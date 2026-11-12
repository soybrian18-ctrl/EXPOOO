"""Helpers for the flip-measurement scenario tests: synthetic candles, night folders and spec-text oracles.

Adopted from the 2026-11-12 verification of the flip tools (its checks/vhelpers.py), and independent of the
builder's own test helpers: own history builders, and oracles written from spec 3.1-3.4 text in exact fractions.
Used by tests/test_phase2_flips_scenarios.py (S01-S29) and tests/test_phase2_flips.py (the order-level oracle).
Not a test module itself (no test_ prefix).

Everything here is synthetic. Session dates used by the scenarios are post-go-live (2026-11-23 on) or in 2024.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from fractions import Fraction
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(ROOT, "loops") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "loops"))

import technicals  # noqa: E402
from phase2 import compare_bars as CB  # noqa: E402
from phase2 import fills as F  # noqa: E402
from phase2 import sample_bars as SB  # noqa: E402
from phase2.params import PARAMS  # noqa: E402

NY, CH = SB.NY, SB.CH
D = dt.date
SEAL = (D(2025, 1, 2), D(2026, 10, 30))
# NYSE holidays the synthetic calendar skips (2024 and 2026 ones near the scenarios, plus the carried ones)
HOLIDAYS = {D(2024, 1, 1), D(2024, 1, 15), D(2024, 2, 19), D(2024, 3, 29), D(2024, 5, 27), D(2024, 6, 19),
            D(2024, 7, 4), D(2024, 9, 2), D(2024, 11, 28), D(2024, 12, 25), D(2023, 12, 25), D(2023, 11, 23),
            D(2026, 5, 25), D(2026, 6, 19), D(2026, 7, 3), D(2026, 9, 7), D(2026, 11, 26), D(2026, 12, 25),
            D(2027, 1, 1), D(2027, 1, 18), D(2027, 2, 15), D(2027, 3, 26)}


def sessions_before(t: dt.date, n: int) -> list[dt.date]:
    out, d = [], t
    while len(out) < n:
        d -= dt.timedelta(days=1)
        if d.weekday() < 5 and d not in HOLIDAYS:
            out.append(d)
    return out[::-1]


def ms(d: dt.date, kind: str) -> int:
    return int(dt.datetime.combine(d, dt.time(0), CH if kind == "final" else NY).timestamp() * 1000)


def cdl(d: dt.date, kind: str, o, h, l, c, v) -> dict:
    return dict(d=d.isoformat(), kind=kind, ms=ms(d, kind), o=o, h=h, l=l, c=c, v=v)


def at(y, mo, d, h, mi, s=0) -> dt.datetime:
    return dt.datetime(y, mo, d, h, mi, s, tzinfo=NY)


def flat(t: dt.date, n: int = 130, c: float = 20.0, r: float = 0.5, v: int = 1_000_000) -> list[dict]:
    return [cdl(d, "final", c, round(c + r, 6), round(c - r, 6), c, v) for d in sessions_before(t, n)]


def bar(o, h, l, c, v) -> dict:
    return dict(o=o, h=h, l=l, c=c, v=v)


class NightW:
    """One synthetic session folder in sample_bars' layout."""

    def __init__(self, root: Path, session: dt.date, names: list[str], reference=("SPY",)):
        self.root, self.session = Path(root), session
        self.day = self.root / session.isoformat()
        self.day.mkdir(parents=True, exist_ok=True)
        with open(self.day / "candidates.json", "w") as fh:
            json.dump(dict(session=session.isoformat(), symbols=list(names), reference=list(reference)), fh)

    def _app(self, name: str, row: dict) -> None:
        with open(self.day / name, "a") as fh:
            fh.write(json.dumps(row) + "\n")

    def add(self, sym, hist, ev, qclose, fin, ev_at, fi_at, *, ev_kind="provisional", fin_kind="final",
            q_open=None, eve_prior=None, final_rows=None):
        t = self.session
        self._app(f"quotes_{SB.stamp(ev_at)}.jsonl",
                  dict(symbol=sym, pulled=SB.iso(ev_at), regular_last=qclose, open=ev["o"] if q_open is None else q_open))
        prior = hist[-4:] if eve_prior is None else eve_prior
        self._app(f"evening_{SB.stamp(ev_at)}.jsonl",
                  dict(symbol=sym, pulled=SB.iso(ev_at), candles=prior + [cdl(t, ev_kind, **ev)]))
        if final_rows is not None:                       # explicit rows: [(pulled, candles or None, extra), ...]
            for pulled, candles, extra in final_rows:
                row = dict(symbol=sym, pulled=SB.iso(pulled), **extra)
                if candles is not None:
                    row["candles"] = candles
                self._app(f"final_{SB.stamp(pulled)}.jsonl", row)
            return
        if fin is None:
            return
        cs = hist + [cdl(t, fin_kind, **fin)]
        if fin_kind == "final":
            cs.append(cdl(t, "provisional", **ev))      # Schwab lists the provisional candle beside the final one
        self._app(f"final_{SB.stamp(fi_at)}.jsonl", dict(symbol=sym, pulled=SB.iso(fi_at), candles=cs))


# --------------------------------------------------------------------------------------------------------
# Spec-text oracles (exact decimal arithmetic where the spec states a threshold)
# --------------------------------------------------------------------------------------------------------

def q(x) -> Fraction:
    """A price or volume as an exact fraction at the millionth (fills.py's resolution)."""
    return Fraction(round(float(x) * 1_000_000), 1_000_000)


def atr_oracle(candles: list[dict]) -> float:
    """ATR14 the way compute_levels computes it (simple mean of the last 14 true ranges, 4 dp)."""
    trs = []
    for p, c in zip(candles[:-1], candles[1:]):
        trs.append(max(c["h"] - c["l"], abs(c["h"] - p["c"]), abs(c["l"] - p["c"])))
    return round(sum(trs[-14:]) / 14, 4)


