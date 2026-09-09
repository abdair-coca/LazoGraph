"""Minimal product CLI for accepted and demo-ready vertical slices."""

from __future__ import annotations

import argparse
import os
import re
import sys

from lazograph.config import ConfigurationError, knowledge_root, resolve_dataset
from lazograph.domain.identity import IdentityResolutionError
from lazograph.features.ask_person.service import (
    GroundingError,
    answer_about_dataset,
    answer_about_person,
    resolve_question_participant,
)
from lazograph.features.ask_relationship import answer_about_relationship
from lazograph.features.describe_relationship import (
    answer_describe_relationship,
    is_relationship_description_question,
)
from lazograph.features.suggestions import answer_suggestion_question, is_suggestion_question
from lazograph.features.pending_plans import (
    PlanProjectionError,
    answer_plan_question,
    is_plan_question,
    list_plans,
    rebuild_extracted_projection,
    show_plan,
)
from lazograph.features.add_context import (
    ContextValidationError,
    apply_context,
    build_context_preview,
)
from lazograph.features.correct_knowledge import (
    CorrectionLedgerError,
    CorrectionValidationError,
    apply_correction,
    build_correction_preview,
    correction_records,
    undo_correction,
)
from lazograph.infrastructure.llm import (
    HostedProvider,
    LocalExtractiveProvider,
    OllamaProvider,
    ProviderError,
)
from scripts import dataset_invariants, ingest, init_knowledge
from scripts.runtime import configure_safe_output

