#!/usr/bin/env python3
"""Rebuild the deterministic plan projection from active source backups."""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lazograph.features.pending_plans import rebuild_extracted_projection


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild source-backed plans")
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()
    root = Path(os.environ.get("OPENPERSONA_KNOWLEDGE", Path.home() / ".openpersona" / "knowledge"))
    result = rebuild_extracted_projection(root / args.slug)
    print(f"Plans rebuilt: {len(result.plans)} ({len(result.unresolved)} unresolved)")


if __name__ == "__main__":
    main()
