#!/usr/bin/env python3
"""Loop 3 technical levels -- the REAL-DATA source for the 3:1 R:R gate (H4).

Pulls LIVE Schwab data (quote + ~200 calendar days of daily candles) and derives
a support-anchored stop and the nearest overhead resistance, so the reward:risk
gate is grounded in actual prices -- never LLM-guessed. Read-only; places nothing.

Setup-validity rules (added after the DVN falling-knife incident, 2026-07-01):
  * The support anchor must be AT LEAST ``MIN_SUPPORT_AGE`` (5) sessions old --
    a low set in the last few sessions is just the current price on the way
    down, not tested support.
  * Any candidate whose fresh lows undercut the prior ``KNIFE_LOOKBACK`` (40)
    session low is a FALLING KNIFE: ``falling_knife=true``, ``valid_setup=false``.
  * If recent lows broke below the aged support anchor, the anchor is invalid
    (``support_held=false``) and the setup is rejected.

Usage:  python loops/technicals.py TICKER [TICKER ...]   (prints JSON to stdout)

Numeric fields are always emitted when data exists (so downstream schemas stay
simple); consumers MUST honor ``valid_setup`` / ``falling_knife`` -- a false
``valid_setup`` means the stop is NOT technically anchored and the candidate
must be rejected regardless of the arithmetic R:R.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

# Add project root for `import config` (loops/ is sys.path[0] when run as a script).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import build_client, load_settings, unwrap  # noqa: E402

STOP_ATR_BUFFER = 0.3      # stop sits this many ATRs below the aged support
MIN_SUPPORT_AGE = 5        # support anchor must be >= this many sessions old
SUPPORT_WINDOW = 15        # aged-anchor scan window (sessions, ending MIN_SUPPORT_AGE ago)
KNIFE_LOOKBACK = 40        # fresh low vs this window = falling knife
RESISTANCE_LOOKBACK = 40   # nearest overhead swing-high window
HIST_DAYS = 200
MIN_RR = 3.0


def levels_for(client, ticker: str) -> dict:
    quote = unwrap(client.get_quote(ticker), context=f"quote {ticker}").get(ticker, {}).get("quote", {})
    last = quote.get("lastPrice")
    ph = unwrap(
        client.get_price_history_every_day(
            ticker,
            start_datetime=dt.datetime.now() - dt.timedelta(days=HIST_DAYS),
            end_datetime=dt.datetime.now(),
        ),
        context=f"history {ticker}",
    )
    candles = ph.get("candles", [])
    if not candles or last is None:
        return {"ticker": ticker, "error": "no price data"}
    if len(candles) < KNIFE_LOOKBACK + MIN_SUPPORT_AGE:
        return {"ticker": ticker, "error": f"insufficient history ({len(candles)} candles)"}

    lows = [k["low"] for k in candles]
    highs = [k["high"] for k in candles]
    trs = [
        max(candles[i]["high"] - candles[i]["low"],
            abs(candles[i]["high"] - candles[i - 1]["close"]),
            abs(candles[i]["low"] - candles[i - 1]["close"]))
        for i in range(1, len(candles))
    ]
    atr = round(sum(trs[-14:]) / 14, 4) if len(trs) >= 14 else None

    # --- Setup validity ---------------------------------------------------
    recent_min = min(lows[-MIN_SUPPORT_AGE:])                      # last 5 sessions
    prior_knife_min = min(lows[-KNIFE_LOOKBACK:-MIN_SUPPORT_AGE])  # sessions 6..40 back
    falling_knife = recent_min < prior_knife_min  # fresh 40-session low set in last 5 sessions

    # Aged support anchor: lowest low in the window ending MIN_SUPPORT_AGE sessions
    # ago (so the anchor is at least 5 sessions old by construction).
    aged_window = lows[-(SUPPORT_WINDOW + MIN_SUPPORT_AGE):-MIN_SUPPORT_AGE]
    support = round(min(aged_window), 2)
    support_held = recent_min >= support  # recent lows have not broken the anchor

    valid_setup = (not falling_knife) and support_held
    rejected_reason = None
    if falling_knife:
        rejected_reason = "falling_knife: fresh 40-session low set within the last 5 sessions"
    elif not support_held:
        rejected_reason = "support_broken: recent lows undercut the aged support anchor"

    # --- Levels (always numeric so downstream schemas stay simple) --------
    stop = round(support - STOP_ATR_BUFFER * (atr or 0), 2)
    risk = round(last - stop, 4)
    resistance = round(max(highs[-RESISTANCE_LOOKBACK:]), 2)
    rr = round((resistance - last) / risk, 3) if risk and risk > 0 else None

    return {
        "ticker": ticker,
        "last": round(last, 4),
        "atr14": atr,
        "support_aged_5plus": support,          # anchor, >=5 sessions old by construction
        "support_held": support_held,
        "falling_knife": falling_knife,
        "valid_setup": valid_setup,
        "rejected_reason": rejected_reason,
        "suggested_stop": stop,
        "risk_per_share": risk,
        "nearest_resistance_40d": resistance,
        "rr_to_resistance": rr,
        "min_t1_for_3to1": round(last + MIN_RR * risk, 2) if risk and risk > 0 else None,
        "three_to_one_achievable": bool(
            valid_setup and rr is not None and rr >= MIN_RR and resistance > last
        ),
    }


def main(argv: list[str]) -> int:
    tickers = [a.upper() for a in argv[1:]]
    if not tickers:
        print(json.dumps({"error": "no tickers given"}))
        return 2
    try:
        client = build_client(load_settings())
    except Exception as exc:  # token/config problem -> structured error, no crash
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 1
    out = {}
    for t in tickers:
        try:
            out[t] = levels_for(client, t)
        except Exception as exc:
            out[t] = {"ticker": t, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