from .features.import_chat.service import (
    ImportPreview,
    ImportValidationError,
    build_preview,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lazo", description="LazoGraph personal knowledge CLI")
    parser.add_argument("--version", action="version", version="LazoGraph 0.8.0")
    commands = parser.add_subparsers(dest="command", required=True)

    import_parser = commands.add_parser(
        "import",
        help="Preview and import one chat safely",
    )
    import_parser.add_argument("source", help="Chat export path")
    import_parser.add_argument("--slug", required=True, help="Dataset identifier")
    import_parser.add_argument("--persona", required=True, help="Focal participant name")
    import_parser.add_argument(
        "--adapter",
        choices=("chat_export", "universal", "social"),
        help="Override source adapter detection",
    )
    import_parser.add_argument("--since", help="Only import messages after this ISO 8601 date")
    import_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show complete preflight without writing",
    )
    import_parser.add_argument(
        "--yes",
        action="store_true",
        help="Apply after successful preflight without interactive confirmation",
    )
    equivalent = import_parser.add_mutually_exclusive_group()
    equivalent.add_argument(
        "--allow-equivalent-source",
        action="store_true",
        help="Keep both equivalent active backups",
    )
    equivalent.add_argument(
        "--reconcile-equivalent-source",
        action="store_true",
        help="Replace equivalent backups using recoverable quarantine",
    )
    import_parser.set_defaults(handler=_run_import)

    ask_parser = commands.add_parser(
        "ask",
        help="Answer a grounded question about one participant or relationship",
    )
    ask_parser.add_argument("question", help="Question to answer")
    ask_parser.add_argument(
        "--about",
        help="Canonical participant or alias; omit for a two-person relationship question",
    )
    ask_parser.add_argument("--slug", help="Dataset identifier; optional when only one exists")
    ask_parser.add_argument(
        "--provider",
        choices=("auto", "local", "ollama", "hosted"),
        default="auto",
        help="Inference provider: auto (uses LLM if configured), local, ollama, or hosted",
    )
    ask_parser.add_argument("--model", help="Model override for Ollama or hosted provider")
    ask_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum retrieved items; mandatory relationship-path evidence is retained",
    )
    ask_parser.add_argument(
        "--evidence-budget",
        type=int,
        default=5000,
        help="Maximum evidence characters sent to provider",
    )
    ask_parser.add_argument("--json", action="store_true", help="Output structured Answer JSON")
    ask_parser.add_argument(
        "--debug",
        action="store_true",
        help="Print retrieval counts without unrelated private content",
    )
    ask_parser.set_defaults(handler=_run_ask)

    context_parser = commands.add_parser(
        "context",
        help="Preview or add auditable manual context",
    )
    context_parser.add_argument("source", help="UTF-8 text or Markdown context file")
    context_parser.add_argument("--slug", required=True, help="Dataset identifier")
    context_parser.add_argument(
        "--about",
        help="Apply every record to one known participant; otherwise detect from text",
    )
    context_action = context_parser.add_mutually_exclusive_group(required=True)
    context_action.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify and validate without writing",
    )
    context_action.add_argument(
        "--apply",
        action="store_true",
        help="Persist context after a successful preflight",
    )
    context_parser.set_defaults(handler=_run_context)

    correct_parser = commands.add_parser(
        "correct",
        help="Preview or apply an auditable knowledge correction",
    )
    correct_parser.add_argument("text", help="Natural-language relationship correction")
    correct_parser.add_argument("--slug", required=True, help="Dataset identifier")
    correct_action = correct_parser.add_mutually_exclusive_group(required=True)
    correct_action.add_argument("--dry-run", action="store_true", help="Preview without writing")
    correct_action.add_argument("--apply", action="store_true", help="Append to correction ledger")
    correct_parser.set_defaults(handler=_run_correct)

    corrections_parser = commands.add_parser(
        "corrections",
        help="Inspect or undo correction claims",
    )
    corrections_parser.add_argument("--slug", required=True, help="Dataset identifier")
    correction_commands = corrections_parser.add_subparsers(dest="correction_command", required=True)
    list_parser = correction_commands.add_parser("list", help="List immutable correction history")
    list_parser.add_argument("--json", action="store_true", help="Output JSON")
    list_parser.set_defaults(handler=_run_corrections)
    undo_parser = correction_commands.add_parser("undo", help="Undo one active correction claim")
    undo_parser.add_argument("claim_id", help="Correction, assertion, or retraction claim ID")
    undo_parser.add_argument("--json", action="store_true", help="Output JSON")
    undo_parser.set_defaults(handler=_run_corrections)

    plans_parser = commands.add_parser("plans", help="Inspect source-backed plans")
    plan_commands = plans_parser.add_subparsers(dest="plan_command", required=True)
    plans_list = plan_commands.add_parser("list", help="List the derived plan projection")
    plans_list.add_argument("--slug", required=True, help="Dataset identifier")
    plans_list.add_argument("--status", choices=("proposed", "pending", "scheduled", "completed", "cancelled"))
    plans_list.add_argument("--participant", help="Filter by canonical participant name")
    plans_list.add_argument("--json", action="store_true", help="Output JSON")
    plans_list.set_defaults(handler=_run_plans)
    plans_show = plan_commands.add_parser("show", help="Show one plan and its lifecycle")
    plans_show.add_argument("plan_id", help="Stable plan ID")
    plans_show.add_argument("--slug", required=True, help="Dataset identifier")
    plans_show.add_argument("--json", action="store_true", help="Output JSON")
    plans_show.set_defaults(handler=_run_plans)

    ui_parser = commands.add_parser("ui", help="Start local web UI")
    ui_parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default 127.0.0.1)")
    ui_parser.add_argument("--port", type=int, default=8765, help="Port to bind (default 8765)")
    ui_parser.add_argument("--no-browser", action="store_true", help="Do not open browser")
    ui_parser.set_defaults(handler=_run_ui)
    return parser


def _print_preview(preview: ImportPreview) -> None:
    print("Import preflight")
    print(f"  Source: {preview.source}")
    print(f"  Dataset: {preview.slug} ({'existing' if preview.dataset_exists else 'new'})")
    print(f"  Adapter: {preview.adapter}")
    print(f"  Parsed: {preview.parsed_messages}")
    print(f"  Rejected system notices: {preview.rejected_notices}")
    print("  Participants:")
    for participant in preview.participants:
        print(
            f"    - {participant.name}: {participant.identity}, "
            f"{participant.messages} messages, {participant.new_messages} new"
        )
    print(f"  Persona: {preview.persona}")
    print(f"  Duplicates: {preview.duplicates}")
    print(f"  New messages: {preview.new_messages}")
    print(f"  PII flags: {', '.join(preview.pii_flags) if preview.pii_flags else 'none'}")
    if preview.equivalent_sources:
        print("  Equivalent active sources:")
        for match in preview.equivalent_sources:
            print(
                f"    - {match['filename']}: {match['coverage']:.1%} overlap, "
                f"{match['size_ratio']:.1%} size ratio"
            )
    else:
        print("  Equivalent active sources: none")


def _confirm() -> bool:
    try:
        return input("Apply import? [y/N] ").strip().casefold() in {"y", "yes"}
    except EOFError:
        return False


