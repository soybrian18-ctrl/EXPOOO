#!/usr/bin/env python3
"""Loop 1 -- Morning Stop Check (Pattern 1: Retry loop).

Trigger:   launchd, weekdays 08:45 local (see deploy/launchd/).
Action:    Pre-flight token validation, then run stop_check.py as a subprocess
           (hard 60s timeout per attempt) and interpret its exit code.
Evaluator: exit 0 = all clear; exit 3 = stop flags exist; exit 2 = config/auth
           (token) error; exit 1 / 124 (timeout) = transient API/network error.
Retry:     DEFINITIVE results (0 or 3) stop immediately. AUTH errors (2) do not
           retry (a retry can't help) -- notify. TRANSIENT failures retry up to
           MAX_RETRIES with backoff, then give up with a notification.
Stop:      Definitive result, OR auth error, OR retries exhausted -> always
           terminates (bounded by MAX_RETRIES).
Output:    If flags exist (exit 3) -> macOS notification with the exact flagged
           positions, and the full stop_check report is appended to the log.
           Every run is logged to logs/stop_check_history.txt with timestamp
           and result.

Guardrails: MAX_RETRIES cap in LOOP_CONFIG (G1); 60s/attempt subprocess timeout
(G2); start-of-attempt log line (G3); clean-exit handler writing a FINAL line if
killed mid-run, e.g. during backoff (G4). Run via:
    loops/run.sh loops/morning_stop_check.py
"""

from __future__ import annotations

import os
import re
import sys
import time

import loop_common as lc  # module import so run_subprocess/notify are patchable in tests

# ===========================================================================
# LOOP_CONFIG  -- all tunables here; never hardcoded inline (guardrail G1)
# ===========================================================================
LOOP_CONFIG = {
    "LOOP_NAME": "morning_stop_check",
    "MAX_RETRIES": 3,                    # G1: hard cap on attempts
    "ITERATION_TIMEOUT_SECONDS": 60,     # G2: per-attempt subprocess timeout
    "BACKOFF_SECONDS": [10, 20],         # waits between transient retries
    "REFRESH_WARN_DAYS": 6.0,
    "REFRESH_CRITICAL_DAYS": 6.5,
    "STOP_CHECK_SCRIPT": "stop_check.py",
    "LOG_FILE": "stop_check_history.txt",
    "NOTIFY_TITLE": "Schwab Stop Check",
    "SUBPROCESS_COLUMNS": "200",         # widen captured output so rows don't wrap
    "MAX_NOTIFY_CHARS": 220,
}

# stop_check.py exit-code taxonomy (verified against render.run_cli + stop_check)
EXIT_ALL_CLEAR = 0
EXIT_FLAGS = 3
EXIT_AUTH = 2
TRANSIENT_CODES = {1, 124}  # 1 = API/network error, 124 = our subprocess timeout

# Matches a flagged row in stop_check's "Positions at Risk" table. The LONG/SHORT
# side column anchors it to a table row (so warning-panel title lines, which lack
# a side, are NOT matched -- avoiding double counting).
_FLAG_ROW_RE = re.compile(
    r"^\s*([A-Z][A-Z0-9.\-]{0,9})\s+(?:LONG|SHORT)\b.*?(STOP BREACHED|AT RISK|DAY TIF)"
)


def parse_stop_flags(stripped_output: str) -> list[str]:
    """Extract ``"<SYMBOL> <ISSUE>"`` for each flagged position, deduped/ordered."""
    out: list[str] = []
    seen: set[str] = set()
    for line in stripped_output.splitlines():
        m = _FLAG_ROW_RE.search(line)
        if m:
            item = f"{m.group(1)} {m.group(2)}"
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


def _log(message: str) -> None:
    lc.append_log(LOOP_CONFIG["LOG_FILE"], f"LOOP={LOOP_CONFIG['LOOP_NAME']} {message}")


