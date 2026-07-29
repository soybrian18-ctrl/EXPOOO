#!/usr/bin/env python3
"""Gate-regression harness: replay every historical gate call through the
CURRENT technicals + sizing logic, with candle history truncated at the
original as-of date, and compare against the recorded verdicts.

Contract (user-mandated before the 2026-07-23 P1-P8 changes ship):
  * HARD rows -- past calls with known-correct outcomes -- must NOT flip:
      - the two 3R winners' entries (COLL 6/15, TENB 6/18) must still pass the
        technical + sizing gates, and
      - every falling-knife / dead-ticker rejection must still reject.
  * SOFT rows -- judgment rejections (R:R below 3 with an honest stop) -- are
    replayed and ANY behavior change is reported for user review, not hidden.

Technical scope note: this harness replays the DETERMINISTIC gates (setup
validity, R:R, liquidity, sizing). Web-verified gates (FCF, catalyst, sector,
moat/revenue) are not replayable offline and were not what P1 changed.

Usage:  python loops/regression_gates.py     (needs a valid Schwab token)
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from technicals import MIN_AVG_VOLUME, MIN_RR, compute_levels  # noqa: E402

FETCH_DAYS = 420

# Balance args as recorded at each evaluation date (from session logs).
BALANCES = {
    "2026-06-15": {"budget": 13.84, "headroom": 243.04},
    "2026-06-18": {"budget": 13.61, "headroom": 202.01},
    "2026-07-01": {"budget": 14.17, "headroom": 219.94},
    "2026-07-03": {"budget": 14.34, "headroom": 217.46},
    "2026-07-23": {"budget": 14.70, "headroom": 403.95},
}

# (as_of, ticker, recorded verdict, hard-contract, recorded detail)
# APPROVE rows replay at the RECORDED DECISION PRICE (the live quote the call
# was actually made at), not the day's close -- the gate ran intraday, and a
# close-based replay would judge a different decision than the one taken.
ENTRY_OVERRIDES = {("2026-06-15", "COLL"): 34.20, ("2026-06-18", "TENB"): 26.57}

EXPECTATIONS = [
    ("2026-06-15", "COLL", "APPROVE", True,  "3R winner entry: stop 32.80, T1 38.40, 3.0:1"),
    ("2026-06-15", "MGNI", "HELD",    False, "pre-system position, exited +$54 at 16.50"),
    ("2026-06-15", "CXM",  "HELD",    False, "pre-system position, stopped -$9 at 5.00"),
    ("2026-06-18", "TENB", "APPROVE", True,  "3R winner entry: stop 25.20, T1 30.90, 3.16:1"),
    ("2026-06-18", "DVN",  "MISTAKE", False, "pre-fix mechanical 8.19:1; user rejected"),
    ("2026-07-01", "PFE",  "REJECT",  True,  "falling knife (fake 20.4:1)"),
    ("2026-07-01", "HAL",  "REJECT",  True,  "falling knife (stop above entry)"),
    ("2026-07-01", "T",    "REJECT",  True,  "falling knife (support broken)"),
    ("2026-07-01", "DVN",  "REJECT",  True,  "falling knife (fake 20.4:1) -> gate fixes"),
    ("2026-07-01", "AR",   "REJECT",  False, "valid setup, rr 1.93"),
    ("2026-07-01", "LYFT", "REJECT",  False, "valid setup, rr 0.35 + sizing"),
    ("2026-07-03", "KGC",  "REJECT",  True,  "falling knife (arith 4.13 voided)"),
    ("2026-07-03", "CTRA", "REJECT",  True,  "delisted (merged into DVN)"),
    ("2026-07-03", "RRC",  "REJECT",  False, "valid setup, rr 1.84"),
    ("2026-07-03", "S",    "REJECT",  False, "valid setup, rr 0.39 + sizing"),
    ("2026-07-03", "ACAD", "REJECT",  False, "valid setup, rr 0.34 + sizing"),
    ("2026-07-23", "IAG",  "REJECT",  True,  "falling knife"),
    ("2026-07-23", "TEVA", "REJECT",  True,  "falling knife (stop above entry)"),
    ("2026-07-23", "PAAS", "REJECT",  True,  "falling knife"),
    ("2026-07-23", "HRMY", "REJECT",  False, "valid setup, rr 0.88 + sizing"),
    ("2026-07-23", "DBX",  "REJECT",  False, "valid setup, rr 0.93"),
    ("2026-07-23", "AR",   "REJECT",  False, "valid setup, rr 0.82 (watch)"),
    ("2026-07-23", "RRC",  "REJECT",  False, "valid setup, rr 0.40 (watch)"),
]


def fetch_history(client, ticker: str):
    from config import unwrap
    ph = unwrap(
        client.get_price_history_every_day(
            ticker,
            start_datetime=dt.datetime.now() - dt.timedelta(days=FETCH_DAYS),
            end_datetime=dt.datetime.now(),
        ),
        context=f"history {ticker}",
    )
    return ph.get("candles", [])


def truncate(candles, as_of: str):
    cutoff = dt.date.fromisoformat(as_of)
    return [k for k in candles if dt.datetime.fromtimestamp(k["datetime"] / 1000).date() <= cutoff]


def new_verdict(levels: dict, bal: dict) -> tuple[str, str]:
    """Apply the CURRENT deterministic gate chain to computed levels."""
    if "error" in levels:
        return "REJECT", f"error:{levels['error'][:40]}"
    if levels["falling_knife"]:
        return "REJECT", "falling_knife"
    if not levels["valid_setup"]:
        return "REJECT", f"invalid_setup:{(levels.get('rejected_reason') or '')[:34]}"
    rr = levels["rr_to_resistance"]
    if rr is None or rr < MIN_RR:
        return "REJECT", f"rr={rr}"
    vol = levels.get("avg_volume_30d") or 0
    if vol < MIN_AVG_VOLUME:
        return "REJECT", f"liquidity={vol}"
    last, risk = levels["last"], levels["risk_per_share"]
    buyable = min(int(200 // last), int(bal["budget"] // risk), int(bal["headroom"] // last))
    if buyable < 3 or buyable * last < 150:
        return "REJECT", f"sizing(buyable={buyable})"
    return "APPROVE", f"rr={rr} stop={levels['suggested_stop']} shares={buyable}"


def main() -> int:
    from config import build_client, load_settings
    client = build_client(load_settings())

    cache: dict[str, list] = {}
    rows, hard_fail, flips = [], [], []
    for as_of, ticker, recorded, hard, note in EXPECTATIONS:
        if ticker not in cache:
            try:
                cache[ticker] = fetch_history(client, ticker)
            except Exception as exc:
                cache[ticker] = {"fetch_error": f"{type(exc).__name__}"}  # type: ignore[assignment]
        hist = cache[ticker]
        if isinstance(hist, dict):
            levels = {"error": f"fetch failed ({hist['fetch_error']})"}
        else:
            candles = truncate(hist, as_of)
            last = ENTRY_OVERRIDES.get((as_of, ticker)) or (candles[-1]["close"] if candles else None)
            levels = compute_levels(candles, last)
        verdict, detail = new_verdict(levels, BALANCES[as_of])

        if recorded in ("HELD", "MISTAKE"):
            status = "INFO"
        elif recorded == verdict:
            status = "MATCH"
        else:
            status = "FLIP"
            (hard_fail if hard else flips).append((as_of, ticker, recorded, verdict, detail))
        rows.append((as_of, ticker, recorded, verdict, status, detail, note))

    w = (11, 6, 8, 8, 6, 44)
    print(f"{'as-of':{w[0]}}{'tkr':{w[1]}}{'recorded':{w[2]}}{'new':{w[3]}}{'stat':{w[4]}}{'new-gate detail':{w[5]}} recorded detail")
    for r in rows:
        print(f"{r[0]:{w[0]}}{r[1]:{w[1]}}{r[2]:{w[2]}}{r[3]:{w[3]}}{r[4]:{w[4]}}{r[5][:42]:{w[5]}} {r[6]}")
    print()
    hard_total = sum(1 for e in EXPECTATIONS if e[3])
    print(f"HARD CONTRACT: {hard_total - len(hard_fail)}/{hard_total} held"
          + ("" if not hard_fail else f"  BROKEN: {hard_fail}"))
    print(f"SOFT FLIPS (behavior changes for user review): {len(flips)}")
    for f in flips:
        print(f"  FLIP {f[0]} {f[1]}: {f[2]} -> {f[3]} ({f[4]})")
    return 1 if hard_fail else 0


if __name__ == "__main__":
    sys.exit(main())