def _run_import(args: argparse.Namespace) -> int:
    root = knowledge_root()
    try:
        preview = build_preview(
            args.source,
            slug=args.slug,
            persona=args.persona,
            adapter_name=args.adapter,
            since=args.since,
            root=root,
        )
    except ImportValidationError as exc:
        print(f"Import rejected: {exc}", file=sys.stderr)
        return 2

    _print_preview(preview)

    if args.dry_run:
        print("Dry run complete. No files written.")
        return 0

    if preview.same_source_reimport:
        result = dataset_invariants.validate_dataset(preview.dataset_dir)
        if not dataset_invariants.print_report(result):
            return 2
        print("Already imported. Dataset unchanged.")
        return 0

    if preview.equivalent_sources and not (
        args.allow_equivalent_source or args.reconcile_equivalent_source
    ):
        print(
            "Import stopped before writes. Use --reconcile-equivalent-source "
            "or --allow-equivalent-source.",
            file=sys.stderr,
        )
        return 2

    if not args.yes and not _confirm():
        print("Import cancelled. No files written.")
        return 1

    if not preview.dataset_exists:
        init_knowledge.init_dataset(
            args.slug,
            preview.persona,
            knowledge_root=root,
        )

    ingest_args = [
        "--slug",
        args.slug,
        "--source",
        str(preview.source),
        "--adapter",
        preview.adapter,
        "--persona-name",
        preview.persona,
        "--persona-exact",
    ]
    if args.since:
        ingest_args.extend(("--since", args.since))
    if args.allow_equivalent_source:
        ingest_args.append("--allow-equivalent-source")
    if args.reconcile_equivalent_source:
        ingest_args.append("--reconcile-equivalent-source")

    try:
        ingest.main(ingest_args, knowledge_root=root)
    except SystemExit as exc:
        return int(exc.code or 0)

    result = dataset_invariants.validate_dataset(preview.dataset_dir)
    if not dataset_invariants.print_report(result):
        return 2
    try:
        extraction = rebuild_extracted_projection(preview.dataset_dir)
    except PlanProjectionError as exc:
        print(f"Import completed, but plan projection failed: {exc}", file=sys.stderr)
        return 2
    print(f"Plans derived: {len(extraction.plans)} ({len(extraction.unresolved)} unresolved)")
    print("Import complete.")
    return 0


