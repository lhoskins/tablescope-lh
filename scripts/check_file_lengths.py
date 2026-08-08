#!/usr/bin/env python3
"""Warn about source files that exceed a line-count threshold.

This is a guardrail, not a gate: it exits 0 so CI does not fail when a file
grows past the threshold, but it prints a warning so the growth is visible.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_THRESHOLD = 500

EXCLUDE_DIRS = {
    ".git",
    ".github",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    "coverage",
    ".next",
    ".mypy_cache",
    ".ruff_cache",
    "redash-8.0.0-7",
}

SOURCE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".java"}


def should_include(path: Path) -> bool:
    if path.suffix.lower() not in SOURCE_EXTENSIONS:
        return False
    for part in path.parts:
        if part in EXCLUDE_DIRS:
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Warn on files over a line-count threshold.")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    parser.add_argument("--exclude", action="append", default=[], help="Directory names to skip")
    parser.add_argument("paths", nargs="*", default=["."], help="Paths to scan")
    args = parser.parse_args()

    exclude = EXCLUDE_DIRS | set(args.exclude)
    offenders: list[tuple[Path, int]] = []

    for root in args.paths:
        root_path = Path(root)
        for path in root_path.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SOURCE_EXTENSIONS:
                continue
            if any(part in exclude for part in path.parts):
                continue
            line_count = sum(1 for _ in path.open("rb"))
            if line_count > args.threshold:
                offenders.append((path, line_count))

    offenders.sort(key=lambda x: x[1], reverse=True)

    if offenders:
        print(f"Files over {args.threshold} lines (warning only):")
        for path, count in offenders:
            print(f"  {count:5d}  {path}")
    else:
        print(f"No files over {args.threshold} lines found.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
