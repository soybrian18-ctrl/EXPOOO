#!/usr/bin/env python3
"""Daily Morning Briefing (scheduled loop).

Trigger:   launchd, weekdays 09:00 local (see deploy/launchd/).
Steps (in order):
  1. Run stop_check.py, capture output.
  2. Run portfolio.py, capture output.
  3. Check the Schwab token age.
  4. Write a clean, timestamped summary to logs/daily_briefing.txt (headline
     numbers + flags, followed by the two captured reports).
  5. Send ONE desktop notification with the headlines: net liq, # positions,
     open P/L, and any stop flags (plus a token-age warning if aging).

Read-only (Schwab). Guardrails: MAX_ITERATIONS cap in LOOP_CONFIG (G1); 60s
timeout per captured subprocess (G2); a start-of-run log line (G3); a clean-exit
handler that writes a FINAL line if killed mid-run (G4). Pre-flight token
validation. Run via:  loops/run.sh loops/daily_briefing.py
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

# loops/ is on sys.path[0]; add project root for config/analysis.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import loop_common as lc  # noqa: E402

# ===========================================================================
# LOOP_CONFIG  -- all tunables here; never hardcoded inline (guardrail G1)
# ===========================================================================
LOOP_CONFIG = {
    "LOOP_NAME": "daily_briefing",
    "MAX_ITERATIONS": 1,
    "ITERATION_TIMEOUT_SECONDS": 60,     # per captured subprocess (G2)
    "REFRESH_WARN_DAYS": 6.0,
    "REFRESH_CRITICAL_DAYS": 6.5,
    "REFRESH_LIFETIME_DAYS": lc.REFRESH_TOKEN_LIFETIME_DAYS,
    "STOP_CHECK_SCRIPT": "stop_check.py",
    "PORTFOLIO_SCRIPT": "portfolio.py",
    "LOG_FILE": "daily_briefing.txt",
    "NOTIFY_TITLE": "Schwab Daily Briefing",
    "SUBPROCESS_COLUMNS": "120",
}

_FLAG_RE = re.compile(
    r"^\s*([A-Z][A-Z0-9.\-]{0,9})\s+(?:LONG|SHORT)\b.*?(STOP BREACHED|AT RISK|DAY TIF)"
)
_POS_RE = re.compile(r"^\s*[A-Z][A-Z0-9.\-]{0,9}\s+(?:LONG|SHORT)\b")


def _log(message: str) -> None:
    lc.append_log(LOOP_CONFIG["LOG_FILE"], f"LOOP={LOOP_CONFIG['LOOP_NAME']} {message}")


def parse_flags(stopcheck_txt: str) -> list[str]:
    out, seen = [], set()
    for line in stopcheck_txt.splitlines():
        m = _FLAG_RE.search(line)
        if m:
            item = f"{m.group(1)} {m.group(2)}"
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


def count_positions(stopcheck_txt: str) -> int:
    return sum(1 for line in stopcheck_txt.splitlines() if _POS_RE.match(line))


def parse_net_liq(portfolio_txt: str):
    m = re.search(r"Deployed\s+\$([\d,]+\.\d{2}).*?Cash\s+\$([\d,]+\.\d{2})", portfolio_txt, re.S)
    if m:
        return float(m.group(1).replace(",", "")) + float(m.group(2).replace(",", ""))
    return None


def parse_pl(portfolio_txt: str):
    m = re.search(r"Total Open P/L\s+([+\-]?\$[\d,]+\.\d{2})\s+([+\-]?[\d.]+%)", portfolio_txt)
    return (m.group(1), m.group(2)) if m else (None, None)


def api_headlines():
    """Authoritative headline numbers straight from the Schwab API (read-only).

    Returns (net_liq, position_count, pl_dollars, pl_pct) or None on any failure.
    """
    try:
        import analysis
        from config import build_client, fetch_securities_account, load_settings, resolve_account
        settings = load_settings()
        client = build_client(settings)
        acct = resolve_account(client, settings)
        sa = fetch_securities_account(client, acct.account_hash)
        summ = analysis.account_summary(sa)
        rows = analysis.position_rows(sa.get("positions", []))
        total_pl = sum(r.pl_dollars for r in rows)
        total_cost = sum(abs(r.avg_price * r.quantity) for r in rows)
        pl_pct = (total_pl / total_cost * 100.0) if total_cost else None
        return summ.net_liquidating_value, len(rows), total_pl, pl_pct
    except Exception:
        return None


def main() -> int:
    state = {"attempt": 0, "result": "not_started", "finalized": False}

    def finalize(reason: str) -> None:
        if state["finalized"]:
            return
        state["finalized"] = True
        _log(f"FINAL reason={reason} attempts={state['attempt']} result={state['result']}")

    def complete(code: int, result: str) -> int:
        state["result"] = result
        state["finalized"] = True
        return code

    lc.install_clean_exit(finalize)
    token_path = lc.resolve_token_path()

    for attempt in range(1, LOOP_CONFIG["MAX_ITERATIONS"] + 1):
        state["attempt"] = attempt
        _log(f"START attempt={attempt}/{LOOP_CONFIG['MAX_ITERATIONS']} ts={lc.iso_now()}")

        # --- Step 3 (pre-flight): token age / validity ---
        tok = lc.validate_token(
            token_path,
            warn_days=LOOP_CONFIG["REFRESH_WARN_DAYS"],
            critical_days=LOOP_CONFIG["REFRESH_CRITICAL_DAYS"],
        )
        if not tok.ok:
            _log(f"ABORT token_invalid status={tok.status} reason=\"{tok.reason}\"")
            lc.notify(LOOP_CONFIG["NOTIFY_TITLE"], f"Briefing aborted: {tok.reason}. Re-run setup_auth.py.")
            return complete(2, "token_invalid")
        age_txt = f"{tok.age_days:.1f}d" if tok.age_days is not None else "n/a"
        remaining = (
            LOOP_CONFIG["REFRESH_LIFETIME_DAYS"] - tok.age_days if tok.age_days is not None else None
        )

        env = {**os.environ, "COLUMNS": LOOP_CONFIG["SUBPROCESS_COLUMNS"]}

        # --- Step 1: stop_check.py ---
        sc = lc.run_subprocess(
            [sys.executable, LOOP_CONFIG["STOP_CHECK_SCRIPT"]],
            timeout_s=LOOP_CONFIG["ITERATION_TIMEOUT_SECONDS"], env=env,
        )
        sc_txt = lc.strip_ansi(sc.stdout)
        flags = parse_flags(sc_txt)
        _log(f"stop_check exit={sc.exit_code} timed_out={sc.timed_out} flags={len(flags)}")

        # --- Step 2: portfolio.py ---
        pf = lc.run_subprocess(
            [sys.executable, LOOP_CONFIG["PORTFOLIO_SCRIPT"]],
            timeout_s=LOOP_CONFIG["ITERATION_TIMEOUT_SECONDS"], env=env,
        )
        pf_txt = lc.strip_ansi(pf.stdout)
        _log(f"portfolio exit={pf.exit_code} timed_out={pf.timed_out}")

        # --- Headline numbers: authoritative API, else parse fallback ---
        heads = api_headlines()
        if heads:
            net_liq, pos_count, pl_dollars, pl_pct = heads
            net_liq_s = f"${net_liq:,.2f}" if net_liq is not None else "n/a"
            pl_s = f"{'+' if pl_dollars >= 0 else '-'}${abs(pl_dollars):,.2f}"
            pl_pct_s = f"{pl_pct:+.2f}%" if pl_pct is not None else ""
        else:
            net_liq = parse_net_liq(pf_txt)
            pos_count = count_positions(sc_txt)
            pl_s, pl_pct_s = parse_pl(pf_txt)
            net_liq_s = f"~${net_liq:,.2f}" if net_liq is not None else "n/a"
            pl_s = pl_s or "n/a"
            pl_pct_s = pl_pct_s or ""

        flags_s = ("; ".join(flags)) if flags else "no flags"

        # --- Step 4: write the clean timestamped summary + captured reports ---
        ts = lc.iso_now()
        lc.ensure_logs_dir()
        block = (
            f"===== DAILY BRIEFING {ts} =====\n"
            f"Net Liq: {net_liq_s}  |  Positions: {pos_count}  |  "
            f"Open P/L: {pl_s} {pl_pct_s}\n"
            f"Token: {tok.status} (age {age_txt}"
            + (f", ~{remaining:.1f}d to refresh expiry" if remaining is not None else "")
            + ")\n"
            f"Stop flags: {flags_s}   (stop_check exit {sc.exit_code})\n\n"
            f"--- stop_check.py ---\n{sc_txt.rstrip()}\n\n"
            f"--- portfolio.py ---\n{pf_txt.rstrip()}\n"
            f"===== END BRIEFING {ts} =====\n\n"
        )
        with open(lc.LOGS_DIR / LOOP_CONFIG["LOG_FILE"], "a", encoding="utf-8") as fh:
            fh.write(block)
            fh.flush()

        # --- Step 5: ONE desktop notification with the headlines ---
        note = f"💼 {net_liq_s} · {pos_count} pos · P/L {pl_s} {pl_pct_s}".strip()
        note += f" · {'⚠ ' + flags_s if flags else '✓ no flags'}"
        if tok.status != lc.HEALTHY:
            note += f" · ⚠ token {age_txt}"
        notified = lc.notify(LOOP_CONFIG["NOTIFY_TITLE"], note)

        _log(
            f"RESULT net_liq={net_liq_s} positions={pos_count} pl=\"{pl_s} {pl_pct_s}\" "
            f"token={tok.status}({age_txt}) flags={len(flags)} notified={notified}"
        )
        return complete(0, "briefing_written")

    return complete(1, "unreachable")


if __name__ == "__main__":
    sys.exit(main())
