#!/usr/bin/env python3
"""Loop 3 technical levels -- the REAL-DATA source for the 3:1 R:R gate (H4).

Pulls LIVE Schwab data (quote + daily candles) and derives a support-anchored
stop and the nearest overhead resistance, so the reward:risk gate is grounded in
actual prices -- never LLM-guessed. Read-only; places nothing.

Gate lineage (each rule traces to a live incident):
  * 2026-07-01 DVN: support anchor must be >= MIN_SUPPORT_AGE (5) sessions old;
    a fresh 40-session low within the last 5 sessions is a FALLING KNIFE.
  * 2026-07-23 P1: the anchor is the NEAREST aged support below price -- a
    tested shelf (>=2 lows clustered within SHELF_TOLERANCE_ATR) or a clear
    wing-2 pivot low -- with the stop placed under the SHELF FLOOR (deepest
    tested low of the cluster), not under the window minimum. This mirrors the
    manually-derived stops of the two 3R winners (TENB, COLL) and stops the
    window-min formula from inflating risk-per-share on healthy names.
  * 2026-07-23 P3: avg_volume_30d emitted so the orchestrator can enforce the
    300k-share liquidity floor deterministically.
  * 2026-08-12 P2 RETIRED: the breakout regime was retired after a full-
    population replay (loops/breakout_replay.py) showed a 20% hit rate against
    ~20% breakeven, with all positive R from 2 of 10 closed trades, and none of
    the motivating escapes (AR/IAG/DBX/RRC) being base-and-confirm breakouts.
    The breakout_* fields below are retained SOLELY for the replay harness and
    future entry-pattern research -- they MUST NOT feed any live approval path.
  * 2026-08-21 C4: ATR stop-distance floor -- risk_per_share must be >=
    ATR_FLOOR_MULT (0.6) x ATR14 or the setup is rejected outright
    (stop_below_atr_floor). A stop inside ~half an ATR sits inside ordinary
    session noise and produces inflated R:R arithmetic: KEY 2026-08-19 passed
    the shelf detector at 0.498 x ATR (rr printed 8.40) and the shelf broke
    within 2 sessions; the pre-fix DVN/PFE fake ratios (20.4:1, 8.19:1) sat at
    0.06-0.36 x ATR. Calibration: every historical approval's stop sat at
    0.70-1.35 x ATR (TENB, a 3R winner, at 0.877 -- so the floor cannot be
    1.0); the bad cluster tops out at 0.498 -> 0.6 splits them with ~0.10
    margin each side. PURE REJECT by design: the considered alternative --
    deepening the anchor to the next aged shelf until the floor is met -- was
    REJECTED because it would have approved KEY at a ~21.6 stop (1.5 x ATR,
    same 8 shares via the $200 cap) on a name that fell to 21.82 two sessions
    later; widening a stop cannot fix a knife-adjacent setup, it just pays
    more to lose. Revisit only if the reject rate proves costly.

Usage:  python loops/technicals.py TICKER [TICKER ...]   (prints JSON to stdout)

``compute_levels(candles, last)`` is pure (no I/O) so unit tests and the
regression harness can replay historical dates by truncating the candle series.
Consumers MUST honor ``valid_setup`` / ``falling_knife`` -- a false
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

STOP_ATR_BUFFER = 0.2        # stop sits this many ATRs below the anchor's shelf floor
ATR_FLOOR_MULT = 0.6         # C4: risk_per_share must be >= this many ATRs (else fake-R:R reject)
SHELF_TOLERANCE_ATR = 0.25   # lows within this band of an anchor count as shelf touches
PIVOT_WING = 2               # sessions each side for a swing-low pivot
MIN_SUPPORT_AGE = 5          # anchor must be >= this many sessions old
SUPPORT_SCAN = 40            # how far back anchors are considered
KNIFE_LOOKBACK = 40          # fresh low vs this window = falling knife
RESISTANCE_LOOKBACK = 40     # nearest overhead swing-high window
BASE_SESSIONS = 10           # P2 shadow: consolidation length checked under a breakout
BASE_MAX_RANGE_ATR = 3.0     # P2 shadow: base height ceiling, in ATRs
BREAKOUT_CONFIRM_ATR = 0.25  # P2 shadow: close must clear the aged high by this margin
HIST_DAYS = 300
MIN_RR = 3.0
MIN_AVG_VOLUME = 300_000


def _aged_support_anchor(lows: list[float], atr: float) -> dict:
    """Nearest tested support below the latest price (P1).

    A qualifying anchor low must be >= MIN_SUPPORT_AGE sessions old, unbroken by
    any later low, within SUPPORT_SCAN sessions, and either (a) a SHELF -- >=2
    session-lows clustered within SHELF_TOLERANCE_ATR*ATR of it -- or (b) a
    wing-2 PIVOT (local minimum of its +/-2-session neighborhood). Among
    qualifiers the HIGHEST low wins (nearest support), and the stop anchors on
    that shelf's FLOOR (deepest touch of the cluster) so a retest of the tested
    low cannot tag the stop.
    """
    n = len(lows)
    tol = SHELF_TOLERANCE_ATR * (atr or 0)
    scan_start = max(0, n - SUPPORT_SCAN)

    def _touches(level: float) -> int:
        """Tests of ``level`` since its last decisive break (low < level - tol).

        Counting across the whole window would let a new low inherit touches
        from a long-BROKEN zone it happens to sit in; support memory only
        counts from the most recent reclaim onward.
        """
        start = scan_start
        for j in range(scan_start, n):
            if lows[j] < level - tol:
                start = j + 1
        return sum(1 for j in range(start, n) if level <= lows[j] <= level + tol)

    candidates: list[int] = []
    for i in range(scan_start, n - MIN_SUPPORT_AGE):
        level = lows[i]
        # Broken only by a DECISIVE later low (more than one tolerance under the
        # level). A sub-tolerance undercut is a stop-hunt wiggle / retest, not a
        # break -- e.g. TENB 2026-06-18 printed 25.50 against its 25.54 shelf
        # and then rallied 16% without ever looking back.
        if min(lows[i + 1:]) < level - tol:
            continue
        lo = max(0, i - PIVOT_WING)
        is_pivot = level == min(lows[lo:i + PIVOT_WING + 1])
        if _touches(level) >= 2 or is_pivot:
            candidates.append(i)
    if not candidates:
        return {"anchor": None, "floor": None, "kind": None}
    best = max(candidates, key=lambda i: lows[i])
    level = lows[best]
    # Floor: deepest tested low WITHIN one tolerance of the anchor (the shelf's
    # own cluster -- including any sub-tolerance undercut wiggles).
    cluster = [l for l in lows[scan_start:] if level - tol <= l <= level + tol]
    floor = min(cluster) if cluster else level
    return {"anchor": round(level, 2), "floor": round(floor, 2),
            "kind": "shelf" if _touches(level) >= 2 else "pivot"}


def compute_levels(candles: list[dict], last: float) -> dict:
    """Pure level computation over daily candles. No network, fully replayable."""
    if not candles or last is None:
        return {"error": "no price data"}
    if len(candles) < KNIFE_LOOKBACK + MIN_SUPPORT_AGE:
        return {"error": f"insufficient history ({len(candles)} candles)"}

    lows = [k["low"] for k in candles]
    highs = [k["high"] for k in candles]
    vols = [k.get("volume", 0) for k in candles]
    trs = [
        max(candles[i]["high"] - candles[i]["low"],
            abs(candles[i]["high"] - candles[i - 1]["close"]),
            abs(candles[i]["low"] - candles[i - 1]["close"]))
        for i in range(1, len(candles))
    ]
    atr = round(sum(trs[-14:]) / 14, 4) if len(trs) >= 14 else None
    avg_volume_30d = int(sum(vols[-30:]) / min(30, len(vols))) if vols else None

    # --- Falling-knife gate (unchanged from the 2026-07-01 fix) --------------
    recent_min = min(lows[-MIN_SUPPORT_AGE:])
    prior_knife_min = min(lows[-KNIFE_LOOKBACK:-MIN_SUPPORT_AGE])
    falling_knife = recent_min < prior_knife_min

    # --- P1 anchor -----------------------------------------------------------
    sup = _aged_support_anchor(lows, atr or 0)
    anchor, floor = sup["anchor"], sup["floor"]
    has_anchor = anchor is not None and anchor < last
    support_held = bool(has_anchor and recent_min >= floor)

    valid_setup = (not falling_knife) and has_anchor and support_held
    rejected_reason = None
    if falling_knife:
        rejected_reason = "falling_knife: fresh 40-session low set within the last 5 sessions"
    elif not has_anchor:
        rejected_reason = "no_aged_support_anchor: no tested shelf/pivot >=5 sessions old below price"
    elif not support_held:
        rejected_reason = "support_broken: recent lows undercut the anchor shelf floor"

    # --- Pullback-regime levels ---------------------------------------------
    stop = round((floor if floor is not None else recent_min) - STOP_ATR_BUFFER * (atr or 0), 2)
    risk = round(last - stop, 4)
    resistance = round(max(highs[-RESISTANCE_LOOKBACK:]), 2)
    rr = round((resistance - last) / risk, 3) if risk and risk > 0 else None
    # C4: floor judged on unrounded values; consumers reject when atr_floor_ok
    # is False (risk <= 0 also lands False and is caught by rr/setup anyway).
    stop_atr_multiple = round(risk / atr, 3) if atr else None
    atr_floor_ok = bool(atr and risk is not None and risk >= ATR_FLOOR_MULT * atr)

    # --- P2 breakout regime (SHADOW ONLY -- never feeds the live approval) ---
    ref_high = round(max(highs[-KNIFE_LOOKBACK:-MIN_SUPPORT_AGE]), 2)
    base_highs = highs[-(BASE_SESSIONS + MIN_SUPPORT_AGE):-MIN_SUPPORT_AGE]
    base_lows = lows[-(BASE_SESSIONS + MIN_SUPPORT_AGE):-MIN_SUPPORT_AGE]
    base_ok = bool(base_highs) and (max(base_highs) - min(base_lows)) <= BASE_MAX_RANGE_ATR * (atr or 0)
    breakout_mode = bool(atr) and last > ref_high + BREAKOUT_CONFIRM_ATR * atr
    breakout_stop = round(ref_high - STOP_ATR_BUFFER * (atr or 0), 2)
    breakout_risk = round(last - breakout_stop, 4)
    breakout_t1 = round(ref_high + (ref_high - min(base_lows)), 2) if base_lows else None
    breakout_rr = (
        round((breakout_t1 - last) / breakout_risk, 3)
        if breakout_t1 is not None and breakout_risk and breakout_risk > 0 else None
    )
    breakout_valid = bool(breakout_mode and base_ok and breakout_risk and breakout_risk > 0)

    return {
        "last": round(last, 4),
        "atr14": atr,
        "avg_volume_30d": avg_volume_30d,
        "support_anchor": anchor,
        "support_floor": floor,
        "support_kind": sup["kind"],
        "support_held": support_held,
        "falling_knife": falling_knife,
        "valid_setup": valid_setup,
        "rejected_reason": rejected_reason,
        "suggested_stop": stop,
        "risk_per_share": risk,
        "stop_atr_multiple": stop_atr_multiple,
        "atr_floor_ok": atr_floor_ok,
        "nearest_resistance_40d": resistance,
        "rr_to_resistance": rr,
        "min_t1_for_3to1": round(last + MIN_RR * risk, 2) if risk and risk > 0 else None,
        "three_to_one_achievable": bool(
            valid_setup and rr is not None and rr >= MIN_RR and resistance > last
        ),
        # ---- P2 SHADOW fields (report/log only; excluded from live gates) ----
        "breakout_mode": breakout_mode,
        "breakout_base_ok": base_ok,
        "breakout_ref_high": ref_high,
        "breakout_stop": breakout_stop,
        "breakout_t1": breakout_t1,
        "breakout_rr": breakout_rr,
        "breakout_valid": breakout_valid,
    }


def levels_for(client, ticker: str) -> dict:
    from config import unwrap  # deferred so compute_levels stays import-light
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
    out = compute_levels(ph.get("candles", []), last)
    out["ticker"] = ticker
    return out


def main(argv: list[str]) -> int:
    tickers = [a.upper() for a in argv[1:]]
    if not tickers:
        print(json.dumps({"error": "no tickers given"}))
        return 2
    try:
        from config import build_client, load_settings
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
