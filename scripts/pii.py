"""Shared PII detection and deterministic redaction."""

import re
from collections import Counter
from pathlib import Path


PII_PATTERNS = (
    (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), 'SSN'),
    (re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'), 'credit_card'),
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'), 'email'),
    (re.compile(r'\b(?:password|passwd|pwd)\s*[:=]\s*\S+', re.IGNORECASE), 'password'),
    (re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'), 'phone'),
)


def scan_text(text: str) -> dict[str, int]:
    counts = Counter()
    for pattern, label in PII_PATTERNS:
        counts[label] += len(pattern.findall(text))
    return dict(sorted((label, count) for label, count in counts.items() if count))


def redact_text(text: str) -> tuple[str, dict[str, int]]:
    counts = Counter()
    redacted = text
    for pattern, label in PII_PATTERNS:
        redacted, count = pattern.subn(f'[REDACTED_{label.upper()}]', redacted)
        counts[label] += count
    return redacted, dict(sorted((label, count) for label, count in counts.items() if count))


def scan_export_inputs(dataset_dir: Path, *, include_sources: bool) -> dict:
    """Scan only files that can contribute content to one export."""
    files = []
    wiki_dir = dataset_dir / 'wiki'
    if wiki_dir.exists():
        files.extend(sorted(wiki_dir.glob('*.md')))
    if include_sources:
        sources_dir = dataset_dir / 'sources'
        if sources_dir.exists():
            files.extend(
                path for path in sorted(sources_dir.iterdir())
                if not path.name.startswith('.')
                and path.suffix.casefold() in {'.jsonl', '.txt', '.json', '.csv'}
            )
    totals = Counter()
    affected_files = []
    for path in files:
        try:
            counts = scan_text(path.read_text(encoding='utf-8', errors='replace'))
        except OSError:
            continue
        if counts:
            affected_files.append({'area': path.parent.name, 'filename': path.name, 'counts': counts})
            totals.update(counts)
    return {
        'total': sum(totals.values()),
        'types': dict(sorted(totals.items())),
        'affected_files': affected_files,
    }


def merge_counts(target: Counter, counts: dict[str, int]) -> None:
    target.update(counts)
