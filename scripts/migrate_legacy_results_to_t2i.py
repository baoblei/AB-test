#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


RESERVED_DIRS = {"T2I", "TI2I"}


def find_legacy_versions(results_dir: Path) -> list[Path]:
    if not results_dir.exists():
        raise FileNotFoundError(f"results directory not found: {results_dir}")
    return sorted(
        path
        for path in results_dir.iterdir()
        if path.is_dir() and path.name not in RESERVED_DIRS
    )


def migrate(results_dir: Path, dry_run: bool = False) -> tuple[list[str], list[str]]:
    target_root = results_dir / "T2I"
    legacy_versions = find_legacy_versions(results_dir)
    moved: list[str] = []
    skipped: list[str] = []

    if not legacy_versions:
        return moved, skipped

    if not dry_run:
        target_root.mkdir(parents=True, exist_ok=True)

    for version_dir in legacy_versions:
        target_dir = target_root / version_dir.name
        if target_dir.exists():
            skipped.append(
                f"skip {version_dir.name}: target already exists at {target_dir}"
            )
            continue
        moved.append(f"move {version_dir} -> {target_dir}")
        if not dry_run:
            shutil.move(str(version_dir), str(target_dir))

    return moved, skipped


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate legacy results/<version>/<scene> directories into results/T2I/<version>/<scene>."
    )
    parser.add_argument(
        "--results-dir",
        default="results",
        help="Path to the results directory. Defaults to ./results",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without moving directories.",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir).resolve()
    try:
        moved, skipped = migrate(results_dir, dry_run=args.dry_run)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not moved and not skipped:
        print("No legacy version directories found under results/.")
        return 0

    for line in moved:
        print(line)
    for line in skipped:
        print(line)

    if args.dry_run:
        print("Dry run complete.")
    else:
        print("Migration complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
