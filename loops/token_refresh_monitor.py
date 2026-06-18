#!/usr/bin/env python3
"""Loop 4 -- Token Refresh Monitor (Pattern 3: Research/check loop).

Trigger:   launchd, weekdays 08:30 local (see deploy/launchd/).
Action:    Read schwab_token.json, compute the refresh token's age from its
           creation_timestamp, and send a macOS notification if it is close to
           the ~7-day expiry.
Evaluator: Token-age check against the LOOP_CONFIG thresholds.
Stop:      Single check per day (MAX_ITERATIONS = 1).
Output:    Desktop notification only when WARN/CRITICAL/MISSING/CORRUPT;
           every run logged to logs/token_monitor.txt (never logs token values).

Guardrails (all four): MAX_ITERATIONS cap in LOOP_CONFIG; 60s per-iteration
timeout; a start-of-iteration log line; a clean-exit handler that writes a FINAL
line if killed mid-run. Handles a missing/corrupt token gracefully (notify, no
crash). Run via: loops/run.sh loops/token_refresh_monitor.py
"""

from __future__ import annotations

import sys
import time

# When run as `python loops/token_refresh_monitor.py`, the loops/ dir is on
# sys.path[0], so loop_common imports directly.
from loop_common import (  # noqa: E402
    CRITICAL,
    HEALTHY,
    MISSING,
    REFRESH_TOKEN_LIFETIME_DAYS,
    WARN,
    DeadlineExceeded,
    append_log,
    deadline,
    install_clean_exit,
    iso_now,
    notify,
    resolve_token_path,
    validate_token,
)

# ===========================================================================
# LOOP_CONFIG  -- all tunables live here; never hardcoded inline (guardrail G1)
# ===========================================================================
LOOP_CONFIG = {
    "LOOP_NAME": "token_refresh_monitor",
    "MAX_ITERATIONS": 1,                 # single check per day
    "ITERATION_TIMEOUT_SECONDS": 60,     # guardrail G2 (deterministic op)
    "REFRESH_WARN_DAYS": 6.0,            # D6: warn threshold
    "REFRESH_CRITICAL_DAYS": 6.5,       # D6: critical escalation
    "REFRESH_LIFETIME_DAYS": REFRESH_TOKEN_LIFETIME_DAYS,  # ~7 days
    "LOG_FILE": "token_monitor.txt",
    "NOTIFY_TITLE": "Schwab Token Monitor",
}


def _log(message: str) -> None:
    append_log(LOOP_CONFIG["LOG_FILE"], f"LOOP={LOOP_CONFIG['LOOP_NAME']} {message}")


def main() -> int:
    state = {
        "attempt": 0,
        "status": "not_started",
        "age_days": None,
        "notified": False,
        "finalized": False,
    }

    def finalize(reason: str) -> None:
        # Idempotent (guardrail G4): only the FIRST caller writes the FINAL line,
        # and only when the loop did NOT complete normally.
        if state["finalized"]:
            return
        state["finalized"] = True
        _log(
            f"FINAL reason={reason} attempts={state['attempt']} "
            f"status={state['status']} age_days={state['age_days']} "
            f"notified={state['notified']}"
        )

    install_clean_exit(finalize)

    token_path = resolve_token_path()

    # Bounded loop -- runs exactly MAX_ITERATIONS times, so it cannot run forever.
    for attempt in range(1, LOOP_CONFIG["MAX_ITERATIONS"] + 1):
        state["attempt"] = attempt
        started = time.monotonic()
        # Guardrail G3: start-of-iteration log (attempt #, input state, timestamp).
        _log(
            f"START attempt={attempt}/{LOOP_CONFIG['MAX_ITERATIONS']} "
            f"ts={iso_now()} token_path={token_path}"
        )

        try:
            with deadline(LOOP_CONFIG["ITERATION_TIMEOUT_SECONDS"]):
                check = validate_token(
                    token_path,
                    warn_days=LOOP_CONFIG["REFRESH_WARN_DAYS"],
                    critical_days=LOOP_CONFIG["REFRESH_CRITICAL_DAYS"],
                    lifetime_days=LOOP_CONFIG["REFRESH_LIFETIME_DAYS"],
                )
        except DeadlineExceeded as exc:
            state["status"] = "TIMEOUT"
            _log(f"TIMEOUT attempt={attempt} detail={exc}")
            notify(LOOP_CONFIG["NOTIFY_TITLE"], "Token check timed out; investigate.")
            finalize("timeout")
            return 1
        except Exception as exc:  # never crash on an unexpected error
            state["status"] = "ERROR"
            _log(f"ERROR attempt={attempt} detail={type(exc).__name__}: {exc}")
            notify(LOOP_CONFIG["NOTIFY_TITLE"], f"Token check error: {type(exc).__name__}.")
            finalize("error")
            return 1

        state["status"] = check.status
        state["age_days"] = None if check.age_days is None else round(check.age_days, 3)
        remaining = (
            None
            if check.age_days is None
            else round(LOOP_CONFIG["REFRESH_LIFETIME_DAYS"] - check.age_days, 2)
        )

        # Notify only on a problem (HEALTHY is silent, per spec).
        if check.status != HEALTHY:
            if check.status == WARN:
                msg = (
                    f"Refresh token is {check.age_days:.1f} days old. "
                    "Re-run setup_auth.py within 24h to keep the monitor online."
                )
            elif check.status == CRITICAL and check.age_days is not None:
                msg = (
                    f"CRITICAL: refresh token is {check.age_days:.1f} days old "
                    f"(~{remaining:.1f}d left). Re-run setup_auth.py NOW."
                )
            elif check.status == MISSING:
                msg = "Schwab token file missing. Re-run setup_auth.py to re-authenticate."
            else:  # CORRUPT or expired
                msg = f"Schwab token problem: {check.reason}. Re-run setup_auth.py."
            state["notified"] = notify(LOOP_CONFIG["NOTIFY_TITLE"], msg)
            if not state["notified"]:
                _log("WARN notification dispatch failed (no GUI session?)")

        duration = round(time.monotonic() - started, 3)
        _log(
            f"RESULT attempt={attempt} status={check.status} "
            f"age_days={state['age_days']} remaining_days={remaining} "
            f"notified={state['notified']} reason=\"{check.reason}\" duration_s={duration}"
        )

    # Completed normally -> suppress the FINAL line (it is reserved for kills).
    state["finalized"] = True
    return 0


if __name__ == "__main__":
    sys.exit(main())
