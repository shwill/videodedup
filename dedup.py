#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import xxhash

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".3gp", ".wmv", ".flv", ".webm", ".mpeg", ".mpg", ".mpe"}
QUICK_HASH_BYTES = 65536


def scan(folder: Path) -> list[Path]:
    return [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS]


def quick_hash(path: Path) -> str:
    h = xxhash.xxh64()
    with open(path, "rb") as f:
        h.update(f.read(QUICK_HASH_BYTES))
    return h.hexdigest()


def full_hash(path: Path) -> str:
    h = xxhash.xxh64()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def ffprobe_tags(path: Path) -> dict:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        return data.get("format", {}).get("tags", {})
    except Exception:
        return {}


def metadata_score(tags: dict) -> int:
    return sum(1 for v in tags.values() if v and str(v).strip())


def creation_date(path: Path, tags: dict) -> datetime | None:
    for key in ("creation_time", "date", "com.apple.quicktime.creationdate"):
        val = tags.get(key)
        if val:
            for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(val[:26], fmt)
                except ValueError:
                    continue
    return datetime.fromtimestamp(path.stat().st_mtime)


def safe_rename(path: Path, new_name: str) -> Path:
    target = path.parent / new_name
    if target == path:
        return path
    stem, suffix = os.path.splitext(new_name)
    counter = 1
    while target.exists():
        target = path.parent / f"{stem}_{counter}{suffix}"
        counter += 1
    return target


def find_duplicates(files: list[Path]) -> list[list[Path]]:
    by_quick: dict[str, list[Path]] = defaultdict(list)
    for f in files:
        by_quick[quick_hash(f)].append(f)

    groups = []
    for candidates in by_quick.values():
        if len(candidates) < 2:
            continue
        by_full: dict[str, list[Path]] = defaultdict(list)
        for f in candidates:
            by_full[full_hash(f)].append(f)
        for group in by_full.values():
            if len(group) > 1:
                groups.append(group)
    return groups


def pick_winner(group: list[Path]) -> tuple[Path, list[Path]]:
    scored = []
    for f in group:
        tags = ffprobe_tags(f)
        scored.append((metadata_score(tags), f.stat().st_mtime * -1, f, tags))
    scored.sort(reverse=True)
    winner = scored[0][2]
    losers = [s[2] for s in scored[1:]]
    return winner, losers


def process(folder: Path, dry_run: bool) -> None:
    files = scan(folder)
    print(f"Found {len(files)} video file(s)")

    groups = find_duplicates(files)
    print(f"Found {len(groups)} duplicate group(s)")

    deleted_lines = []
    renamed_lines = []
    unchanged_lines = []

    all_losers: set[Path] = set()
    winner_info: list[tuple[Path, dict]] = []

    for group in groups:
        winner, losers = pick_winner(group)
        all_losers.update(losers)
        tags = ffprobe_tags(winner)
        winner_info.append((winner, tags))
        for loser in losers:
            if not dry_run:
                loser.unlink()
            deleted_lines.append(f"  {loser.name}  →  deleted (duplicate of {winner.name})")

    already_renamed: set[Path] = set()
    for path in files:
        if path in all_losers:
            continue
        tags = ffprobe_tags(path)
        date = creation_date(path, tags)
        if date:
            new_name = date.strftime("%Y-%m-%d_%H%M%S") + path.suffix.lower()
            target = safe_rename(path, new_name)
            if target != path:
                if not dry_run:
                    path.rename(target)
                renamed_lines.append(f"  {path.name}  →  {target.name}")
                already_renamed.add(path)
            else:
                unchanged_lines.append(f"  {path.name}  (already correctly named)")
        else:
            unchanged_lines.append(f"  {path.name}  (no date metadata)")

    report_lines = ["=== DELETED (Duplicates) ==="]
    report_lines += deleted_lines or ["  none"]
    report_lines += ["\n=== RENAMED ==="]
    report_lines += renamed_lines or ["  none"]
    report_lines += ["\n=== UNCHANGED ==="]
    report_lines += unchanged_lines or ["  none"]

    if dry_run:
        report_lines.insert(0, "=== DRY RUN — no files were modified ===\n")

    report = "\n".join(report_lines)
    print(report)

    report_path = folder / "dedup_report.txt"
    report_path.write_text(report)
    print(f"\nReport written to {report_path}")


def main():
    parser = argparse.ArgumentParser(description="Deduplicate and rename video files")
    parser.add_argument("folder", nargs="?", default="/data", help="Folder to process")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without modifying files")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Error: {folder} is not a directory", file=sys.stderr)
        sys.exit(1)

    process(folder, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
