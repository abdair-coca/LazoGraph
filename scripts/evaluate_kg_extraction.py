#!/usr/bin/env python3
"""Evaluate conservative KG person extraction against labeled JSONL cases."""

import argparse
import json
import sys
from pathlib import Path

from kg_extraction import evaluate_cases


def main() -> None:
    parser = argparse.ArgumentParser(description='Evaluate KG extraction precision and recall')
    parser.add_argument('--cases', required=True, type=Path, help='Labeled JSONL cases')
    parser.add_argument('--min-precision', type=float, default=0.90)
    parser.add_argument('--min-recall', type=float, default=0.70)
    args = parser.parse_args()
    try:
        cases = [
            json.loads(line) for line in args.cases.read_text(encoding='utf-8').splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        print(f'Could not read evaluation cases: {exc}', file=sys.stderr)
        raise SystemExit(1) from exc
    report = evaluate_cases(cases)
    print(json.dumps(report, indent=2))
    passed = report['precision'] >= args.min_precision and report['recall'] >= args.min_recall
    raise SystemExit(0 if passed else 1)


if __name__ == '__main__':
    main()
