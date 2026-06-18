#!/usr/bin/env python3
"""Loop 2 -- End-of-Day Portfolio Logger (Pattern 2: Pipeline loop).

Trigger:   launchd, weekdays 16:15 local (see deploy/launchd/).
Pipeline:  validate token -> run portfolio.py (hard 60s timeout) -> capture full
           output -> strip ANSI -> append a timestamped snapshot block to
           logs/portfolio_history.txt -> verify the write -> notify.
Evaluator: portfolio.py exit 0 AND the append is verified (file grew + the
           snapshot's END marker is present in the tail).
Stop:      Single run per day (MAX_ITERATIONS = 1).
Output:    Plain-text (ANSI-stripped) timestamped snapshot in the history file;
           a desktop notification confirming the snapshot was saved (enriched
           with Net Liq / Open P/L when parseable), or a failure notification.

Guardrails: MAX_ITERATIONS cap in LOOP_CONFIG (G1); 60s subprocess timeout (G2);
start-of-iteration log line (G3); clean-exit handler writing a FINAL line if
killed mid-run (G4). Pre-flight token validation before the API call. Run via:
    loops/run.sh loops/eod_portfolio_logger.py
"""

from __future__ import annotations

import os
import re
import sys

import loop_common as lc  # module import so helpers are patchable in tests

# ===========================================================================
# LOOP_CONFIG  -- all tunables here; never hardcoded inline (guardrail G1)
# ===========================================================================
LOOP_CONFIG = {
    "LOOP_NAME": "eod_portfolio_logger",
    "MAX_ITERATIONS": 1,                 # single run per day (G1)
    "ITERATION_TIMEOUT_SECONDS": 60,     # G2: subprocess timeout
    "REFRESH_WARN_DAYS": 6.0,
    "REFRESH_CRITICAL_DAYS": 6.5,
    "PORTFOLIO_SCRIPT": "portfolio.py",
    "HISTORY_FILE": "portfolio_history.txt",   # the timestamped snapshot archive
    "LOG_FILE": "portfolio_logger.txt",        # operational START/RESULT/FINAL log
    "NOTIFY_TITLE": "Schwab Portfolio Logger",
    "SUBPROCESS_COLUMNS": "120",
}

EXIT_OK = 0
EXIT_AUTH = 2


def _log(message: str) -> None:
    lc.append_log(LOOP_CONFIG["LOG_FILE"], f"LOOP={LOOP_CONFIG['LOOP_NAME']} {message}")


def summarize(stripped: str) -> str:
    """Best-effort one-line summary for the notification (never raises)."""
    parts = []
    m = re.search(
        r"Deployed\s+\$([\d,]+\.\d{2}).*?Cash\s+\$([\d,]+\.\d{2})", stripped, re.S
    )
    if m:
        try:
            nl = float(m.group(1).replace(",", "")) + float(m.group(2).replace(",", ""))
            parts.append(f"Net Liq ~${nl:,.2f}")
        except ValueError:
            pass
    m2 = re.search(
        r"Total Open P/L\s+([+\-]?\$[\d,]+\.\d{2})\s+([+\-]?[\d.]+%)", stripped
    )
    if m2:
        parts.append(f"Open P/L {m2.group(1)} ({m2.group(2)})")
    return " · ".join(parts)


