#!/usr/bin/env python3
"""Loop 3 technical levels -- the REAL-DATA source for the 3:1 R:R gate (H4).

Pulls LIVE Schwab data (quote + ~200 calendar days of daily candles) and derives
a support-anchored stop and the nearest overhead resistance, so the reward:risk
gate is grounded in actual prices -- never LLM-guessed. Read-only; places nothing.

Usage:  python loops/technicals.py TICKER [TICKER ...]   (prints JSON to stdout)

Per ticker it emits: last, atr14, support_10d (recent swing low), suggested_stop
(support - 0.3*ATR), risk_per_share, nearest_resistance_40d (recent swing high),
rr_to_resistance, min_t1_for_3to1, and three_to_one_achievable. On any failure it
emits {"error": ...} for that ticker so the caller never crashes (G4 / point 4).
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

# Add project root for `import config` (loops/ is sys.path[0] when run as a script).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import build_client, load_settings, unwrap  # noqa: E402

STOP_ATR_BUFFER = 0.3      # stop sits this many ATRs below recent support
SUPPORT_LOOKBACK = 10      # sessions for the recent swing-low (support)
RESISTANCE_LOOKBACK = 40   # sessions for the nearest overhead swing-high
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

    lows = [k["low"] for k in candles]
    highs = [k["high"] for k in candles]
    trs = [
        max(candles[i]["high"] - candles[i]["low"],
            abs(candles[i]["high"] - candles[i - 1]["close"]),
            abs(candles[i]["low"] - candles[i - 1]["close"]))
        for i in range(1, len(candles))
    ]
    atr = round(sum(trs[-14:]) / 14, 4) if len(trs) >= 14 else None
    support = round(min(lows[-SUPPORT_LOOKBACK:]), 2)
    resistance = round(max(highs[-RESISTANCE_LOOKBACK:]), 2)
    stop = round(support - STOP_ATR_BUFFER * (atr or 0), 2)
    risk = round(last - stop, 4)
    rr = round((resistance - last) / risk, 3) if risk and risk > 0 else None
    return {
        "ticker": ticker,
        "last": round(last, 4),
        "atr14": atr,
        "support_10d": support,
        "suggested_stop": stop,
        "risk_per_share": risk,
        "nearest_resistance_40d": resistance,
        "rr_to_resistance": rr,
        "min_t1_for_3to1": round(last + MIN_RR * risk, 2) if risk and risk > 0 else None,
        "three_to_one_achievable": bool(rr is not None and rr >= MIN_RR and resistance > last),
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
