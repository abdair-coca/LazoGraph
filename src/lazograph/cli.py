"""Minimal product CLI for accepted and demo-ready vertical slices."""

from __future__ import annotations

import argparse
import sys

from scripts import dataset_invariants, ingest, init_knowledge
from scripts.runtime import configure_safe_output

from .features.import_chat.service import (
    ImportPreview,
    ImportValidationError,
    build_preview,
    knowledge_root,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lazo", description="LazoGraph personal knowledge CLI")
    parser.add_argument("--version", action="version", version="LazoGraph 0.4.0")
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


def main(argv: list[str] | None = None) -> int:
    configure_safe_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))

