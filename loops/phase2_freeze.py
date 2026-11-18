#!/usr/bin/env python3
"""Phase 2 freeze record (spec 3.7 step 1; build step B2, ruled by the owner 2026-11-18).

The freeze is specs/phase2_freeze.json: a list of entries, oldest first. Each entry records
  * the SHA-256 of specs/phase2_spec.md,
  * the SHA-256 of loops/phase2/params.py and its params_hash() (the 16-character hash every report prints),
  * one SHA-256 over every git-tracked file except the record itself ("code tree"): the hash of the sorted lines
    "<sha256 of the file's bytes>  <path>\\n", read from the working tree.
The freeze commit is the commit that adds an entry; the record cannot name its own commit. The last entry before
the first IS number is the binding freeze (re-freezing, a new logged entry, is allowed only before it; spec 3.7).
tests/test_phase2_freeze.py fails when the spec or the params no longer match the last entry.

Both modes refuse a working tree that differs from the index (unstaged edits to tracked files, or untracked files
that are not ignored), so the hash read from the working tree is the hash of what a commit of the index records.

This file lives OUTSIDE loops/phase2 because it runs git (`git ls-files`, `git diff`), which the package's
contracts forbid. It reads files and writes only specs/phase2_freeze.json; it touches no network, no token and no
.env, and it never commits.

Usage:
  .venv/bin/python -B loops/phase2_freeze.py check
        recompute everything and compare with the last entry; exit 1 on any difference
  .venv/bin/python -B loops/phase2_freeze.py write --label B2 --ruled 2026-11-18 --reason "..."
        append an entry computed from the working tree; stage every change first (`git add`), new files
        included, so the working tree and the index agree
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
LOOPS = ROOT / "loops"
if str(LOOPS) not in sys.path:
    sys.path.insert(0, str(LOOPS))

from phase2.params import PARAMS, params_hash, unset  # noqa: E402

RECORD = "specs/phase2_freeze.json"
SPEC = "specs/phase2_spec.md"
PARAMS_FILE = "loops/phase2/params.py"
ET = ZoneInfo("America/New_York")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tracked_files(root: Path = ROOT) -> list[str]:
    """Every git-tracked path (staged new files included), the record itself excluded, sorted."""
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], check=True, capture_output=True).stdout
    paths = sorted(p for p in out.decode().split("\0") if p and p != RECORD)
    if not paths:
        raise SystemExit("freeze: git lists no tracked files")
    return paths


def unstaged(root: Path = ROOT) -> list[str]:
    """Paths where the working tree differs from the index: unstaged edits, and untracked files not ignored."""
    def git(*args: str) -> list[str]:
        out = subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout
        return [p for p in out.decode().split("\0") if p]
    return sorted(set(git("diff", "--name-only", "-z")) | set(git("ls-files", "--others", "--exclude-standard", "-z")))


def tree_hash(root: Path = ROOT, paths: list[str] | None = None) -> tuple[str, int]:
    paths = tracked_files(root) if paths is None else paths
    missing = [p for p in paths if not (root / p).is_file()]
    if missing:
        raise SystemExit(f"freeze: tracked file(s) missing from the working tree: {missing[:5]}")
    lines = "".join(f"{sha256_file(root / p)}  {p}\n" for p in paths)
    return hashlib.sha256(lines.encode()).hexdigest(), len(paths)


def current(root: Path = ROOT) -> dict:
    tree, n = tree_hash(root)
    return dict(spec_sha256=sha256_file(root / SPEC), params_file_sha256=sha256_file(root / PARAMS_FILE),
                params_hash=params_hash(PARAMS), code_tree_sha256=tree, code_tree_files=n)


def load(root: Path = ROOT) -> list[dict]:
    path = root / RECORD
    if not path.exists():
        return []
    entries = json.loads(path.read_text())
    if not isinstance(entries, list):
        raise SystemExit(f"freeze: {RECORD} is not a list of entries")
    return entries


COMPARED = ("spec_sha256", "params_file_sha256", "params_hash", "code_tree_sha256", "code_tree_files")


def check(root: Path = ROOT) -> list[str]:
    """Differences between the working tree and the last entry (empty = matches)."""
    loose = unstaged(root)
    if loose:
        return [f"working tree differs from the index (stage or revert first): {loose}"]
    entries = load(root)
    if not entries:
        return [f"no freeze entry in {RECORD}"]
    last, now = entries[-1], current(root)
    return [f"{k}: frozen {last.get(k)} now {now[k]}" for k in COMPARED if last.get(k) != now[k]]


def write(label: str, ruled: str, reason: str, root: Path = ROOT) -> dict:
    blocking = unset(PARAMS)
    if blocking:
        raise SystemExit(f"freeze refused: params still unset or awaiting a ruling: {blocking}")
    loose = unstaged(root)
    if loose:
        raise SystemExit(f"freeze refused: the working tree differs from the index (stage or revert first): {loose}")
    dt.date.fromisoformat(ruled)
    entry = dict(label=label, ruled=ruled, reason=reason,
                 written=dt.datetime.now(ET).isoformat(timespec="seconds"), **current(root))
    entries = load(root) + [entry]
    (root / RECORD).write_text(json.dumps(entries, indent=2) + "\n")
    return entry


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 2 freeze record (spec 3.7 step 1)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    w = sub.add_parser("write")
    w.add_argument("--label", required=True)
    w.add_argument("--ruled", required=True, help="date of the owner's ruling, YYYY-MM-DD")
    w.add_argument("--reason", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "check":
        diffs = check()
        if diffs:
            print("freeze check: DIFFERS from the last entry\n  " + "\n  ".join(diffs))
            return 1
        print(f"freeze check: matches entry {len(load())} ({load()[-1]['label']})")
        return 0
    entry = write(a.label, a.ruled, a.reason)
    print(json.dumps(entry, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