def ceil_cent(x: Fraction) -> Decimal:
    return (Decimal(x.numerator) / Decimal(x.denominator)).quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def floor_cent(x: Fraction) -> Decimal:
    return (Decimal(x.numerator) / Decimal(x.denominator)).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)


def frac(d: Decimal) -> Fraction:
    return Fraction(d)


def spec_levels(T: Decimal, atr: float, k: float, s0) -> dict:
    """Spec 3.4 Order + section 4 sizing, in exact fractions."""
    a, Tf = q(atr), frac(T)
    C = floor_cent(Tf + Fraction(1, 4) * a)
    s_atr = Tf - Fraction(k).limit_denominator(100) * a
    S = floor_cent(min(q(s0), s_atr) if s0 is not None else s_atr)
    P = ceil_cent(Tf + 3 * (Tf - frac(S)))
    if not (0 < S < T <= C < P):
        return None
    n = min(Fraction(15) / (frac(C) - frac(S)), Fraction(26250, 100) / frac(C))
    N = n.numerator // n.denominator
    return dict(T=T, C=C, S=S, P=P, N=N, sizable=N >= 3)


def spec_eval(hist: list[dict], b: dict, prior60: set) -> dict:
    """eligible / above / M2 tests / M1 tests straight from spec 3.1-3.3 (M1 through compute_levels, unchanged)."""
    n = len(hist)
    out = {}
    adv30 = sum(Fraction(int(c["v"])) for c in hist[-30:]) / 30 if n >= 30 else None
    present = sum(1 for c in hist if c["d"] in prior60)
    out["eligible"] = bool(q(5) <= q(b["c"]) <= q(100) and adv30 is not None and adv30 >= 500_000
                           and present >= 58 and n >= 60)
    if n >= 49:
        closes = [q(c["c"]) for c in hist[-49:]] + [q(b["c"])]
        out["above"] = q(b["c"]) > sum(closes) / 50
    T = ceil_cent(q(b["h"]) + Fraction(1, 100))
    out["T"] = T
    bars = [dict(open=c["o"], high=c["h"], low=c["l"], close=c["c"], volume=c["v"]) for c in hist[-119:]]
    bars.append(dict(open=b["o"], high=b["h"], low=b["l"], close=b["c"], volume=b["v"]))
    L = technicals.compute_levels(bars, last=float(T))
    if "error" in L:
        return out
    out["L"] = L
    atr_t = L["atr14"]
    atr_p = atr_oracle(hist[-15:])
    prev_c = q(hist[-1]["c"])
    need = max(Fraction(3, 100) * prev_c, q(atr_p))
    mid = q(b["l"]) + Fraction(1, 2) * (q(b["h"]) - q(b["l"]))
    out["m2"] = dict(gap=q(b["o"]) - prev_c >= need,
                     volume=adv30 is not None and q(b["v"]) >= 3 * adv30,
                     held=q(b["l"]) > prev_c and q(b["c"]) >= mid,
                     knife_free=not L["falling_knife"], eligible=out["eligible"])
    anchor = L["support_anchor"]
    touch_line = q(anchor) + Fraction(1, 4) * q(atr_t) if anchor is not None else None
    out["m1"] = dict(valid_setup=bool(L["valid_setup"]), atr_floor_ok=bool(L["atr_floor_ok"]),
                     rr=L["rr_to_resistance"] is not None and L["rr_to_resistance"] >= 3.0,
                     touch=anchor is not None and q(b["l"]) <= touch_line,
                     eligible=out["eligible"])
    # exact ties, where binary floats may land either side (reported separately, scenario S07)
    out["ties"] = {"m2.gap": q(b["o"]) - prev_c == need, "m2.held": q(b["c"]) == mid or q(b["l"]) == prev_c,
                   "m1.touch": touch_line is not None and q(b["l"]) == touch_line,
                   "above": n >= 49 and q(b["c"]) == sum(closes) / 50,
                   "m2.volume": adv30 is not None and q(b["v"]) == 3 * adv30}
    out["atr_t"], out["atr_p"] = atr_t, atr_p
    return out


# --------------------------------------------------------------------------------------------------------
# Spec 3.4 fill oracle for ONE session (the first window session, or a held session)
# --------------------------------------------------------------------------------------------------------

def spec_entry_session(T, C, S, P, b):
    """Spec 3.4 'Entry session d' + 'Exits on the entry session'. Prices as Fractions. Returns an outcome tuple."""
    o, h, l, c = b
    tt = Fraction(1, 100)
    if T <= o <= C:
        kind, raw = "open", o
    elif o < T <= h:
        kind, raw = "trigger", T
    elif o > C:
        if l <= C - tt:
            kind, raw = "ceiling", C
        else:
            return ("CANCELED", None, None, None, None, "triggered_unfilled")
    else:
        return ("PENDING", None, None, None, None, None)
    if l <= S:
        return ("CLOSED", kind, raw, "stop", S, None)
    reached = (c >= P + tt) if kind == "ceiling" else (h >= P + tt)
    if reached:
        return ("CLOSED", kind, raw, "target", P, None)
    return ("OPEN", kind, raw, None, None, None)


def spec_held_session(S, P, b):
    """Spec 3.4 'Later sessions, in order' (the time exit is far away here)."""
    o, h, l, c = b
    tt = Fraction(1, 100)
    if o <= S:
        return ("gap_stop", o)
    if o >= P + tt:
        return ("target", P)
    if l <= S:
        return ("stop", S)
    if h >= P + tt:
        return ("target", P)
    return (None, None)
