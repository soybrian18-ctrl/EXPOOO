#!/usr/bin/env python3
"""Loop 3 logging shim -- called via Bash from the equity-research Workflow's
per-candidate stages (the Workflow JS sandbox has no filesystem, so progress is
recorded here in logs/). Satisfies guardrails G3 (per-candidate logging) and G4
(incremental progress survives a kill via the resume file).

Subcommands:
  research_log.py log <LEVEL> <message...>     -> append a line to research_loop.txt
  research_log.py record <ticker> <verdict> <msg...>
        -> append a RESULT line AND upsert logs/research_loop_resume.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# loops/ is on sys.path[0] when run as a script, so loop_common imports directly.
from loop_common import LOGS_DIR, append_log, ensure_logs_dir, iso_now

LOG_FILE = "research_loop.txt"
RESUME_FILE = "research_loop_resume.json"
LOOP_NAME = "equity_research"


def _log(level: str, message: str) -> None:
    append_log(LOG_FILE, f"LOOP={LOOP_NAME} {level} {message}")


def _upsert_resume(entry: dict) -> None:
    """Atomically append a candidate verdict to the resume file (G4)."""
    ensure_logs_dir()
    path = LOGS_DIR / RESUME_FILE
    data = {"evaluated": []}
    if path.exists():
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or "evaluated" not in data:
                data = {"evaluated": []}
        except (ValueError, OSError):
            data = {"evaluated": []}
    data["evaluated"].append(entry)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: research_log.py log|record ...", file=sys.stderr)
        return 2
    cmd = argv[1]
    if cmd == "log":
        level = argv[2] if len(argv) > 2 else "INFO"
        _log(level, " ".join(argv[3:]))
        return 0
    if cmd == "record":
        ticker = argv[2] if len(argv) > 2 else "?"
        verdict = argv[3] if len(argv) > 3 else "?"
        detail = " ".join(argv[4:])
        _log("RESULT", f"ticker={ticker} verdict={verdict} {detail}")
        _upsert_resume({"ts": iso_now(), "ticker": ticker, "verdict": verdict, "detail": detail})
        return 0
    print(f"unknown subcommand: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
