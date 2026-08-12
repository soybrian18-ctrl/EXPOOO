#!/usr/bin/env python3
"""C2: breakout (P2 shadow) evidence replay -- what would continuous shadow
coverage have caught, and how would those trades have resolved?

Context: the live SHADOW-BREAKOUT log is EMPTY because the pipeline only
evaluates on run days, and every observed escape (AR, IAG, DBX, RRC) confirmed
its breakout between runs. This harness reconstructs continuous coverage by
replaying the pure ``compute_levels`` day-by-day over real candle history for
the FULL population of screened-but-never-traded names (user-mandated: not just
the four memorable escapes -- that sample is biased toward breakouts that worked).

For each ticker: find the FIRST session (within the replay window) where the
full shadow gate would have fired --
    breakout_valid AND breakout_rr >= 3.0 AND avg_volume_30d >= 300k
    AND 5 <= close <= 50 AND sizing feasible (>=3 shares, >=$150 notional,
    within a representative $14.70 risk budget / $200 cap)
-- then walk forward: did breakout_t1 or breakout_stop get hit first (same-day
both-touch resolves PESSIMISTICALLY as stop-first), or is the trade still open?

Read-only; places nothing; changes no gate behavior. Output feeds the user's
promote-or-keep-shadow decision on P2.

Usage:  python loops/breakout_replay.py
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from technicals import compute_levels  # noqa: E402

# Full screened-but-never-traded population (traded names FRO/AEO/CCL and
# delisted CTRA excluded; S included -- approved but never filled, then escaped).
POPULATION = [
    # the four noticed escapes
    "AR", "IAG", "DBX", "RRC",
    # every other reject / un-followed candidate with data, all runs Jun-Aug
    "PFE", "HAL", "T", "DVN", "LYFT", "SOFI", "KGC", "S", "ACAD", "CMCSA",
    "TEVA", "PAAS", "HRMY", "VTRS", "HPE", "AMRX", "PR", "EGO", "TOST",
    "CENX", "DKNG", "SUPN", "PGNY", "SM", "GAP", "BILL", "PATH",
    "KEY", "SBLK", "GEN", "PTON", "GPS", "CPRT", "GTLB", "IOT", "KSS", "ASO",
    "BOX", "LEVI",
]

REPLAY_START = dt.date(2026, 6, 15)   # experiment era start
MIN_RR = 3.0
MIN_VOL = 300_000
PRICE_MIN, PRICE_MAX = 5.0, 50.0
RISK_BUDGET = 14.70                   # representative 2% budget across the era
MAX_NOTIONAL = 200.0
MIN_NOTIONAL = 150.0
MIN_SHARES = 3
FETCH_DAYS = 420


def sizing_ok(entry: float, risk: float) -> bool:
    if risk <= 0 or entry <= 0:
        return False
    buyable = min(int(MAX_NOTIONAL // entry), int(RISK_BUDGET // risk))
    return buyable >= MIN_SHARES and buyable * entry >= MIN_NOTIONAL


def replay_ticker(candles: list[dict]) -> dict | None:
    """First shadow fire in the window + walk-forward outcome."""
    dates = [dt.datetime.fromtimestamp(k["datetime"] / 1000).date() for k in candles]
    for i in range(50, len(candles)):           # need history depth for the gates
        if dates[i] < REPLAY_START:
            continue
        levels = compute_levels(candles[: i + 1], candles[i]["close"])
        if "error" in levels:
            continue
        rr = levels.get("breakout_rr")
        if not (levels.get("breakout_valid") and rr is not None and rr >= MIN_RR):
            continue
        close = candles[i]["close"]
        if not (PRICE_MIN <= close <= PRICE_MAX):
            continue
        if (levels.get("avg_volume_30d") or 0) < MIN_VOL:
            continue
        stop, t1 = levels["breakout_stop"], levels["breakout_t1"]
        risk = close - stop
        if not sizing_ok(close, risk):
            continue
        # ---- fire: walk forward ----
        outcome, exit_date, days = "OPEN", None, 0
        for j in range(i + 1, len(candles)):
            days = j - i
            lo, hi = candles[j]["low"], candles[j]["high"]
            if lo <= stop:                       # pessimistic: stop checked first
                outcome, exit_date = "STOPPED", dates[j]
                break
            if hi >= t1:
                outcome, exit_date = "TARGET", dates[j]
                break
        r_mult = {"TARGET": round((t1 - close) / risk, 2),
                  "STOPPED": -1.0,
                  "OPEN": round((candles[-1]["close"] - close) / risk, 2)}[outcome]
        return {"fired": dates[i], "entry": round(close, 2), "stop": stop, "t1": t1,
                "rr": rr, "outcome": outcome, "exit": exit_date, "days": days,
                "r": r_mult}
    return None


def main() -> int:
    from config import build_client, load_settings, unwrap
    client = build_client(load_settings())

    fired, no_fire, errors = [], [], []
    for tkr in POPULATION:
        try:
            ph = unwrap(
                client.get_price_history_every_day(
                    tkr,
                    start_datetime=dt.datetime.now() - dt.timedelta(days=FETCH_DAYS),
                    end_datetime=dt.datetime.now(),
                ),
                context=f"history {tkr}",
            )
            candles = ph.get("candles", [])
            if len(candles) < 60:
                errors.append((tkr, "insufficient history"))
                continue
        except Exception as exc:
            errors.append((tkr, f"{type(exc).__name__}"))
            continue
        res = replay_ticker(candles)
        if res:
            fired.append((tkr, res))
        else:
            no_fire.append(tkr)

    print(f"C2 BREAKOUT SHADOW REPLAY -- window {REPLAY_START} .. today; "
          f"population {len(POPULATION)} names; gate: breakout_valid & rr>={MIN_RR:g} "
          f"& vol>={MIN_VOL:,} & ${PRICE_MIN:g}-{PRICE_MAX:g} & sizing-ok; "
          f"same-day both-touch = STOP (pessimistic)\n")
    print(f"{'tkr':6}{'fired':12}{'entry':>8}{'stop':>8}{'T1':>8}{'rr':>6}  {'outcome':8}{'exit':12}{'days':>5}{'R':>7}")
    for tkr, r in sorted(fired, key=lambda x: x[1]["fired"]):
        print(f"{tkr:6}{str(r['fired']):12}{r['entry']:8.2f}{r['stop']:8.2f}{r['t1']:8.2f}"
              f"{r['rr']:6.2f}  {r['outcome']:8}{str(r['exit'] or '-'):12}{r['days']:5d}{r['r']:7.2f}")
    print(f"\nNO FIRE ({len(no_fire)}): {', '.join(no_fire)}")
    if errors:
        print(f"DATA ERRORS ({len(errors)}): {', '.join(f'{t}({e})' for t, e in errors)}")

    closed = [r for _, r in fired if r["outcome"] != "OPEN"]
    targets = [r for r in closed if r["outcome"] == "TARGET"]
    total_r = sum(r["r"] for _, r in fired)
    print(f"\nAGGREGATE: {len(fired)} fires / {len(POPULATION)} names "
          f"({len(no_fire)} never fired). Closed: {len(closed)} "
          f"(targets {len(targets)}, stops {len(closed) - len(targets)}); "
          f"open: {len(fired) - len(closed)}. "
          f"Hit rate (closed): {round(100 * len(targets) / len(closed)) if closed else 'n/a'}%. "
          f"Sum R (incl. open marked-to-market): {round(total_r, 2)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
