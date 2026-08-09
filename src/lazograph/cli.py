"""Minimal product CLI for accepted and demo-ready vertical slices."""

from __future__ import annotations

import argparse
import sys

from lazograph.config import ConfigurationError, knowledge_root, resolve_dataset
from lazograph.domain.identity import IdentityResolutionError
from lazograph.features.ask_person.service import GroundingError, answer_about_person
from lazograph.features.add_context import ContextValidationError, build_context_preview
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
    parser.add_argument("--version", action="version", version="LazoGraph 0.5.0")
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
        help="Answer a grounded question about one participant",
    )
    ask_parser.add_argument("question", help="Question to answer")
    ask_parser.add_argument("--about", required=True, help="Canonical participant or alias")
    ask_parser.add_argument("--slug", help="Dataset identifier; optional when only one exists")
    ask_parser.add_argument(
        "--provider",
        choices=("local", "ollama", "hosted"),
        default="local",
        help="Inference provider (default: local extractive)",
    )
    ask_parser.add_argument("--model", help="Model override for Ollama or hosted provider")
    ask_parser.add_argument("--limit", type=int, default=5, help="Maximum evidence items")
    ask_parser.add_argument(
        "--evidence-budget",
        type=int,
        default=2500,
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
    print("Import complete.")
    return 0


def _answer_provider(args: argparse.Namespace):
    if args.provider == "ollama":
        return OllamaProvider(model=args.model)
    if args.provider == "hosted":
        return HostedProvider(model=args.model)
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
            print(f"    {evidence.excerpt}")
    else:
        print("Citations: none")
    if debug:
        print("Retrieval:")
        for key, value in answer.retrieval_summary.items():
            print(f"  {key}: {value}")


def _run_ask(args: argparse.Namespace) -> int:
    if args.limit < 1:
        print("Ask rejected: --limit must be at least 1.", file=sys.stderr)
        return 2
    if args.evidence_budget < 100:
        print("Ask rejected: --evidence-budget must be at least 100.", file=sys.stderr)
        return 2
    try:
        dataset_dir = resolve_dataset(args.slug)
        answer = answer_about_person(
            dataset_dir,
            args.question,
            args.about,
            _answer_provider(args),
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
    print("Context apply is not available in this implementation increment.", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    configure_safe_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))