def main() -> int:
    state = {"attempt": 0, "result": "not_started", "finalized": False}

    def finalize(reason: str) -> None:
        if state["finalized"]:
            return
        state["finalized"] = True
        _log(
            f"FINAL reason={reason} attempts={state['attempt']}/"
            f"{LOOP_CONFIG['MAX_RETRIES']} result={state['result']}"
        )

    def complete(code: int, result: str) -> int:
        state["result"] = result
        state["finalized"] = True  # normal completion -> suppress FINAL (reserved for kills)
        return code

    lc.install_clean_exit(finalize)

    token_path = lc.resolve_token_path()

    # --- Pre-flight token validation (required for every API-touching loop) ---
    tok = lc.validate_token(
        token_path,
        warn_days=LOOP_CONFIG["REFRESH_WARN_DAYS"],
        critical_days=LOOP_CONFIG["REFRESH_CRITICAL_DAYS"],
    )
    if not tok.ok:
        _log(f"PREFLIGHT token_invalid status={tok.status} reason=\"{tok.reason}\"")
        lc.notify(
            LOOP_CONFIG["NOTIFY_TITLE"],
            f"Stop check skipped: {tok.reason}. Re-run setup_auth.py.",
        )
        _log("RESULT result=skipped_token_invalid notified=True")
        return complete(EXIT_AUTH, "skipped_token_invalid")

    env = {**os.environ, "COLUMNS": LOOP_CONFIG["SUBPROCESS_COLUMNS"]}
    cmd = [sys.executable, LOOP_CONFIG["STOP_CHECK_SCRIPT"]]

    # --- Bounded retry loop (cannot run forever: range over MAX_RETRIES) ---
    for attempt in range(1, LOOP_CONFIG["MAX_RETRIES"] + 1):
        state["attempt"] = attempt
        _log(
            f"START attempt={attempt}/{LOOP_CONFIG['MAX_RETRIES']} ts={lc.iso_now()} "
            f"token_valid=True token_status={tok.status}"
        )

        res = lc.run_subprocess(
            cmd,
            timeout_s=LOOP_CONFIG["ITERATION_TIMEOUT_SECONDS"],
            env=env,
        )
        _log(
            f"ATTEMPT attempt={attempt} exit={res.exit_code} "
            f"timed_out={res.timed_out} duration_s={round(res.duration_s, 2)}"
        )

        code = res.exit_code

        if code == EXIT_ALL_CLEAR:
            _log("RESULT result=all_clear notified=False")
            return complete(EXIT_ALL_CLEAR, "all_clear")

        if code == EXIT_FLAGS:
            stripped = lc.strip_ansi(res.stdout)
            flags = parse_stop_flags(stripped)
            detail = "; ".join(flags) if flags else "stop flags detected (see log)"
            msg = f"⚠ {len(flags) or ''} stop flag(s): {detail}".strip()
            if len(msg) > LOOP_CONFIG["MAX_NOTIFY_CHARS"]:
                msg = msg[: LOOP_CONFIG["MAX_NOTIFY_CHARS"] - 1] + "…"
            notified = lc.notify(LOOP_CONFIG["NOTIFY_TITLE"], msg)
            _log(f"RESULT result=flags flags=\"{detail}\" notified={notified}")
            # Persist the full report so the exact details are in the history log.
            _log("REPORT-BEGIN")
            for line in stripped.splitlines():
                lc.append_log(LOOP_CONFIG["LOG_FILE"], "    " + line)
            _log("REPORT-END")
            return complete(EXIT_FLAGS, "flags")

        if code == EXIT_AUTH:
            _log("RESULT result=auth_error notified=True")
            lc.notify(
                LOOP_CONFIG["NOTIFY_TITLE"],
                "Stop check could not run (token/config error). Re-run setup_auth.py.",
            )
            return complete(EXIT_AUTH, "auth_error")

        # --- Transient (or unknown) failure -> retry within the cap ---
        is_transient = code in TRANSIENT_CODES
        kind = "transient" if is_transient else f"unexpected({code})"
        _log(f"FAILURE kind={kind} attempt={attempt}/{LOOP_CONFIG['MAX_RETRIES']}")
        if attempt < LOOP_CONFIG["MAX_RETRIES"]:
            backoff_list = LOOP_CONFIG["BACKOFF_SECONDS"]
            backoff = backoff_list[min(attempt - 1, len(backoff_list) - 1)]
            _log(f"BACKOFF sleeping_s={backoff} before retry")
            time.sleep(backoff)
            continue
        # Retries exhausted
        _log(f"RESULT result=transient_exhausted attempts={attempt} notified=True")
        lc.notify(
            LOOP_CONFIG["NOTIFY_TITLE"],
            f"Stop check failed after {LOOP_CONFIG['MAX_RETRIES']} attempts "
            "(API/network). Investigate.",
        )
        return complete(1, "transient_exhausted")

    # Unreachable: the loop always returns. Defensive backstop.
    return complete(1, "unreachable")


if __name__ == "__main__":
    sys.exit(main())