def _answer_provider(args: argparse.Namespace):
    if args.provider == "ollama":
        return OllamaProvider(model=args.model)
    if args.provider == "hosted":
        return HostedProvider(model=args.model)
    if args.provider == "auto":
        if (
            os.environ.get("LAZOGRAPH_HOSTED_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        ):
            try:
                return HostedProvider(model=args.model)
            except Exception:
                return LocalExtractiveProvider()
        return LocalExtractiveProvider()
    return LocalExtractiveProvider()


def _print_answer(answer, *, debug: bool) -> None:
    print(answer.text)
    print(f"Confidence: {answer.confidence:.2f}")
    if answer.citations:
        print("Citations:")
        for evidence in answer.citations:
            timestamp = evidence.timestamp or "unknown time"
            print(
                f"  [{evidence.message_id}] {evidence.sender}, {timestamp}, "
                f"score={evidence.score:.4f}"
            )
            if evidence.source_type in {"user_context", "user_correction"}:
                print(
                    f"    provenance: {evidence.record_kind}; authority={evidence.authority}; "
                    f"authored_by={evidence.authored_by}"
                )
            print(f"    {evidence.excerpt}")
    else:
        print("Citations: none")
    if debug:
        print("Retrieval:")
        for key, value in answer.retrieval_summary.items():
            print(f"  {key}: {value}")
    if answer.suggestions:
        print("Suggestions:")
        for suggestion in answer.suggestions:
            print(f"  {suggestion}")
    if answer.missing_information:
        print("Missing information:")
        for item in answer.missing_information:
            print(f"  {item}")


def _looks_like_relationship_question(question: str) -> bool:
    return bool(re.search(
        r"\b(?:relationship|relation|related|connected|relación|relacionado|"
        r"conectado|vínculo|vinculo|pareja|amigo|amiga|hermano|hermana|"
        r"colleague|coworker|parent|child|manager|jefe|familia)\b",
        question,
        re.IGNORECASE,
    ))


def _run_ask(args: argparse.Namespace) -> int:
    if args.limit < 1:
        print("Ask rejected: --limit must be at least 1.", file=sys.stderr)
        return 2
    if args.evidence_budget < 100:
        print("Ask rejected: --evidence-budget must be at least 100.", file=sys.stderr)
        return 2
    try:
        dataset_dir = resolve_dataset(args.slug)
        provider = _answer_provider(args)
        if args.about:
            answer = answer_about_person(
                dataset_dir,
                args.question,
                args.about,
                provider,
                limit=args.limit,
                evidence_budget=args.evidence_budget,
            )
        elif is_plan_question(args.question):
            answer = answer_plan_question(dataset_dir, args.question)
        elif is_suggestion_question(args.question):
            answer = answer_suggestion_question(
                dataset_dir,
                args.question,
                provider,
                limit=args.limit,
                evidence_budget=args.evidence_budget,
            )
        elif is_relationship_description_question(args.question):
            answer = answer_describe_relationship(
                dataset_dir,
                args.question,
                provider,
                limit=args.limit,
                evidence_budget=args.evidence_budget,
            )
        else:
            mentioned = resolve_question_participant(dataset_dir, args.question)
            if mentioned is not None:
                answer = answer_about_person(
                    dataset_dir,
                    args.question,
                    str(mentioned["name"]),
                    provider,
                    limit=args.limit,
                    evidence_budget=args.evidence_budget,
                )
            elif _looks_like_relationship_question(args.question):
                answer = answer_about_relationship(
                    dataset_dir,
                    args.question,
                    provider,
                    limit=args.limit,
                    evidence_budget=args.evidence_budget,
                )
            else:
                answer = answer_about_dataset(
                    dataset_dir,
                    args.question,
                    provider,
                    limit=args.limit,
                    evidence_budget=args.evidence_budget,
                )
    except (
        ConfigurationError,
        IdentityResolutionError,
        GroundingError,
        ProviderError,
        RuntimeError,
        OSError,
    ) as exc:
        print(f"Ask failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        import json

        print(json.dumps(answer.to_dict(), indent=2, ensure_ascii=False))
    else:
        _print_answer(answer, debug=args.debug)
    return 0


def _run_plans(args: argparse.Namespace) -> int:
    try:
        dataset_dir = resolve_dataset(args.slug)
        if args.plan_command == "show":
            plan = show_plan(dataset_dir, args.plan_id)
            payload = plan.to_dict()
        else:
            plans = list_plans(
                dataset_dir,
                status=args.status,
                participant=args.participant,
            )
            payload = [plan.to_dict() for plan in plans]
    except (ConfigurationError, PlanProjectionError, OSError) as exc:
        print(f"Plans failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        import json

        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    plans = [plan] if args.plan_command == "show" else plans
    print(f"Plans: {len(plans)}")
    for item in plans:
        scheduled = item.scheduled_for.isoformat() if item.scheduled_for else "unscheduled"
        print(f"  {item.id} [{item.status}] {item.title}")
        print(f"    participants: {', '.join(item.participants) or 'none'}")
        print(f"    scheduled: {scheduled}; location: {item.location or 'unknown'}")
        print(f"    sources: {', '.join(item.source_ids)}")
        for transition in item.transitions:
            print(
                f"    {transition.from_status} -> {transition.to_status} "
                f"at {transition.occurred_at.isoformat()} "
                f"[{', '.join(transition.source_ids)}]"
            )
    return 0


def _print_context_preview(preview) -> None:
    print("Manual context preflight")
    print(f"  Source: {preview.source}")
    print(f"  Dataset: {preview.dataset_dir.name}")
    print(f"  Source hash: {preview.source_sha256}")
    print(f"  Records: {len(preview.records)} ({preview.new_records} new, {preview.duplicates} duplicates)")
    print(f"  PII flags: {', '.join(preview.pii_flags) if preview.pii_flags else 'none'}")
    for record in preview.records:
        status = "duplicate" if record.duplicate else "new"
        print(
            f"    {record.number}. {record.kind} about {record.subject}; "
            f"authority={record.authority}; confidence={record.confidence:.2f}; {status}"
        )
        print(f"       {record.content[:160]}")


def _run_context(args: argparse.Namespace) -> int:
    try:
        dataset_dir = resolve_dataset(args.slug)
        preview = build_context_preview(
            args.source,
            dataset_dir,
            about=args.about,
        )
    except (ConfigurationError, ContextValidationError, OSError) as exc:
        print(f"Context rejected: {exc}", file=sys.stderr)
        return 2

    _print_context_preview(preview)
    if args.dry_run:
        print("Dry run complete. No files written.")
        return 0
    try:
        result = apply_context(preview)
    except (ContextValidationError, RuntimeError, OSError) as exc:
        print(f"Context apply failed: {exc}", file=sys.stderr)
        return 2
    if not result.stored_records:
        print("Already stored. Dataset unchanged.")
        return 0
    print("Context applied.")
    print(f"  Stored records: {result.stored_records}")
    print(f"  Duplicate records skipped: {result.duplicates}")
    print(f"  Vectors stored: {result.vector_count}")
    print(f"  Source backup: sources/{result.source_file}")
    print("  Dataset invariants: passed")
    return 0


def _print_correction_preview(preview) -> None:
    print("Knowledge correction preflight")
    print(f"  Dataset: {preview.dataset_slug}")
    print(f"  Fingerprint: {preview.fingerprint}")
    print(f"  PII flags: {', '.join(preview.pii_flags) if preview.pii_flags else 'none'}")
    print(f"  Matched effective claims: {len(preview.matched_claims)}")
    if preview.already_applied:
        print("  Status: already applied; no write required")
    for claim in preview.matched_claims:
        print(
            f"    - {claim.subject} --{claim.predicate}--> {claim.object}; "
            f"confidence={claim.confidence:.2f}; source={claim.source or 'unknown'}"
        )
    print(
        f"  Retract: {preview.retract.subject} --{preview.retract.predicate}--> "
        f"{preview.retract.object}"
    )
    print(
        f"  Assert: {preview.assert_claim.subject} --{preview.assert_claim.predicate}--> "
        f"{preview.assert_claim.object}; confidence=1.00; authority=user"
    )


def _run_correct(args: argparse.Namespace) -> int:
    try:
        dataset_dir = resolve_dataset(args.slug)
        preview = build_correction_preview(args.text, dataset_dir)
    except (ConfigurationError, CorrectionValidationError, RuntimeError, OSError) as exc:
        print(f"Correction rejected: {exc}", file=sys.stderr)
        return 2
    _print_correction_preview(preview)
    if args.dry_run:
        print("Dry run complete. No files written.")
        return 0
    try:
        result = apply_correction(preview)
    except (ConfigurationError, CorrectionValidationError, CorrectionLedgerError, RuntimeError, OSError) as exc:
        print(f"Correction apply failed: {exc}", file=sys.stderr)
        return 2
    record = result["record"]
    if not result["appended"]:
        print(f'Already applied. Active claim: {record["claim_id"]}')
        return 0
    print("Correction applied.")
    print(f'  Claim ID: {record["claim_id"]}')
    print("  Generated graph/source data: unchanged")
    print("  Effective graph: updated")
    return 0


def _run_corrections(args: argparse.Namespace) -> int:
    try:
        dataset_dir = resolve_dataset(args.slug)
        if args.correction_command == "undo":
            result = undo_correction(dataset_dir, args.claim_id)
            if args.json:
                import json

                print(json.dumps(result, indent=2, ensure_ascii=False))
            elif result["appended"]:
                print(f'Correction undone: {result["record"]["claim_id"]}')
                print(f'Undo event: {result["event"]["event_id"]}')
            else:
                print(f'Already undone: {result["record"]["claim_id"]}')
            return 0
        records = correction_records(dataset_dir)
    except (ConfigurationError, CorrectionLedgerError, RuntimeError, OSError) as exc:
        print(f"Corrections failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        import json

        print(json.dumps(records, indent=2, ensure_ascii=False))
        return 0
    print(f"Corrections: {len(records)}")
    for record in records:
        assertion = record["assert"]
        retraction = record["retract"]
        print(f'  {record["claim_id"]} [{record["status"]}] {record["created_at"]}')
        print(
            f'    retract {retraction["subject"]} --{retraction["predicate"]}--> '
            f'{retraction["object"]}'
        )
        print(
            f'    assert  {assertion["subject"]} --{assertion["predicate"]}--> '
            f'{assertion["object"]}'
        )
    return 0


def _run_ui(args: argparse.Namespace) -> int:
    try:
        from lazograph.ui.app import create_app
    except Exception as exc:
        print(f"UI unavailable: {exc}", file=sys.stderr)
        return 2
    import webbrowser

    app = create_app()
    url = f"http://{args.host}:{args.port}"
    print(f"LazoGraph UI at {url} (local only)")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        import uvicorn

        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    except OSError as exc:
        print(f"UI failed to start: {exc}", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_safe_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