def main() -> int:
    state = {"attempt": 0, "result": "not_started", "finalized": False}

    def finalize(reason: str) -> None:
        if state["finalized"]:
            return
        state["finalized"] = True
        _log(f"FINAL reason={reason} attempts={state['attempt']} result={state['result']}")

    def complete(code: int, result: str) -> int:
        state["result"] = result
        state["finalized"] = True  # normal completion -> suppress FINAL
        return code

    lc.install_clean_exit(finalize)

    token_path = lc.resolve_token_path()
    tok = lc.validate_token(
        token_path,
        warn_days=LOOP_CONFIG["REFRESH_WARN_DAYS"],
        critical_days=LOOP_CONFIG["REFRESH_CRITICAL_DAYS"],
    )
    if not tok.ok:
        _log(f"PREFLIGHT token_invalid status={tok.status} reason=\"{tok.reason}\"")
        lc.notify(
            LOOP_CONFIG["NOTIFY_TITLE"],
            f"Snapshot skipped: {tok.reason}. Re-run setup_auth.py.",
        )
        _log("RESULT result=skipped_token_invalid notified=True")
        return complete(EXIT_AUTH, "skipped_token_invalid")

    env = {**os.environ, "COLUMNS": LOOP_CONFIG["SUBPROCESS_COLUMNS"]}
    cmd = [sys.executable, LOOP_CONFIG["PORTFOLIO_SCRIPT"]]

    for attempt in range(1, LOOP_CONFIG["MAX_ITERATIONS"] + 1):
        state["attempt"] = attempt
        _log(
            f"START attempt={attempt}/{LOOP_CONFIG['MAX_ITERATIONS']} ts={lc.iso_now()} "
            f"token_valid=True token_status={tok.status}"
        )

        # --- Stage 1: run portfolio.py ---
        res = lc.run_subprocess(
            cmd, timeout_s=LOOP_CONFIG["ITERATION_TIMEOUT_SECONDS"], env=env
        )
        _log(
            f"ATTEMPT exit={res.exit_code} timed_out={res.timed_out} "
            f"duration_s={round(res.duration_s, 2)}"
        )

        if res.exit_code == EXIT_AUTH:
            lc.notify(
                LOOP_CONFIG["NOTIFY_TITLE"],
                "Snapshot failed (token/config error). Re-run setup_auth.py.",
            )
            _log("RESULT result=auth_error notified=True")
            return complete(EXIT_AUTH, "auth_error")

        if res.exit_code != EXIT_OK:
            reason = "timeout" if res.timed_out else f"portfolio.py exit {res.exit_code}"
            lc.notify(LOOP_CONFIG["NOTIFY_TITLE"], f"Snapshot FAILED: {reason}.")
            _log(f"RESULT result=portfolio_failed reason=\"{reason}\" notified=True")
            return complete(1, "portfolio_failed")

        # --- Stage 2: capture + strip ANSI ---
        stripped = lc.strip_ansi(res.stdout)
        if not stripped.strip():
            lc.notify(LOOP_CONFIG["NOTIFY_TITLE"], "Snapshot FAILED: empty portfolio output.")
            _log("RESULT result=empty_output notified=True")
            return complete(1, "empty_output")

        # --- Stage 3: append a delimited, timestamped snapshot block ---
        ts = lc.iso_now()
        lc.ensure_logs_dir()
        hist_path = lc.LOGS_DIR / LOOP_CONFIG["HISTORY_FILE"]
        footer = f"===== END SNAPSHOT {ts} ====="
        block = f"===== PORTFOLIO SNAPSHOT {ts} =====\n{stripped.rstrip()}\n{footer}\n\n"
        size_before = hist_path.stat().st_size if hist_path.exists() else 0
        try:
            with open(hist_path, "a", encoding="utf-8") as handle:
                handle.write(block)  # single write of the whole block (near-atomic)
                handle.flush()
        except OSError as exc:
            lc.notify(LOOP_CONFIG["NOTIFY_TITLE"], f"Snapshot FAILED: write error ({exc}).")
            _log(f"RESULT result=write_error reason=\"{type(exc).__name__}\" notified=True")
            return complete(1, "write_error")

        # --- Stage 4: verify the write (the evaluator) ---
        size_after = hist_path.stat().st_size if hist_path.exists() else 0
        tail = ""
        try:
            with open(hist_path, "r", encoding="utf-8") as handle:
                handle.seek(max(0, size_after - len(block.encode("utf-8")) - 256))
                tail = handle.read()
        except OSError:
            tail = ""
        verified = hist_path.exists() and size_after > size_before and footer in tail
        bytes_written = size_after - size_before

        if not verified:
            lc.notify(LOOP_CONFIG["NOTIFY_TITLE"], "Snapshot FAILED: write could not be verified.")
            _log(
                f"RESULT result=verify_failed bytes={bytes_written} "
                f"size_before={size_before} size_after={size_after} notified=True"
            )
            return complete(1, "verify_failed")

        # --- Success ---
        summary = summarize(stripped)
        msg = "📈 EOD portfolio snapshot saved"
        if summary:
            msg += f" — {summary}"
        notified = lc.notify(LOOP_CONFIG["NOTIFY_TITLE"], msg)
        _log(
            f"RESULT result=snapshot_saved bytes={bytes_written} "
            f"history=\"{LOOP_CONFIG['HISTORY_FILE']}\" notified={notified}"
        )
        return complete(EXIT_OK, "snapshot_saved")

    return complete(1, "unreachable")


if __name__ == "__main__":
    sys.exit(main())
