#!/usr/bin/env python3
"""Phase 2 flip measurement, part 2 of 2: across every sampled night, how often would the EVENING scan's
provisional bars flip a signal, a ticket or an order state that the FINAL bars decide? READ-ONLY, no network.

Owner's instruction (2026-11-11): "Before relying on it, measure how often provisional bars flip a signal
across the nights you sample." Inputs are the <root>/<session>/ folders written by sample_bars.py, the
legacy 2026-11-11 files included: every row is classified from its own candles and stamps, never from a
stored label, and rows are ordered by their own pull times, never by file names. A candle's date is its
stamp's New York date (as sample_bars.candle_from_raw derives it), not its stored 'd'; a night with any
candle whose stored date disagrees with its stamp gets the bar level only (safety S6). A folder under the
root that is not a session date inside sample_bars' carried calendar after 2026-10-30 is ignored, and the
report lists it as ignored (safety S9).

The evening scan's bar is the provisional candle (stamped midnight New York) with its close replaced by the
quote's regular-session last price, the official close. The final bar is the candle stamped midnight Chicago.

Classes, per name and night, each reported on its own and never folded into a flip count:
  evening  PROVISIONAL (compared) | ALREADY_FINAL (a late sample: kept out of every flip denominator; counted
           in the finality coverage) |
           TRUNCATED | EMPTY | NO_BAR | ERROR | NOT_PULLED
  final    FINAL (compared) | NOT_FINAL (not final yet: unconfirmed, never a flip or a disappearance) |
           TRUNCATED (no prior history, the 01:50 block) | EMPTY | NO_BAR | ERROR | NOT_PULLED
  A name's final record is its FINAL row with the most history (the latest among equals), so a later error
  or truncated row never replaces good data. On the pairs: a missing quote close keeps the name out of every
  close-based test; a price change in the evening's t-1..t-4 candles (a basis change) keeps it out of the
  signal level; a volume-only revision of those candles is counted.

Night states: OK | LATE (the evening sample started after 19:30 ET, params.watchdog_evening_et, or on a later
  day, or an evening candle was already final) | NO-FINAL | MISSED-NIGHT | NO-EVENING. Calendar sessions without
  a folder between the first and the last sampled session are listed as NOT SAMPLED. LATE nights stay out of the
  pooled numbers unless --include-late is given.

BAR LEVEL (reads bars t-4..t only; always runs)
  Per-field difference rates per name-night (open, high, low, candle close, scan close, volume), per night
  and pooled with a night-clustered interval; |delta open| in % of price and its sign; final/evening volume
  ratios and their direction; quote openPrice vs the provisional open; the whole-cent trigger T from
  orders.trigger_from_high; every overnight pull's finality, and whether a 99% gate would have passed while names
  were still unfinished; the M2-like stratum on quote fields.

SIGNAL LEVEL (reads up to 120 sessions of look-back; guarded, below), both ways on every pair:
  eligible(t) (spec 3.1); close above its 50-session average and breadth B(t), with its distance to 50% and
  bounds for names that have no final bar; M1 through technicals.compute_levels(bars[t-119..t], last = T):
  valid_setup, atr_floor_ok, rr_to_resistance >= 3.0, touch low(t) <= anchor + 0.25 ATR(t), the knife;
  the M2 bar tests: gap >= max(3% of the prior close, 1.0 ATR(t-1)), volume >= 3 x the 30-session average
  ending t-1, held, the knife, eligible (no earnings-event filter, so an upper bound on M2 signals); SPY's
  own gap test; order levels T/C/S/P/N for k = 1.0, 1.5, 2.0 (confirmed, changed, disappeared, appeared) and
  tickets under breadth on; the day-t fill path through fills.step, for synthetic pending orders with
  triggers at -0.5..+0.5 ATR(t-1) around the final open and synthetic open trades with the stop or target
  there; each signal's margin to each threshold, and P(flip) estimated from the pooled deltas; exact one-sided
  95% upper bounds (Clopper-Pearson) for the counts: "0 of 10 M2 signals, upper bound 25.9%".

ACCEPTANCE BAR (the owner's ruling of 2026-11-12, spec 4 step 4, "What it decides"): "a method gets evening
  tickets only if it had zero flips on every sampled night, in either direction (a ticket changed, disappeared,
  or appeared only on final bars). Judge M1 and M2 separately. Any flip keeps that method on recheck tickets."
  The report prints, per method, "acceptance bar (ruled 2026-11-12): met / not met" over every reported night,
  LATE nights included (a MISSED-NIGHT or NO-EVENING night is skipped: it has no evening sample, so it is not a
  sampled night; --include-late does not change it): a flip is a ticket, at any k, with the breadth filter on or
  off, that changed, disappeared or appeared; at least 6 compared nights are needed. A night without the ticket comparison (no signal level, or a state other than OK or LATE) cannot
  show zero flips, so it leaves the bar not met; so does a report with no such night. The bar is judged only
  over all nights (--all, or no sessions named).

Order levels come from loops/phase2/orders.py only (review D6). It must import and pass a startup self-check on
known answers worked from the spec text; this module carries no copy of its formulas. Without a usable orders.py,
everything built from them is NOT RUN, with the reason in the report: the whole-cent T at the bar level, and the
whole signal level, because T is compute_levels' ``last`` (every M1 test reads it) and the order levels, the
tickets and the fill path's synthetic orders are brackets. A deliberate change to orders.py's rules (for example
a later ruling on how T rounds) therefore stops those sections until the known answers here are reviewed
and changed with it; the measurement never keeps a rule orders.py has dropped.

Look-back guard (spec 3.7 step 2), fail closed. The signal level never runs for a session inside the sealed
window 2025-01-02..2026-10-30 (fills.step would refuse it anyway, and this module never calls it there; such a
folder is ignored, above). Every night is PRE-go-live until GO_LIVE_ACTUAL below records the actual go-live date;
params.go_live_target is only a target and never opens the guard (review D2). A pre-go-live night whose
look-back reaches into the sealed window may read those bars as look-back by the owner's ruling of 2026-11-12
(spec 3.7: "Reading sealed bars as look-back to compute indicators for a session after October 30 is allowed
... Signal-level flip comparisons can resume"), recorded as PRE_GO_LIVE_LOOKBACK_RULED = True below: the second,
independent condition (review F1). It opens pre-go-live nights after 2026-10-30 only, never a sealed session,
and it reads the sealed bars only as one session's look-back (ATR, shelves, dollar volume, breadth): no statistic
here is aggregated over sealed sessions. Were the constant not True, those nights would get the bar level only.
Recording go-live and the ruling are one-line, reviewable edits of those two constants, never command-line
flags; the report says which nights were refused and why.

Usage:
  compare_bars.py --all                       every session folder under the root, pooled (folders that are not
                                              carried-calendar sessions after 2026-10-30 are listed as ignored)
  compare_bars.py 2026-11-30 2026-12-01       those nights, pooled
  options: --root DIR   --bars-only   --include-late
           --go-live DATE (only LATER than GO_LIVE_ACTUAL, to tighten the guard; refused while it is unset)
           --json PATH (also write the full report as JSON)   --examples N (names shown per list, default 8)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from collections import Counter
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Callable, Iterable, Optional

HERE = Path(__file__).resolve()
LOOPS = HERE.parents[1]
if str(LOOPS) not in sys.path:                          # run as a script: make `phase2` and `technicals` importable
    sys.path.insert(0, str(LOOPS))

import technicals  # noqa: E402  (compute_levels, unchanged: spec 2)
from phase2 import fills as F  # noqa: E402
from phase2 import sample_bars as SB  # noqa: E402
from phase2.params import PARAMS, params_hash  # noqa: E402

EPS = 1e-9
SEALED_FIRST, SEALED_LAST = dt.date(2025, 1, 2), dt.date(2026, 10, 30)     # spec 3.7 step 2
# The ACTUAL go-live date (spec 6: L is frozen at the actual go-live), a datetime.date set by a reviewed one-line
# edit once forward logging has really started. While it is None every night is pre-go-live, whatever
# params.go_live_target says: a target is not a record that go-live happened (review D2, fail closed).
GO_LIVE_ACTUAL: Optional[dt.date] = None
# The owner's ruling of 2026-11-12, recorded in spec 3.7: "Reading sealed bars as look-back to compute indicators
# for a session after October 30 is allowed. That covers ATR, shelves, dollar volume, and breadth for the drill,
# the nightly scan, and the flip comparison. Statistics aggregated over sealed sessions stay off-limits, except
# the 14 real fill records. ... Signal-level flip comparisons can resume." So PRE-go-live nights after 2026-10-30
# read sealed-window bars as look-back (review F1). Independent of GO_LIVE_ACTUAL, and it never opens a sealed
# session. Changing it is a reviewed edit, never a command-line flag; were it not True, those nights would get the
# bar level only.
PRE_GO_LIVE_LOOKBACK_RULED = True
# ATR(t-1) for M2 is ATR14 exactly as technicals.compute_levels computes ATR(t) (its trs[-14:]); params.py has no
# ATR-period field, so the 14 is compute_levels' own, kept here (spec 2: compute_levels unchanged).
ATR_PERIOD = 14
OFFSETS = tuple(round(-0.5 + 0.05 * i, 2) for i in range(21))              # ATR(t-1) units around the open
FIELDS = ("o", "h", "l", "c", "v")
CENT = Decimal("0.01")
CONF = 0.95
EV_CLASSES = (SB.PROVISIONAL, SB.ALREADY_FINAL, SB.TRUNCATED, SB.EMPTY, SB.NO_BAR, SB.ERROR, "NOT_PULLED")
FI_CLASSES = (SB.FINAL, SB.NOT_FINAL, SB.TRUNCATED, SB.EMPTY, SB.NO_BAR, SB.ERROR, "NOT_PULLED")
M1_TESTS = ("valid_setup", "atr_floor_ok", "rr", "touch", "eligible")
M2_TESTS = ("gap", "volume", "held", "knife_free", "eligible")


# =========================================================================================================
# Exact cents, and the order levels from loops/phase2/orders.py only (spec 3.4 "Order"; section 4; review D6)
# =========================================================================================================

def _dec(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(repr(round(float(x), 6)))


class OrdersUnavailable(RuntimeError):
    """loops/phase2/orders.py is missing or failed the startup self-check: no T, level or ticket can be built."""


def _module_levels(O, trigger: Decimal, atr: float, k: float, s0: Optional[float]) -> dict:   # noqa: N803
    """orders.build_bracket + paper_shares as a plain dict; S0 None means the ATR stop alone (orders.ATR_ONLY)."""
    b = O.build_bracket(trigger, atr, k, PARAMS, structural_stop=O.ATR_ONLY if s0 is None else s0)
    z = O.paper_shares(b, PARAMS)
    return dict(T=Decimal(str(b.trigger)), C=Decimal(str(b.ceiling)), S=Decimal(str(b.stop)),
                P=Decimal(str(b.target)), N=int(z.shares), sizable=bool(z.sizable))


# The startup self-check: KNOWN ANSWERS worked by hand from spec 3.4 "Order" and section 4 (each also equals the
# exact-fraction oracle tests/phase2_flip_helpers.spec_levels), not a copy of the formulas. They follow
# T = high + 0.01 rounded UP to the cent (orders.py's rounding, ruled 2026-11-12), C = floor(T + 0.25 ATR),
# S = floor(min(S0, T - k ATR)), P = ceil(T + 3 (T - S)), N = floor(min(15 / (C - S), 262.50 / C)), sizable from 3.
# A decided change to orders.py's rules changes these answers in the same reviewed edit; until then it fails here.
SELF_CHECK_T = ((20.511, Decimal("20.53")), (20.514, Decimal("20.53")), (20.6, Decimal("20.61")),
                (64.12, Decimal("64.13")), (41.315, Decimal("41.33")), (49.183, Decimal("49.20")),
                (49.190000000000005, Decimal("49.20")))
SELF_CHECK_LEVELS = (   # (T, ATR, k, S0 or None for the ATR stop alone) -> (T, C, S, P, N, sizable)
    ((Decimal("20.61"), 0.8036, 1.5, 19.84), ("20.61", "20.81", "19.40", "24.24", 10, True)),
    ((Decimal("20.61"), 0.8036, 1.0, 19.84), ("20.61", "20.81", "19.80", "23.04", 12, True)),
    ((Decimal("50.86"), 1.2133, 1.0, None), ("50.86", "51.16", "49.64", "54.52", 5, True)),
    ((Decimal("21.81"), 1.0571, 2.0, 20.6886), ("21.81", "22.07", "19.69", "28.17", 6, True)),
    ((Decimal("7.43"), 0.6125, 1.5, 6.9), ("7.43", "7.58", "6.51", "10.19", 14, True)),
    ((Decimal("93.51"), 0.7, 1.5, 92.46), ("93.51", "93.68", "92.46", "96.66", 2, False)),   # C > $87.50: unsizable
)
SELF_CHECK_REFUSED = ((Decimal("1.00"), 2.0, 1.0, None),)     # S = floor(1.00 - 2.00) is below zero: no bracket


def _order_module():
    """(orders module, description) when loops/phase2/orders.py imports and gives every known answer above;
    otherwise (None, why). There is no fallback: with None the T, the levels, the tickets and the signal level
    are NOT RUN, and the report prints why."""
    try:
        from phase2 import orders as O          # noqa: N812
    except Exception as e:
        return None, f"loops/phase2/orders.py is not usable: it cannot be imported ({type(e).__name__}: {e})"
    needed = ("build_bracket", "paper_shares", "trigger_from_high")
    if not all(callable(getattr(O, n, None)) for n in needed) or not hasattr(O, "ATR_ONLY"):
        return None, ("loops/phase2/orders.py is not usable: it lacks build_bracket / paper_shares / "
                      "trigger_from_high / ATR_ONLY")
    try:
        for high, want in SELF_CHECK_T:
            got = O.trigger_from_high(high, PARAMS)
            if got != want:
                return None, (f"loops/phase2/orders.py failed the startup self-check: trigger_from_high({high!r}) "
                              f"is {got}, the known answer is {want}")
        for args, (t, c, s, p, n, sizable) in SELF_CHECK_LEVELS:
            want = dict(T=Decimal(t), C=Decimal(c), S=Decimal(s), P=Decimal(p), N=n, sizable=sizable)
            got = _module_levels(O, *args)
            if got != want:
                return None, (f"loops/phase2/orders.py failed the startup self-check on {args}: {got}; "
                              f"the known answer is {want}")
        for args in SELF_CHECK_REFUSED:
            try:
                got = _module_levels(O, *args)
            except ValueError:
                continue
            return None, f"loops/phase2/orders.py failed the startup self-check: {args} must be refused, not {got}"
    except Exception as e:
        return None, f"loops/phase2/orders.py failed the startup self-check: it raised {type(e).__name__}: {e}"
    n = len(SELF_CHECK_T) + len(SELF_CHECK_LEVELS) + len(SELF_CHECK_REFUSED)
    return O, (f"loops/phase2/orders.py (trigger_from_high, build_bracket, paper_shares), self-checked on {n} "
               "known answers")


ORDERS, ORDER_SOURCE = _order_module()


def _orders():
    if ORDERS is None:
        raise OrdersUnavailable(ORDER_SOURCE)
    return ORDERS


def whole_cent_trigger(high: float) -> Decimal:
    """T = orders.trigger_from_high(high). Raises OrdersUnavailable without a usable orders.py (no local rule)."""
    return _orders().trigger_from_high(high, PARAMS)


def levels(trigger: Decimal, atr: float, k: float, s0: Optional[float]) -> Optional[dict]:
    """T/C/S/P/N for one bracket and k (S0 None: the ATR stop alone) from orders.py, or None when orders.py
    refuses the bracket (none is valid). Raises OrdersUnavailable without a usable orders.py."""
    O = _orders()                                 # noqa: N806
    try:
        return _module_levels(O, trigger, atr, k, s0)
    except (ValueError, ArithmeticError):
        return None


# =========================================================================================================
# Statistics
# =========================================================================================================

def _binom_cdf(x: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0 if x < n else 1.0
    lp, lq = math.log(p), math.log1p(-p)
    lg = math.lgamma(n + 1)
    return min(1.0, sum(math.exp(lg - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq)
                        for i in range(x + 1)))


def upper_bound(x: int, n: int, conf: float = CONF) -> Optional[float]:
    """Exact one-sided upper confidence bound (Clopper-Pearson) on a rate after x events in n trials."""
    if n <= 0:
        return None
    if x >= n:
        return 1.0
    if x == 0:
        return 1.0 - (1.0 - conf) ** (1.0 / n)
    lo, hi = x / n, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if _binom_cdf(x, n, mid) > 1.0 - conf:
            lo = mid
        else:
            hi = mid
    return hi


def clustered_ci(xs: list[int], ns: list[int]) -> Optional[tuple[float, float]]:
    """A night-clustered 95% interval for the pooled rate sum(x) / sum(n) (ratio estimator; rough with few nights)."""
    k, n = len(xs), sum(ns)
    if k < 2 or n == 0:
        return None
    p = sum(xs) / n
    var = k / (k - 1) * sum((x - p * m) ** 2 for x, m in zip(xs, ns)) / n ** 2
    se = math.sqrt(var)
    return max(0.0, p - 1.96 * se), min(1.0, p + 1.96 * se)


def rate(x: int, n: int) -> str:
    """'x of n (r%), 95% upper u%'."""
    if n <= 0:
        return f"{x} of 0"
    u = upper_bound(x, n)
    return f"{x} of {n} ({100 * x / n:.2f}%; 95% upper bound {100 * u:.1f}%)"


def quantiles(vals: Iterable[float], qs=(0.05, 0.5, 0.95)) -> Optional[dict]:
    v = sorted(vals)
    if not v:
        return None
    out = {f"p{int(q * 100)}": v[min(len(v) - 1, int(q * len(v)))] for q in qs}
    out.update(min=v[0], max=v[-1], n=len(v))
    return out


# =========================================================================================================
# Reading a night
# =========================================================================================================

def _load_jsonl(path: Path) -> tuple[list[dict], int]:
    rows, bad = [], 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            if isinstance(r, dict) and "symbol" in r:
                rows.append(r)
            else:
                bad += 1
    return rows, bad


def _fix_kinds(r: dict) -> dict:
    """Re-derive each stamped candle's kind AND date from its own stamp (the date as sample_bars.candle_from_raw
    derives it: the stamp's New York date), overwriting the stored labels. A row with a candle whose stored 'd'
    disagreed is marked with the number of such candles (``_label_mismatch``): its night gets no signal level,
    since the look-back guard must read the stamps, never a label (safety S6)."""
    bad = 0
    for c in r.get("candles") or []:
        if "ms" in c:
            c["kind"] = SB.stamp_kind(c["ms"])
            d = dt.datetime.fromtimestamp(c["ms"] / 1000, SB.NY).date().isoformat()
            if "d" in c and c["d"] != d:
                bad += 1
            c["d"] = d
    r.pop("_label_mismatch", None)                               # never a stored mark: only this count
    if bad:
        r["_label_mismatch"] = bad
    return r


def prior_finals(candles: list[dict], s_iso: str) -> list[dict]:
    """The final candles dated before the session, one per date, oldest first."""
    by = {}
    for c in candles or []:
        if c.get("d", "") < s_iso and c.get("kind") == "final":
            by[c["d"]] = c
    return [by[d] for d in sorted(by)]


def session_candle(candles: list[dict], s_iso: str, kind: str) -> Optional[dict]:
    """The session's candle of ``kind``; for 'provisional', any non-final stamp will do (the last one)."""
    hit = None
    for c in candles or []:
        if c.get("d") == s_iso and (c.get("kind") == kind or (kind == "provisional" and c.get("kind") != "final")):
            hit = c
    return hit


class NightFiles:
    """Everything stored for one session folder, rows grouped by symbol and ordered by pull time."""

    def __init__(self, day: Path) -> None:
        self.day, self.s_iso = day, day.name
        self.session = dt.date.fromisoformat(day.name)
        self.bad_lines = 0
        self.label_mismatch = 0                                     # candles whose stored date disagreed with the stamp
        self.candidates = None
        if (day / "candidates.json").exists():
            with open(day / "candidates.json") as fh:
                self.candidates = json.load(fh)
        self.universe = list(self.candidates.get("symbols", [])) if self.candidates else []
        self.reference = list(self.candidates.get("reference", [])) if self.candidates else []
        self.quotes: dict[str, dict] = {}
        self.evening: dict[str, list[dict]] = {}
        self.final: dict[str, list[dict]] = {}
        self.final_files: list[tuple[str, list[dict]]] = []
        self.minute: set[str] = set()
        quote_rows = []
        for p in sorted(day.glob("*.jsonl")):
            if p.name == "exclusions.jsonl":
                continue
            rows, bad = _load_jsonl(p)
            self.bad_lines += bad
            for r in rows:
                r["_file"] = p.name
                _fix_kinds(r)
                self.label_mismatch += r.get("_label_mismatch", 0)
            if p.name.startswith("quotes_"):
                quote_rows += rows
            elif p.name.startswith("evening_"):
                for r in rows:
                    self.evening.setdefault(r["symbol"], []).append(r)
            elif p.name.startswith("final_"):
                self.final_files.append((p.name, rows))
                for r in rows:
                    self.final.setdefault(r["symbol"], []).append(r)
            elif p.name.startswith("minute_"):
                self.minute |= {r["symbol"] for r in rows if r.get("candles")}
        for r in sorted(quote_rows, key=SB.pulled_at):            # the earliest evening quote per symbol
            self.quotes.setdefault(r["symbol"], r)
        if self.candidates is None and self.evening:              # no candidates.json: the evening rows decide
            self.universe = sorted(set(self.evening) - {"SPY"})
            self.reference = ["SPY"] if "SPY" in self.evening else []
        for d in (self.evening, self.final):
            for rows in d.values():
                rows.sort(key=SB.pulled_at)
        self.final_files.sort(key=lambda fr: min((SB.pulled_at(r) for r in fr[1]), default=dt.datetime.max.replace(
            tzinfo=dt.timezone.utc)))
        self.statuses = SB.statuses(day)


def pick_evening(rows: list[dict], s_iso: str) -> dict:
    """The earliest usable evening row (what a 17:30 scan saw); otherwise the best failure class."""
    worst = None
    for r in rows:
        cls = SB.row_class(r, s_iso, "evening")
        if cls in (SB.PROVISIONAL, SB.ALREADY_FINAL):
            kind = "provisional" if cls == SB.PROVISIONAL else "final"
            return dict(cls=cls, row=r, cand=session_candle(r["candles"], s_iso, kind),
                        prior=prior_finals(r["candles"], s_iso), pulled=SB.pulled_at(r))
        worst = SB.better_class(worst, cls)
    return dict(cls=worst or "NOT_PULLED", row=None, cand=None, prior=[], pulled=None)


def pick_final(rows: list[dict], s_iso: str) -> dict:
    """The FINAL row with the most history (latest among equals); never an error or degenerate row over it."""
    finals, worst = [], None
    for r in rows:
        cls = SB.row_class(r, s_iso, "final")
        if cls == SB.FINAL:
            finals.append(r)
        worst = SB.better_class(worst, cls)
    if not finals:
        best_nf = None
        if worst == SB.NOT_FINAL:
            best_nf = max((r for r in rows if SB.row_class(r, s_iso, "final") == SB.NOT_FINAL),
                          key=lambda r: (len(prior_finals(r["candles"], s_iso)), SB.pulled_at(r)))
        return dict(cls=worst or "NOT_PULLED", row=best_nf, cand=None,
                    hist=prior_finals(best_nf["candles"], s_iso) if best_nf else [], revised=False, from_earlier=False)
    chosen = max(finals, key=lambda r: (len(prior_finals(r["candles"], s_iso)), SB.pulled_at(r)))
    cands = [session_candle(r["candles"], s_iso, "final") for r in finals]
    revised = any(any(abs(a[f] - cands[0][f]) > EPS for f in FIELDS) for a in cands[1:])
    return dict(cls=SB.FINAL, row=chosen, cand=session_candle(chosen["candles"], s_iso, "final"),
                hist=prior_finals(chosen["candles"], s_iso), revised=revised,
                from_earlier=SB.pulled_at(chosen) < SB.pulled_at(rows[-1]))


def basis_check(eve_prior: list[dict], hist: list[dict]) -> tuple[str, bool]:
    """Compare the evening's t-1..t-4 final candles with the overnight history: ('ok' | 'unchecked' |
    'split-like x' | 'shift $x' | 'revised', volume-only revision?)."""
    by = {c["d"]: c for c in hist}
    common = [(e, by[e["d"]]) for e in eve_prior[-4:] if e["d"] in by]
    if not common:
        return "unchecked", False
    price = [(e, h) for e, h in common if any(abs(e[f] - h[f]) > EPS for f in ("o", "h", "l", "c"))]
    vol = any(e["v"] != h["v"] for e, h in common)
    if not price:
        return "ok", vol
    # across all four price fields: a split scales them all by one ratio, a special distribution moves them all
    # by one dollar amount (spec 4, basis-change detection); anything else is a revision
    pf = [(e[f], h[f]) for e, h in common for f in ("o", "h", "l", "c")]
    ratios = [b / a for a, b in pf if a]
    shifts = [b - a for a, b in pf]
    if ratios and max(ratios) - min(ratios) < 1e-4 and abs(ratios[0] - 1) > 1e-4:
        return f"split-like x{ratios[0]:.4f}", vol
    if max(shifts) - min(shifts) < 0.005 and abs(shifts[0]) >= 0.005:
        return f"shift ${shifts[0]:+.2f}", vol
    return "revised", vol


# =========================================================================================================
# Both ways: the tests a bar difference can flip
# =========================================================================================================

def atr14(candles: list[dict]) -> Optional[float]:
    """ATR14 exactly as compute_levels computes it (simple mean of ATR_PERIOD = 14 true ranges, 4 dp), ending at
    the last candle."""
    n = ATR_PERIOD
    if len(candles) < n + 1:
        return None
    trs = [max(c["h"] - c["l"], abs(c["h"] - p["c"]), abs(c["l"] - p["c"]))
           for p, c in zip(candles[-(n + 1):-1], candles[-n:])]
    return round(sum(trs) / n, 4)


def _tl(c: dict) -> dict:
    return dict(open=c["o"], high=c["h"], low=c["l"], close=c["c"], volume=c["v"])


def evaluate(hist: list[dict], bar: dict, prior60: Optional[set]) -> dict:
    """Every threshold test of spec 3.1-3.3 on day t's ``bar`` (o, h, l, c, v) given the final history through t-1.
    T comes from orders.py (OrdersUnavailable without it): compute_levels reads it as ``last``."""
    n = len(hist)
    out: dict = dict(n_hist=n)
    w_adv, w_cost = PARAMS.adv_window, PARAMS.cost_dollar_volume_window        # 30 and 30 sessions ending t-1
    adv30 = sum(c["v"] for c in hist[-w_adv:]) / w_adv if n >= w_adv else None
    adv_dollar = sum(c["c"] * c["v"] for c in hist[-w_cost:]) / w_cost if n >= w_cost else None
    present = sum(1 for c in hist if c["d"] in prior60) if prior60 is not None else None
    price_ok = PARAMS.price_min <= bar["c"] <= PARAMS.price_max
    out["eligible"] = bool(price_ok and adv30 is not None and adv30 >= PARAMS.adv_min_shares and present is not None
                           and present >= PARAMS.bars_present_min and n >= PARAMS.min_history_sessions)
    out.update(adv30=adv30, adv_dollar=adv_dollar, price_ok=price_ok)
    if n >= PARAMS.breadth_sma - 1:
        closes = [c["c"] for c in hist[-(PARAMS.breadth_sma - 1):]] + [bar["c"]]
        out["sma"] = sum(closes) / len(closes)
        out["above"] = _dec(bar["c"]) * len(closes) > sum(_dec(x) for x in closes)     # exact, as fills.py compares
    T = whole_cent_trigger(bar["h"])
    out["T"] = T
    if n < technicals.KNIFE_LOOKBACK + technicals.MIN_SUPPORT_AGE - 1:
        out["error"] = f"insufficient history ({n} prior sessions)"
        return out
    bars = [_tl(c) for c in hist[-(PARAMS.levels_window - 1):]] + [_tl(bar)]
    L = technicals.compute_levels(bars, last=float(T))
    if "error" in L:
        out["error"] = L["error"]
        return out
    atr_t, atr_prev, prev = L["atr14"], atr14(hist), hist[-1]
    out.update(L=L, atr_t=atr_t, atr_prev=atr_prev, prev_c=prev["c"])
    lows = [b["low"] for b in bars]
    prior_knife_min = min(lows[-technicals.KNIFE_LOOKBACK:-technicals.MIN_SUPPORT_AGE])
    unit = atr_prev or atr_t or None
    anchor = L["support_anchor"]
    # --- M1 (spec 3.2) ---
    touch = (anchor is not None and atr_t is not None
             and _dec(bar["l"]) <= _dec(anchor) + _dec(PARAMS.touch_atr) * _dec(atr_t))
    rr = L["rr_to_resistance"]
    m1 = dict(valid_setup=bool(L["valid_setup"]), atr_floor_ok=bool(L["atr_floor_ok"]),
              rr=rr is not None and rr >= PARAMS.m1_min_rr, touch=bool(touch), eligible=out["eligible"])
    out["m1"] = m1
    out["m1_signal"] = all(m1.values())
    out["knife"] = bool(L["falling_knife"])
    # margins: (test, field, sensitivity, margin in ATR(t-1) units; volume in log ratio)
    mg1 = []
    if unit:
        if anchor is not None and atr_t:
            mg1.append(("touch", "l", -1, (anchor + PARAMS.touch_atr * atr_t - bar["l"]) / unit))
        stop = L["suggested_stop"]
        if rr is not None:
            t_star = (L["nearest_resistance_40d"] + PARAMS.m1_min_rr * stop) / (1 + PARAMS.m1_min_rr)
            mg1.append(("rr", "h", -1, (t_star - float(T)) / unit))
        if atr_t:
            mg1.append(("atr_floor_ok", "h", +1, (float(T) - stop - technicals.ATR_FLOOR_MULT * atr_t) / unit))
        if L["support_floor"] is not None:
            mg1.append(("valid_setup", "l", +1, (bar["l"] - max(L["support_floor"], prior_knife_min)) / unit))
        mg1.append(_price_margin(bar["c"], unit))
    out["m1_margins"] = mg1
    # --- M2 (spec 3.2), no earnings-event filter ---
    if atr_prev and adv30:
        need = max(PARAMS.m2_gap_pct * prev["c"], PARAMS.m2_gap_atr * atr_prev)
        gap = bar["o"] - prev["c"]
        mid = bar["l"] + PARAMS.m2_close_range_min * (bar["h"] - bar["l"])
        # the thresholds compared exactly (Decimal at the millionth), so a cent-exact tie lands as spec 3.2 reads
        need_x = max(_dec(PARAMS.m2_gap_pct) * _dec(prev["c"]), _dec(PARAMS.m2_gap_atr) * _dec(atr_prev))
        mid_x = _dec(bar["l"]) + _dec(PARAMS.m2_close_range_min) * (_dec(bar["h"]) - _dec(bar["l"]))
        vol_x = (_dec(bar["v"]) * PARAMS.adv_window
                 >= _dec(PARAMS.m2_volume_mult) * sum(_dec(c["v"]) for c in hist[-PARAMS.adv_window:]))
        m2 = dict(gap=_dec(bar["o"]) - _dec(prev["c"]) >= need_x, volume=vol_x,
                  held=_dec(bar["l"]) > _dec(prev["c"]) and _dec(bar["c"]) >= mid_x, knife_free=not L["falling_knife"],
                  eligible=out["eligible"])
        out.update(m2=m2, m2_signal=all(m2.values()), gap=gap, need=need)
        mg2 = [("gap", "o", +1, (gap - need) / atr_prev),
               ("held_low", "l", +1, (bar["l"] - prev["c"]) / atr_prev),
               ("held_close", "c", +1, (bar["c"] - mid) / atr_prev),
               ("knife_free", "l", +1, (bar["l"] - prior_knife_min) / atr_prev),
               _price_margin(bar["c"], atr_prev)]
        if bar["v"] > 0:
            mg2.insert(1, ("volume", "v", +1, math.log(bar["v"] / (PARAMS.m2_volume_mult * adv30))))
        out["m2_margins"] = mg2
        out["m2_like"] = abs(gap) / prev["c"] >= SB.M2_LIKE_GAP and bar["v"] >= SB.M2_LIKE_VOLUME * adv30
    return out


def _price_margin(close: float, unit: float) -> tuple:
    lo, hi = close - PARAMS.price_min, PARAMS.price_max - close
    return ("eligible", "c", +1, lo / unit) if lo <= hi else ("eligible", "c", -1, hi / unit)


# =========================================================================================================
# The day-t fill path through fills.step (sessions outside the sealed window only)
# =========================================================================================================

def in_sealed_window(d: dt.date) -> bool:
    first, last = dt.date.fromisoformat(PARAMS.oos_start), dt.date.fromisoformat(PARAMS.oos_end)
    return SEALED_FIRST <= d <= SEALED_LAST or first <= d <= last


def _outcome(o: F.Order) -> tuple:
    r6 = (lambda x: None if x is None else round(x, 6))
    return (o.state, o.entry_kind, r6(o.entry_raw), o.exit_kind, r6(o.exit_raw), o.cancel_reason)


def _change_kind(a: tuple, b: tuple) -> Optional[str]:
    if a == b:
        return None
    for i, label in enumerate(("state", "entry kind", "entry price", "exit kind", "exit price", "cancel reason")):
        if a[i] != b[i]:
            return label
    return "other"


def synthetic_orders(sym: str, fin_open: float, atr: float, tier: float, signal_d: dt.date, prev_d: dt.date,
                     prev2_d: Optional[dt.date]) -> tuple[list[tuple[str, F.Order]], int]:
    """(family, order) for the replay grid, and how many grid points had no valid order (0 < S < T <= C < P).
    Every bracket comes from orders.py (``levels``); only the grid points are chosen here: a pending entry's T is
    the grid price rounded up to the cent, and an open trade's T is the cent that puts its stop S exactly at the
    grid's stop (T = ceil(S + k ATR), so S0 = S binds)."""
    out, bad = [], 0
    a = _dec(atr)
    for off in OFFSETS:
        x = _dec(fin_open) + _dec(off) * a
        for k in PARAMS.stop_k:                                 # pending entries, one per k
            lv = levels(x.quantize(CENT, rounding=ROUND_CEILING), atr, k, None)
            if lv is None:
                bad += 1
                continue
            try:
                out.append(("pending", F.Order(ticker=sym, signal_date=signal_d, trigger=float(lv["T"]),
                                               ceiling=float(lv["C"]), stop=float(lv["S"]), target=float(lv["P"]),
                                               window=PARAMS.m2_window, atr=atr, tier_bps=tier)))
            except ValueError:
                bad += 1
        if prev2_d is None:
            continue
        k = PARAMS.default_k
        for family, s in (("open, stop near the open", x.quantize(CENT, rounding=ROUND_FLOOR)),
                          ("open, target near the open",
                           (x.quantize(CENT, rounding=ROUND_CEILING) - 4 * _dec(k) * a).quantize(CENT, rounding=ROUND_FLOOR))):
            lv = levels((s + _dec(k) * a).quantize(CENT, rounding=ROUND_CEILING), atr, k, s)
            if lv is None:
                bad += 1
                continue
            try:
                entry = float(lv["T"])
                out.append((family, F.Order(ticker=sym, signal_date=prev2_d, trigger=entry, ceiling=float(lv["C"]),
                                            stop=float(lv["S"]), target=float(lv["P"]), window=PARAMS.m1_window,
                                            atr=atr, tier_bps=tier, state=F.OPEN, last_session=prev_d,
                                            sessions_pending=1, entry_date=prev_d, entry_kind=F.ENTRY_TRIGGER,
                                            entry_raw=entry, entry_cost=F.half_spread(entry, tier, PARAMS),
                                            sessions_held=1)))
            except ValueError:
                bad += 1
    return out, bad


def replay_fill_paths(sym: str, session: dt.date, eve: dict, fin: dict, atr: float, tier: float,
                      hist: list[dict]) -> dict:
    """Step every synthetic order once on day t with the evening bar and with the final bar; count changes."""
    if in_sealed_window(session):                               # never: the guard refuses these nights first
        raise RuntimeError(f"{session} is inside the sealed window; the fill path is not replayed there")
    res = Counter()
    kinds = Counter()
    prev_d = dt.date.fromisoformat(hist[-1]["d"])
    prev2_d = dt.date.fromisoformat(hist[-2]["d"]) if len(hist) >= 2 else None
    orders, bad = synthetic_orders(sym, fin["o"], atr, tier, prev_d, prev_d, prev2_d)
    res["not_constructible"] += bad
    try:
        be = F.Bar(session, eve["o"], eve["h"], eve["l"], eve["c"])
        bf = F.Bar(session, fin["o"], fin["h"], fin["l"], fin["c"])
    except ValueError:
        res["impossible_bar"] += 1
        return dict(counts=dict(res), kinds={})
    same = all(abs(eve[f] - fin[f]) <= EPS for f in ("o", "h", "l", "c"))
    for family, order in orders:
        res[f"{family}: orders"] += 1
        if same:
            continue
        a = _outcome(F.step(order, session, be, breadth_ok=True, params=PARAMS))
        b = _outcome(F.step(order, session, bf, breadth_ok=True, params=PARAMS))
        kind = _change_kind(a, b)
        if kind:
            res[f"{family}: changed"] += 1
            kinds[f"{family}: {kind}"] += 1
    res["identical_bars"] += int(same)
    return dict(counts=dict(res), kinds=dict(kinds))


# =========================================================================================================
# One night
# =========================================================================================================

def go_live_actual() -> Optional[dt.date]:
    """GO_LIVE_ACTUAL when it is a datetime.date; None otherwise (unset, or not a plain date: fail closed)."""
    return GO_LIVE_ACTUAL if type(GO_LIVE_ACTUAL) is dt.date else None


def effective_go_live(requested: Optional[dt.date] = None) -> Optional[dt.date]:
    """The go-live date the guard uses: GO_LIVE_ACTUAL, or a later ``requested`` date (a request only tightens).
    None while GO_LIVE_ACTUAL is unset: then every night is pre-go-live, whatever is requested, and
    params.go_live_target is never read for it (review D2)."""
    actual = go_live_actual()
    if actual is None:
        return None
    return max(actual, requested) if requested is not None else actual


def lookback_guard(session: dt.date, earliest: Optional[dt.date], latest: Optional[dt.date],
                   go_live: Optional[dt.date]) -> tuple[bool, str]:
    """May the signal level read this night's look-back bars? (spec 3.7 step 2; reviews F1 and D2)

    ``go_live`` is the effective go-live (``effective_go_live``); None means go-live is not recorded, so the
    night is pre-go-live. Two independent conditions open a night whose look-back reaches into the sealed
    window: it is on or after the recorded go-live, or PRE_GO_LIVE_LOOKBACK_RULED is True (the owner's ruling of
    2026-11-12, spec 3.7: sealed bars may be read as look-back for any session after 2026-10-30). Neither opens a
    session inside the sealed window."""
    if in_sealed_window(session):
        return False, (f"session {session} is inside the sealed OOS window {SEALED_FIRST}..{SEALED_LAST} "
                       "(spec 3.7 step 2)")
    overlaps = earliest is not None and latest is not None and earliest <= SEALED_LAST and latest >= SEALED_FIRST
    pre_go_live = go_live is None or session < go_live
    if pre_go_live and overlaps and PRE_GO_LIVE_LOOKBACK_RULED is not True:
        when = (f"go-live {go_live}" if go_live is not None else
                f"go-live not recorded: GO_LIVE_ACTUAL is unset, and params.go_live_target {PARAMS.go_live_target} "
                f"is only a target")
        return False, (f"pre-go-live night ({when}) whose look-back ({earliest}..{latest}) reaches into "
                       f"the sealed window, and PRE_GO_LIVE_LOOKBACK_RULED, which records the owner's 2026-11-12 "
                       f"ruling (spec 3.7), is not True: such look-back is then read only for post-go-live sessions "
                       f"(review F1)")
    return True, ""


def _night_state(nf: NightFiles, ev_usable: int, late: list[str]) -> str:
    if not ev_usable:
        return "MISSED-NIGHT" if any(s.get("state") == "MISSED-NIGHT" for s in nf.statuses) else "NO-EVENING"
    if not nf.final:
        return "NO-FINAL"
    return "LATE" if late else "OK"


def analyze_night(day: Path, *, bars_only: bool = False, go_live: Optional[dt.date] = None,
                  examples: int = 8) -> dict:
    """Every counter for one session folder. Pure apart from reading the folder. ``go_live`` may only move the
    recorded go-live later (``effective_go_live``); it never opens the guard while GO_LIVE_ACTUAL is unset."""
    go_live = effective_go_live(go_live)
    nf = NightFiles(day)
    s_iso, session = nf.s_iso, nf.session
    T: Counter = Counter()               # summable tallies
    L: dict[str, list] = {}               # poolable lists

    def keep(key: str, item) -> None:
        L.setdefault(key, []).append(item)

    universe, reference = nf.universe, nf.reference
    ev = {s: pick_evening(nf.evening.get(s, []), s_iso) for s in universe + reference}
    fi = {s: pick_final(nf.final.get(s, []), s_iso) for s in universe + reference}
    for s in universe:
        T[f"ev_{ev[s]['cls']}"] += 1
        T[f"fi_{fi[s]['cls']}"] += 1
    T["universe"] = len(universe)
    names = {k: [] for k in ("already_final", "evening_truncated", "not_final_yet", "final_truncated", "final_empty",
                             "final_error", "final_no_bar", "final_not_pulled", "no_quote_close", "basis_change",
                             "truncated_response")}
    for s in universe + reference:                 # TRUNCATED responses as their own class, whatever came later
        n_trunc = sum(1 for r in nf.evening.get(s, []) if SB.row_class(r, s_iso, "evening") == SB.TRUNCATED)
        n_trunc += sum(1 for r in nf.final.get(s, []) if SB.row_class(r, s_iso, "final") == SB.TRUNCATED)
        if n_trunc:
            T["truncated_responses"] += n_trunc
            names["truncated_response"].append(s)
    # --- lateness and state ---
    pulled = [e["pulled"] for e in ev.values() if e["pulled"] is not None]
    late: list[str] = []
    first_evening = min(pulled) if pulled else None
    if first_evening is not None:
        timing, why = SB.evening_timing(first_evening, session)
        if timing != "ON_TIME":
            late += why
    if T[f"ev_{SB.ALREADY_FINAL}"]:
        late.append(f"{T[f'ev_{SB.ALREADY_FINAL}']} evening candle(s) already final")
    for st in nf.statuses:
        if st.get("mode") == "evening" and st.get("late"):
            late += [r for r in st.get("late_reasons", []) if r not in late]
    ev_usable = T[f"ev_{SB.PROVISIONAL}"] + T[f"ev_{SB.ALREADY_FINAL}"]
    state = _night_state(nf, ev_usable, late)
    night = dict(session=s_iso, tags=SB.session_tags(session), state=state, late_reasons=late,
                 evening_first=SB.iso(first_evening) if first_evening else None,
                 evening_last=SB.iso(max(pulled)) if pulled else None,
                 final_files=[f for f, _ in nf.final_files], reference=reference,
                 statuses=[{k: st.get(k) for k in ("mode", "state", "started", "finished", "reason", "error")}
                           for st in nf.statuses],
                 bad_lines=nf.bad_lines, minute_symbols=len(nf.minute),
                 orders_unavailable=None if ORDERS is not None else ORDER_SOURCE)
    # --- pairs ---
    pairs = []
    for s in universe:
        e, f = ev[s], fi[s]
        if e["cls"] == SB.ALREADY_FINAL:
            names["already_final"].append(s)
        elif e["cls"] == SB.TRUNCATED:
            names["evening_truncated"].append(s)
        if e["cls"] != SB.PROVISIONAL:
            continue
        if f["cls"] != SB.FINAL:
            key = {SB.NOT_FINAL: "not_final_yet", SB.TRUNCATED: "final_truncated", SB.EMPTY: "final_empty",
                   SB.ERROR: "final_error", SB.NO_BAR: "final_no_bar"}.get(f["cls"], "final_not_pulled")
            names[key].append(s)
            continue
        q = nf.quotes.get(s) or {}
        pairs.append(dict(sym=s, prov=e["cand"], fin=f["cand"], hist=f["hist"], eve_prior=e["prior"], q=q,
                          qclose=q.get("regular_last")))
        T["final_from_earlier_pull"] += int(f["from_earlier"])
        T["final_revised_between_pulls"] += int(f["revised"])
    T["pairs"] = len(pairs)
    # --- finality timeline ---
    with_bar = {s for s in universe if ev[s]["cls"] in (SB.PROVISIONAL, SB.ALREADY_FINAL)}
    cum: set[str] = set()
    timeline = []
    for fname, rows in nf.final_files:
        best: dict[str, str] = {}
        for r in rows:
            best[r["symbol"]] = SB.better_class(best.get(r["symbol"]), SB.row_class(r, s_iso, "final"))
        cum |= {s for s, c in best.items() if c == SB.FINAL}
        cls = Counter(c for s, c in best.items() if s in with_bar)
        coverage = len(cum & with_bar) / len(with_bar) if with_bar else 0.0
        unfinished = with_bar - cum
        ref_final = all(r in cum for r in reference) if reference else None
        passes_names = coverage >= PARAMS.completeness_min
        times = [SB.pulled_at(r) for r in rows]
        timeline.append(dict(file=fname, first=SB.iso(min(times)) if times else None,
                             last=SB.iso(max(times)) if times else None, rows=len(rows), symbols=len(best),
                             classes=dict(cls), coverage=coverage, spy_final=ref_final,
                             gate_99=(passes_names and ref_final) if ref_final is not None else None,
                             gate_99_names_only=passes_names, unfinished=len(unfinished),
                             unfinished_by_class=dict(Counter(best.get(s, "NOT_PULLED") for s in unfinished)),
                             unfinished_examples=sorted(unfinished)[:examples]))
    night["timeline"] = timeline
    # --- bar level ---
    for p in pairs:
        pv, fn, q = p["prov"], p["fin"], p["q"]
        for f in ("o", "h", "l", "v"):
            T[f"diff_{f}"] += int(abs(pv[f] - fn[f]) > EPS)
        T["diff_c_candle"] += int(abs(pv["c"] - fn["c"]) > EPS)
        if p["qclose"] is None:
            T["no_quote_close"] += 1
            names["no_quote_close"].append(p["sym"])
        else:
            T["pairs_with_quote_close"] += 1
            T["diff_c_scan"] += int(abs(p["qclose"] - fn["c"]) > EPS)
            T["diff_any_price"] += int(any(abs(pv[f] - fn[f]) > EPS for f in ("o", "h", "l"))
                                       or abs(p["qclose"] - fn["c"]) > EPS)
        d_open = fn["o"] - pv["o"]
        if abs(d_open) > EPS:
            T["open_up" if d_open > 0 else "open_down"] += 1
            keep("open_delta_pct", 100 * d_open / pv["o"])
            keep("x_open", f"{p['sym']} {pv['o']} -> {fn['o']} ({100 * d_open / pv['o']:+.2f}% of the evening open)")
        if pv["v"]:
            ratio = fn["v"] / pv["v"]
            keep("vol_ratio", ratio)
            T["vol_up" if ratio > 1 else "vol_down" if ratio < 1 else "vol_same"] += 1
        if q.get("open") is not None:
            T["quote_open_compared"] += 1
            T["quote_open_equal"] += int(abs(q["open"] - pv["o"]) <= EPS)
        if ORDERS is not None:                     # T only from orders.py; without it this counter is NOT RUN
            if whole_cent_trigger(pv["h"]) != whole_cent_trigger(fn["h"]):
                T["trigger_moves"] += 1
                keep("x_trigger", f"{p['sym']} T {whole_cent_trigger(pv['h'])} -> {whole_cent_trigger(fn['h'])}")
        if SB.m2_like_quote(q):
            T["m2like_q_n"] += 1
            T["m2like_q_open_diff"] += int(abs(d_open) > EPS)
        status, vol_rev = basis_check(p["eve_prior"], p["hist"])
        p["basis"] = status
        T["prior_volume_revised"] += int(vol_rev)
        if status == "unchecked":
            T["basis_unchecked"] += 1
        elif status != "ok":
            T["basis_change"] += 1
            names["basis_change"].append(f"{p['sym']} ({status})")
    night["names"] = {k: v[:examples] for k, v in names.items()}
    night["names_count"] = {k: len(v) for k, v in names.items()}
    # --- signal level ---
    night["signals"] = None
    night["label_mismatch"] = nf.label_mismatch
    if bars_only:
        night["signals"] = dict(run=False, reason="--bars-only")
    elif nf.label_mismatch:                        # the guard reads dates: labels that lie about them close it
        night["signals"] = dict(run=False, reason=f"stored dates disagree with the stamps ({nf.label_mismatch} "
                                                  f"candles)")
    else:
        ds = [c["d"] for p in pairs for c in p["hist"]] + [c["d"] for r in reference for c in fi[r]["hist"]]
        ok, why = lookback_guard(session, dt.date.fromisoformat(min(ds)) if ds else None,
                                 dt.date.fromisoformat(max(ds)) if ds else None, go_live)
        if not ok:
            night["signals"] = dict(run=False, reason=why)
        elif ORDERS is None:
            night["signals"] = dict(run=False, reason=(
                f"{ORDER_SOURCE}. T (compute_levels' last, read by every M1 test), the order levels, the tickets and "
                f"the fill path's brackets come only from orders.py (review D6)"), orders_unavailable=True)
        elif not pairs:
            night["signals"] = dict(run=False, reason="no compared names")
        else:
            night["signals"] = _signal_level(session, pairs, ev, fi, reference, universe, T, keep, examples)
    night["tally"], night["lists"] = dict(T), L
    return night


def _signal_level(session: dt.date, pairs: list[dict], ev: dict, fi: dict, reference: list[str], universe: list[str],
                  T: Counter, keep: Callable, examples: int) -> dict:
    s_iso = session.isoformat()
    spy = "SPY" if "SPY" in reference else None
    if spy and fi[spy]["cls"] == SB.FINAL:
        session_list = [c["d"] for c in fi[spy]["hist"]]
        calendar_source = "SPY's final bar dates"
    else:
        session_list = sorted({c["d"] for p in pairs for c in p["hist"]})
        calendar_source = "the union of the sampled names' bar dates (SPY not final or not sampled)"
    prior60 = set(session_list[-PARAMS.bars_present_window:])
    out: dict = dict(run=True, calendar_source=calendar_source)
    for p in pairs:
        if p["qclose"] is None or p["basis"] not in ("ok", "unchecked"):
            continue
        eve_bar = dict(o=p["prov"]["o"], h=p["prov"]["h"], l=p["prov"]["l"], c=p["qclose"], v=p["prov"]["v"])
        fin_bar = {f: p["fin"][f] for f in FIELDS}
        a, b = evaluate(p["hist"], eve_bar, prior60), evaluate(p["hist"], fin_bar, prior60)
        p.update(eve_bar=eve_bar, fin_bar=fin_bar, a=a, b=b)
        T["sig_pairs"] += 1
        if "error" in a or "error" in b:
            T["sig_short_history"] += 1
    used = [p for p in pairs if "a" in p]
    # eligibility and the 50-session average
    for p in used:
        a, b = p["a"], p["b"]
        T["elig_eve"] += int(a["eligible"])
        T["elig_fin"] += int(b["eligible"])
        if a["eligible"] != b["eligible"]:
            T["elig_flip"] += 1
            keep("x_elig", f"{p['sym']} {a['eligible']} -> {b['eligible']} (close {p['eve_bar']['c']} -> {p['fin_bar']['c']})")
        if "above" in a and "above" in b:
            T["sma_n"] += 1
            if a["above"] != b["above"]:
                T["sma_flip"] += 1
                keep("x_sma", f"{p['sym']} above {a['above']} -> {b['above']}")
    # breadth B(t), both ways, on the paired names
    def breadth(side: str) -> dict:
        e = [p for p in used if p[side]["eligible"] and "above" in p[side]]
        above = sum(1 for p in e if p[side]["above"])
        n = len(e)
        b = above / n if n else None
        gate = b is not None and b >= PARAMS.breadth_min
        to_flip = (math.floor(above - PARAMS.breadth_min * n) + 1) if gate else math.ceil(PARAMS.breadth_min * n - above)
        return dict(eligible=n, above=above, B=b, gate_open=gate, names_to_flip=to_flip if n else None)
    be, bf = breadth("a"), breadth("b")
    missing_final = sum(1 for s in universe if ev[s]["cls"] == SB.PROVISIONAL and fi[s]["cls"] != SB.FINAL)
    lo = bf["above"] / (bf["eligible"] + missing_final) if bf["eligible"] + missing_final else None
    hi = (bf["above"] + missing_final) / (bf["eligible"] + missing_final) if bf["eligible"] + missing_final else None
    out["breadth"] = dict(evening=be, final=bf, gate_flip=be["gate_open"] != bf["gate_open"],
                          missing_final=missing_final, final_low=lo, final_high=hi,
                          final_gate_robust=None if lo is None else (lo >= PARAMS.breadth_min) == (hi >= PARAMS.breadth_min))
    T["breadth_nights"] += 1
    T["breadth_gate_flip"] += int(out["breadth"]["gate_flip"])
    # M1 and M2, both ways
    for m, tests in (("m1", M1_TESTS), ("m2", M2_TESTS)):
        for p in used:
            a, b = p["a"], p["b"]
            if m not in a or m not in b:
                continue
            T[f"{m}_n"] += 1
            for t in tests:
                if a[m][t] != b[m][t]:
                    T[f"{m}_t_{t}_flip"] += 1
                T[f"{m}_t_{t}_pass_fin"] += int(b[m][t])
            sa, sb = a[f"{m}_signal"], b[f"{m}_signal"]
            T[f"{m}_eve"] += int(sa)
            T[f"{m}_fin"] += int(sb)
            T[f"{m}_either"] += int(sa or sb)
            T[f"{m}_both"] += int(sa and sb)
            if sa != sb:
                T[f"{m}_flip"] += 1
                why = [t for t in tests if a[m][t] != b[m][t]]
                keep(f"x_{m}", f"{p['sym']} evening {sa} -> final {sb} ({', '.join(why)})")
            for side, val, other in (("evening", a, b), ("final", b, a)):
                if val[f"{m}_signal"]:
                    keep("signals", dict(sym=p["sym"], night=s_iso, method=m.upper(), side=side,
                                         flipped=not other[f"{m}_signal"], margins=val[f"{m}_margins"]))
    for p in used:
        a, b = p["a"], p["b"]
        if "knife" in a and "knife" in b:
            T["knife_n"] += 1
            T["knife_flip"] += int(a["knife"] != b["knife"])
        if "m2_like" in b:
            T["m2like_b_n"] += int(b["m2_like"])
            T["m2like_b_open_diff"] += int(b["m2_like"] and abs(p["eve_bar"]["o"] - p["fin_bar"]["o"]) > EPS)
    # volume revisions near the 3.0x line: within the night's largest revisions?
    ratios = [p["fin_bar"]["v"] / p["eve_bar"]["v"] for p in used if p["eve_bar"]["v"]]
    if ratios:
        up, down = max(ratios), min(ratios)
        for p in used:
            a = p["a"]
            if a.get("adv30") and p["eve_bar"]["v"]:
                r_e = p["eve_bar"]["v"] / a["adv30"]
                line = PARAMS.m2_volume_mult
                T["volume_reach"] += int((r_e < line <= r_e * up) or (r_e >= line > r_e * down))
    # SPY's own gap test (fallback mode: gap < +1.0%)
    out["spy_gap"] = None
    if spy and ev[spy]["cls"] == SB.PROVISIONAL and fi[spy]["cls"] == SB.FINAL and fi[spy]["hist"]:
        pc = fi[spy]["hist"][-1]["c"]
        ge, gf = ev[spy]["cand"]["o"] / pc - 1, fi[spy]["cand"]["o"] / pc - 1
        out["spy_gap"] = dict(evening=ge, final=gf, ok_evening=ge < PARAMS.m2_spy_gap_max,
                              ok_final=gf < PARAMS.m2_spy_gap_max, flip=(ge < PARAMS.m2_spy_gap_max) != (gf < PARAMS.m2_spy_gap_max))
        T["spy_nights"] += 1
        T["spy_gap_flip"] += int(out["spy_gap"]["flip"])
    # order levels and tickets
    for p in used:
        a, b = p["a"], p["b"]
        for m in ("m1", "m2"):
            sa, sb = a.get(f"{m}_signal", False), b.get(f"{m}_signal", False)
            if not (sa or sb):
                continue
            for k in PARAMS.stop_k:
                la = _signal_levels(m, a, p["eve_bar"], k) if sa else None
                lb = _signal_levels(m, b, p["fin_bar"], k) if sb else None
                key = f"lv_{m}_{k}"
                if la and lb:
                    diff = [f for f in ("T", "C", "S", "P", "N") if la[f] != lb[f]]
                    T[f"{key}_{'changed' if diff else 'confirmed'}"] += 1
                    for f in diff:
                        T[f"{key}_field_{f}"] += 1
                    if diff:
                        keep("x_levels", f"{p['sym']} {m.upper()} k={k}: " + ", ".join(f"{f} {la[f]}->{lb[f]}" for f in diff))
                elif la or lb:
                    T[f"{key}_{'disappeared' if la else 'appeared'}"] += 1
                else:
                    T[f"{key}_unbuildable"] += 1
                ta = bool(la and la["sizable"] and out["breadth"]["evening"]["gate_open"])
                tb = bool(lb and lb["sizable"] and out["breadth"]["final"]["gate_open"])
                tkey = f"tk_{m}_{k}"
                if ta and tb:
                    same = all(la[f] == lb[f] for f in ("T", "C", "S", "P", "N"))
                    T[f"{tkey}_{'confirmed' if same else 'changed'}"] += 1
                elif ta or tb:
                    T[f"{tkey}_{'disappeared' if ta else 'appeared'}"] += 1
                # the same ticket with the breadth filter off (the owner, 2026-11-12: count flips with the filter on
                # and off the same way; the December pick can land on either)
                oa, ob = bool(la and la["sizable"]), bool(lb and lb["sizable"])
                okey = f"tko_{m}_{k}"
                if oa and ob:
                    same = all(la[f] == lb[f] for f in ("T", "C", "S", "P", "N"))
                    T[f"{okey}_{'confirmed' if same else 'changed'}"] += 1
                elif oa or ob:
                    T[f"{okey}_{'disappeared' if oa else 'appeared'}"] += 1
    # the day-t fill path
    for p in used:
        a = p["a"]
        atr, adv_dollar = a.get("atr_prev"), a.get("adv_dollar")
        if not atr or not adv_dollar or len(p["hist"]) < 1:
            T["fill_skipped"] += 1
            continue
        r = replay_fill_paths(p["sym"], session, p["eve_bar"], p["fin_bar"], atr,
                              F.tier_bps(adv_dollar, PARAMS), p["hist"])
        changed = 0
        for k, v in r["counts"].items():
            T[f"fill_{k}"] += v
            if k.endswith(": changed"):
                changed += v
        for k, v in r["kinds"].items():
            T[f"fillkind_{k}"] += v
        T["fill_names"] += 1
        if changed:
            T["fill_names_changed"] += 1
            moved = ", ".join(f"{f} {p['eve_bar'][f]} -> {p['fin_bar'][f]}" for f in ("o", "h", "l", "c")
                              if abs(p["eve_bar"][f] - p["fin_bar"][f]) > EPS)
            keep("x_fill", f"{p['sym']} ({moved}): {changed} synthetic orders change "
                           f"({', '.join(f'{k} {v}' for k, v in sorted(r['kinds'].items()))})")
    # pooled deltas, in ATR(t-1) units (volume: log ratio), final minus evening
    for p in used:
        atr = p["a"].get("atr_prev")
        if not atr:
            continue
        T["delta_n"] += 1
        for f in ("o", "h", "l", "c"):
            keep(f"d_{f}", (p["fin_bar"][f] - p["eve_bar"][f]) / atr)
        if p["eve_bar"]["v"] > 0 and p["fin_bar"]["v"] > 0:
            keep("d_v", math.log(p["fin_bar"]["v"] / p["eve_bar"]["v"]))
        d_open = abs(p["fin_bar"]["o"] - p["eve_bar"]["o"])
        if d_open > EPS:
            keep("open_delta_atr", d_open / atr)
    return out


def _signal_levels(m: str, side: dict, bar: dict, k: float) -> Optional[dict]:
    atr_t = side.get("atr_t")
    if not atr_t:
        return None
    s0 = side["L"]["suggested_stop"] if m == "m1" else bar["l"] - PARAMS.stop_buffer_atr * atr_t
    return levels(side["T"], atr_t, k, s0)


# =========================================================================================================
# Pooling and the margin-based estimate
# =========================================================================================================

def flip_estimates(signals: list[dict], deltas: dict[str, list[float]]) -> list[dict]:
    """P(flip | signal) <= sum over its tests of P(delta beyond the margin, in the flipping direction), each
    estimated from the pooled deltas (final minus evening; reversed for a final-side signal) with an exact bound."""
    out = []
    for sg in signals:
        parts, p_sum, u_sum = [], 0.0, 0.0
        sign = 1 if sg["side"] == "evening" else -1
        for test, field, sens, margin in sg["margins"]:
            d = deltas.get(field) or []
            if not d or margin is None or margin < 0:
                continue
            x = sum(1 for v in d if sens * sign * v < -margin)
            p, u = x / len(d), upper_bound(x, len(d))
            parts.append(dict(test=test, field=field, margin=margin, x=x, n=len(d), p=p, upper=u))
            p_sum += p
            u_sum += u or 0.0
        tightest = min(parts, key=lambda q: q["margin"], default=None)
        out.append(dict(sg, parts=parts, p=min(1.0, p_sum), upper=min(1.0, u_sum), tightest=tightest))
    return out


def pool(nights: list[dict]) -> dict:
    T: Counter = Counter()
    L: dict[str, list] = {}
    for n in nights:
        T.update(n["tally"])
        for k, v in n["lists"].items():
            L.setdefault(k, []).extend(v)
    return dict(tally=dict(T), lists=L)


def night_folders(root: Path) -> tuple[list[Path], list[dict]]:
    """(the session folders the report reads, the folders it ignores, each with its reason). A night is a folder
    named by a session inside sample_bars' carried calendar, after 2026-10-30; any other folder under the root (a
    stray ``final --session`` date, a sealed or out-of-calendar date, a weekend or holiday, any other name) is
    ignored and listed, so it is never analyzed and cannot spoil the NOT SAMPLED list (safety S9)."""
    root = Path(root)
    days, ignored = [], []
    for p in sorted(root.iterdir()) if root.is_dir() else []:
        if not p.is_dir():
            continue
        try:
            d = dt.date.fromisoformat(p.name)
            why = None if p.name == d.isoformat() else "not a YYYY-MM-DD session date"
        except ValueError:
            d, why = None, "not a YYYY-MM-DD session date"
        if why is None and d <= SEALED_LAST:
            why = f"not after {SEALED_LAST}"
        elif why is None and not SB.CALENDAR_FIRST <= d <= SB.CALENDAR_LAST:
            why = f"outside the calendar carried by sample_bars.py ({SB.CALENDAR_FIRST}..{SB.CALENDAR_LAST})"
        elif why is None and not SB.is_session(d):
            why = "not an NYSE session"
        if why is None:
            days.append(p)
        else:
            ignored.append(dict(folder=p.name, reason=why))
    return days, ignored


ACCEPTANCE_FLIPS = ("changed", "disappeared", "appeared")     # a ticket's flips, either direction (spec 4 step 4)
ACCEPTANCE_MIN_NIGHTS = 6                                      # the owner, 2026-11-12: at least 6 compared nights ...
ACCEPTANCE_THROUGH = dt.date(2026, 11, 20)                     # ... through 11-20 (flips count on every night)
ACCEPTANCE_SKIPPED = ("MISSED-NIGHT", "NO-EVENING")            # no evening sample: not a sampled night


def acceptance(nights: list[dict]) -> dict:
    """The owner's acceptance bar (ruled 2026-11-12), per method: met only if every sampled night (LATE ones included;
    a MISSED-NIGHT or NO-EVENING night has no evening sample and is skipped) ran the ticket comparison and had zero
    ticket flips for that method (every k, breadth filter on and off: changed, disappeared or appeared only on final
    bars), and at least ACCEPTANCE_MIN_NIGHTS nights through ACCEPTANCE_THROUGH were compared. M1 and M2 are judged separately."""
    judged = [n for n in nights if n["state"] not in ACCEPTANCE_SKIPPED]
    through = [n for n in judged if dt.date.fromisoformat(n["session"]) <= ACCEPTANCE_THROUGH]
    unjudged = [n["session"] for n in judged if n["state"] not in ("OK", "LATE") or not (n["signals"] or {}).get("run")]
    out = {}
    for m in ("m1", "m2"):
        flips = {n["session"]: sum(n["tally"].get(f"{pre}_{m}_{k}_{x}", 0) for pre in ("tk", "tko")
                                   for k in PARAMS.stop_k for x in ACCEPTANCE_FLIPS) for n in judged}
        flip_nights = [s for s, v in flips.items() if v]
        if not judged:
            why = "no sampled night"
        elif flip_nights:
            why = f"ticket flips on {', '.join(flip_nights)}"
        elif unjudged:
            why = f"no ticket comparison on {', '.join(unjudged)}"
        elif len(through) < ACCEPTANCE_MIN_NIGHTS:
            why = (f"only {len(through)} compared night(s) through {ACCEPTANCE_THROUGH:%m-%d}; the bar needs at least "
                   f"{ACCEPTANCE_MIN_NIGHTS}")
        else:
            why = None
        out[m] = dict(met=why is None, nights=len(judged), flips=sum(flips.values()), flip_nights=flip_nights,
                      unjudged=unjudged, reason=why)
    return out


def build_report(root: Path, sessions: Optional[list[str]] = None, *, bars_only: bool = False,
                 include_late: bool = False, go_live: Optional[dt.date] = None, examples: int = 8) -> dict:
    """Analyze the chosen session folders (all of them by default) and pool the eligible nights. Folders that are
    not carried-calendar sessions after 2026-10-30 are ignored and listed (``night_folders``)."""
    root = Path(root)
    go_live = effective_go_live(go_live)
    days, ignored = night_folders(root)
    if sessions:
        wanted = set(sessions)
        ignored = [i for i in ignored if i["folder"] in wanted]
        missing = sorted(wanted - {d.name for d in days} - {i["folder"] for i in ignored})
        days = [d for d in days if d.name in wanted]
    else:
        missing = []
    nights = [analyze_night(d, bars_only=bars_only, go_live=go_live, examples=examples) for d in days]
    pooled_states = ("OK", "LATE") if include_late else ("OK",)
    contributing = [n for n in nights if n["state"] in pooled_states]
    pooled = pool(contributing)
    not_sampled = []
    if days:
        try:
            cal = SB.sessions_between(dt.date.fromisoformat(days[0].name), dt.date.fromisoformat(days[-1].name))
            have = {d.name for d in days}
            not_sampled = [d.isoformat() for d in cal if d.isoformat() not in have]
        except SB.CalendarError:
            not_sampled = ["(outside the calendar carried by sample_bars.py)"]
    sig = pooled["lists"].get("signals", [])
    deltas = {f: pooled["lists"].get(f"d_{f}", []) for f in FIELDS}
    estimates = flip_estimates(sig, deltas)
    return dict(meta=dict(root=str(root), generated=SB.iso(SB.now_et()), params_hash=params_hash(),
                          order_levels=ORDER_SOURCE, orders_ok=ORDERS is not None,
                          go_live=go_live.isoformat() if go_live else None,
                          go_live_actual=go_live_actual().isoformat() if go_live_actual() else None,
                          go_live_target=PARAMS.go_live_target, bars_only=bars_only,
                          include_late=include_late, pre_go_live_lookback_ruled=PRE_GO_LIVE_LOOKBACK_RULED,
                          requested_missing=missing, ignored=ignored),
                nights=nights, not_sampled=not_sampled, contributing=[n["session"] for n in contributing],
                pooled=pooled, estimates=estimates, acceptance=None if sessions else acceptance(nights))


# =========================================================================================================
# The printed report
# =========================================================================================================

def _pct(x: Optional[float], digits: int = 2) -> str:
    return "n/a" if x is None else f"{100 * x:.{digits}f}%"


def render(report: dict, examples: int = 8) -> str:
    out: list[str] = []
    w = out.append
    m = report["meta"]
    w("PHASE 2 FLIP MEASUREMENT  (read-only; no network)")
    w(f"root {m['root']}  |  params {m['params_hash']}  |  generated {m['generated']}")
    w(f"order levels: {m['order_levels']}" if m["orders_ok"] else
      f"order levels: NOT RUN: {m['order_levels']} (no local copy of the formulas: the whole-cent T, the levels, "
      f"the tickets, the fill path and the signal level are NOT RUN)")
    gl = (f"go-live {m['go_live']} (GO_LIVE_ACTUAL {m['go_live_actual']})" if m["go_live"] else
          f"go-live NOT RECORDED (GO_LIVE_ACTUAL unset; params.go_live_target {m['go_live_target']} is only a "
          f"target): every night is pre-go-live")
    ruled = ("pre-go-live look-back ruled: True (the owner's ruling of 2026-11-12, spec 3.7: sealed bars are read as "
             "look-back for sessions after 2026-10-30)" if m["pre_go_live_lookback_ruled"] is True else
             f"pre-go-live look-back ruled: {m['pre_go_live_lookback_ruled']} (pre-go-live nights get the bar level only)")
    w(f"look-back guard: {gl}; {ruled}" + ("  |  --bars-only" if m["bars_only"] else ""))
    if m["requested_missing"]:
        w(f"requested but not found: {', '.join(m['requested_missing'])}")
    if m.get("ignored"):
        w("IGNORED folders (a night is a carried-calendar session after 2026-10-30): "
          + ", ".join(f"{i['folder']} ({i['reason']})" for i in m["ignored"]))
    w("")
    w("NIGHTS")
    w(f"  {'session':10} {'tags':34} {'state':12} {'evening':13} {'final pulls':>11} {'universe':>8} {'compared':>8} "
      f"{'alrdy-final':>11} {'trunc':>5} {'not-final':>9} {'signal level'}")
    w(f"  {'':10} ('trunc' = names with a TRUNCATED response in any pull; 'not-final' = no FINAL row at all)")
    for n in report["nights"]:
        t = n["tally"]
        ev_t = (n["evening_first"] or "-")[11:16]
        sig = n["signals"]
        sig_s = "run" if sig and sig.get("run") else f"NOT RUN: {sig['reason'][:70]}" if sig else "-"
        w(f"  {n['session']:10} {', '.join(n['tags'])[:34]:34} {n['state']:12} {ev_t:13} {len(n['final_files']):>11} "
          f"{t.get('universe', 0):>8} {t.get('pairs', 0):>8} {t.get('ev_ALREADY_FINAL', 0):>11} "
          f"{n['names_count'].get('truncated_response', 0):>5} {t.get('fi_NOT_FINAL', 0):>9} {sig_s}")
        if n["late_reasons"]:
            w(f"  {'':10} LATE: {'; '.join(n['late_reasons'])}")
        for st in n["statuses"]:
            if st.get("state") in ("MISSED-NIGHT", "FAILED", "INCOMPLETE", "SKIPPED"):
                w(f"  {'':10} {st.get('mode')} run {st.get('state')}: {st.get('reason') or st.get('error') or ''}")
    if report["not_sampled"]:
        w(f"  NOT SAMPLED (calendar sessions without a folder): {', '.join(report['not_sampled'])}")
    w(f"  pooled below: {', '.join(report['contributing']) or 'none'}"
      + ("" if m["include_late"] else "  (LATE nights excluded; --include-late to pool them)"))
    w("")
    for n in report["nights"]:
        _render_night(n, w, examples)
    _render_pooled(report, w, examples)
    w("")
    w("ACCEPTANCE BAR (ruled 2026-11-12, spec 4 step 4: zero ticket flips on every sampled night, either direction; "
      "M1 and M2 judged separately; any flip keeps that method on recheck tickets)")
    if report.get("acceptance") is None:
        w("  not judged: the bar covers every sampled night, so it is printed only over all nights (--all)")
    for mkey, a in (report.get("acceptance") or {}).items():
        w(f"  {mkey.upper()} acceptance bar (ruled 2026-11-12): {'met' if a['met'] else 'not met'}  "
          f"({a['flips']} ticket flip(s) over {a['nights']} sampled night(s)"
          + (f"; {a['reason']}" if a["reason"] else "") + ")")
    return "\n".join(out)


def _render_night(n: dict, w, examples: int) -> None:
    t, names, cnt = n["tally"], n["names"], n["names_count"]
    w(f"=== {n['session']} ({', '.join(n['tags'])}) state {n['state']}; evening {n['evening_first'] or '-'} .. "
      f"{n['evening_last'] or '-'}; reference {n['reference'] or 'none (SPY not sampled)'}")
    if not t.get("universe"):
        w("  no evening sample (no candidates.json and no evening rows): nothing to compare")
        w("")
        return
    w("  classes  evening: " + ", ".join(f"{c} {t.get('ev_' + c, 0)}" for c in EV_CLASSES if t.get("ev_" + c))
      + "  |  final: " + ", ".join(f"{c} {t.get('fi_' + c, 0)}" for c in FI_CLASSES if t.get("fi_" + c)))
    pairs, pq = t.get("pairs", 0), t.get("pairs_with_quote_close", 0)
    t_moves = "NOT RUN (no usable orders.py)" if n.get("orders_unavailable") else t.get("trigger_moves", 0)
    w(f"  bar level on {pairs} pairs: open {t.get('diff_o', 0)}, high {t.get('diff_h', 0)}, low {t.get('diff_l', 0)}, "
      f"scan close {t.get('diff_c_scan', 0)} of {pq} (candle's own close {t.get('diff_c_candle', 0)}), volume "
      f"{t.get('diff_v', 0)}, whole-cent T {t_moves}")
    for key, label in (("already_final", "evening already final (excluded)"), ("evening_truncated", "evening TRUNCATED"),
                       ("final_truncated", "final TRUNCATED (no history)"), ("not_final_yet", "final NOT_FINAL (unconfirmed)"),
                       ("final_empty", "final EMPTY"), ("final_error", "final ERROR"), ("final_no_bar", "final NO_BAR"),
                       ("final_not_pulled", "never pulled overnight"), ("no_quote_close", "no quote close"),
                       ("basis_change", "basis change"),
                       ("truncated_response", "names with a TRUNCATED response (single candle, no history), any pull")):
        if cnt.get(key):
            w(f"  {label}: {cnt[key]}  {', '.join(names[key][:examples])}{' ...' if cnt[key] > examples else ''}")
    if t.get("final_from_earlier_pull") or t.get("final_revised_between_pulls"):
        w(f"  final record from an earlier pull than the latest: {t.get('final_from_earlier_pull', 0)}; "
          f"final candle revised between pulls: {t.get('final_revised_between_pulls', 0)}")
    for tl in n["timeline"]:
        gate = ("n/a (SPY not sampled)" if tl["gate_99"] is None else "PASS" if tl["gate_99"] else "fail")
        w(f"  pull {tl['file']} {(tl['first'] or '')[11:19]}..{(tl['last'] or '')[11:19]}: FINAL coverage "
          f"{_pct(tl['coverage'])}; 99% gate {gate} (names alone: {'pass' if tl['gate_99_names_only'] else 'fail'})"
          + (f"; {tl['unfinished']} unfinished {tl['unfinished_by_class']}" if tl["unfinished"] else ""))
        if (tl["gate_99"] or (tl["gate_99"] is None and tl["gate_99_names_only"])) and tl["unfinished"]:
            w(f"    !! a 99% gate passes here with {tl['unfinished']} names unfinished (they must read UNCONFIRMED, "
              f"never 'disappeared'): {', '.join(tl['unfinished_examples'])}")
    sig = n["signals"] or {}
    if sig.get("run"):
        b = sig["breadth"]
        for side in ("evening", "final"):
            x = b[side]
            w(f"  breadth B(t) {side:7}: {_pct(x['B'])} ({x['above']} of {x['eligible']} eligible above the 50-session "
              f"average), gate {'open' if x['gate_open'] else 'closed'}, {x['names_to_flip']} names from flipping it")
        w(f"  breadth gate flip: {b['gate_flip']}; names without a final bar: {b['missing_final']} -> final B between "
          f"{_pct(b['final_low'])} and {_pct(b['final_high'])} (gate robust: {b['final_gate_robust']})")
        if sig.get("spy_gap"):
            g = sig["spy_gap"]
            w(f"  SPY gap: evening {g['evening']:+.4%}, final {g['final']:+.4%}; < +1.0% test flips: {g['flip']}")
        else:
            w("  SPY gap: n/a (SPY not sampled, or no provisional and final pair)")
        w(f"  signal level: {t.get('sig_pairs', 0)} names evaluated ({t.get('sig_short_history', 0)} with too little "
          f"history for compute_levels); calendar from {sig['calendar_source']}")
        fl = sum(v for k, v in t.items() if k.startswith("fill_") and k.endswith(": changed"))
        w(f"  flips: eligible {t.get('elig_flip', 0)}, 50-session average {t.get('sma_flip', 0)}, knife "
          f"{t.get('knife_flip', 0)}; M1 signals {t.get('m1_flip', 0)} of {t.get('m1_either', 0)} (touch test "
          f"{t.get('m1_t_touch_flip', 0)}); M2 signals {t.get('m2_flip', 0)} of {t.get('m2_either', 0)} (test flips: gap "
          f"{t.get('m2_t_gap_flip', 0)}, volume {t.get('m2_t_volume_flip', 0)}, held {t.get('m2_t_held_flip', 0)}); "
          f"fill path: {fl} synthetic orders on {t.get('fill_names_changed', 0)} names")
    elif sig:
        w(f"  signal level NOT RUN: {sig.get('reason')}")
    w("")


def _render_pooled(report: dict, w, examples: int) -> None:
    pooled, nights = report["pooled"], [n for n in report["nights"] if n["session"] in report["contributing"]]
    t, L = pooled["tally"], pooled["lists"]
    k = len(nights)
    w(f"POOLED over {k} night(s): {sum(n['tally'].get('pairs', 0) for n in nights)} name-nights compared")
    if not k:
        w("  nothing to pool")
        return
    w("  BAR LEVEL  (field differences, provisional evening vs final; per-night min / median / max; night-clustered 95% CI)")
    for key, label, den in (("diff_o", "open", "pairs"), ("diff_h", "high", "pairs"), ("diff_l", "low", "pairs"),
                            ("diff_c_candle", "close (candle's own)", "pairs"),
                            ("diff_c_scan", "close (scan = quote official close)", "pairs_with_quote_close"),
                            ("diff_v", "volume", "pairs"), ("diff_any_price", "any of O/H/L/scan close", "pairs_with_quote_close"),
                            ("trigger_moves", "whole-cent trigger T", "pairs")):
        if key == "trigger_moves" and not report["meta"]["orders_ok"]:
            w(f"    {label:38} NOT RUN: {report['meta']['order_levels']}")
            continue
        xs = [n["tally"].get(key, 0) for n in nights]
        ns = [n["tally"].get(den, 0) for n in nights]
        per = sorted(x / m for x, m in zip(xs, ns) if m)
        ci = clustered_ci(xs, ns)
        mid = per[len(per) // 2] if per else None
        w(f"    {label:38} {rate(sum(xs), sum(ns)):48} nights {_pct(per[0] if per else None)} / {_pct(mid)} / "
          f"{_pct(per[-1] if per else None)}  CI {('n/a (1 night)' if ci is None else f'{_pct(ci[0])}..{_pct(ci[1])}')}")
    nights_any = sum(1 for n in nights if n["tally"].get("diff_any_price", 0))
    w(f"    nights with any price-field difference: {rate(nights_any, k)}")
    q = quantiles(abs(x) for x in L.get("open_delta_pct", []))
    w(f"    open differences: up {t.get('open_up', 0)}, down {t.get('open_down', 0)}; |delta open| % of price "
      + (f"median {q['p50']:.3f}%, p95 {q['p95']:.3f}%, max {q['max']:.3f}%" if q else "none"))
    qa = quantiles(L.get("open_delta_atr", []))
    if qa:
        w(f"    |delta open| in ATR(t-1) units (signal-level nights): median {qa['p50']:.3f}, p95 {qa['p95']:.3f}, max {qa['max']:.3f}")
    vr = quantiles(L.get("vol_ratio", []))
    if vr:
        w(f"    volume final/evening: median {vr['p50']:.5f}, p5 {vr['p5']:.5f}, p95 {vr['p95']:.5f}, min {vr['min']:.4f}, "
          f"max {vr['max']:.4f}; up {t.get('vol_up', 0)}, down {t.get('vol_down', 0)}, same {t.get('vol_same', 0)}")
    w(f"    quote openPrice equals the provisional open: {t.get('quote_open_equal', 0)} of {t.get('quote_open_compared', 0)}")
    w(f"    M2-like stratum (quote fields: |gap| >= 2%, volume >= 2 x avg10): open differs {rate(t.get('m2like_q_open_diff', 0), t.get('m2like_q_n', 0))}")
    w(f"    basis changes in t-1..t-4: {t.get('basis_change', 0)}; volume-only revisions of those bars: "
      f"{t.get('prior_volume_revised', 0)}; unchecked: {t.get('basis_unchecked', 0)}")
    for key, label in (("x_open", "open differences"), ("x_trigger", "trigger moves")):
        if L.get(key):
            w(f"    e.g. {label}: {'; '.join(L[key][:examples])}")
    sig_nights = [n for n in nights if (n["signals"] or {}).get("run")]
    w("")
    if not sig_nights:
        reasons = sorted({(n["signals"] or {}).get("reason", "-") for n in nights})
        w("  SIGNAL LEVEL: not run on any pooled night: " + " | ".join(r[:160] for r in reasons))
        if not report["meta"]["orders_ok"]:
            why = report["meta"]["order_levels"]
            w(f"    order levels T/C/S/P/N: NOT RUN: {why}")
            w(f"    tickets (breadth on): NOT RUN: {why}")
            w(f"    day-t fill path (synthetic brackets): NOT RUN: {why}")
        return
    w(f"  SIGNAL LEVEL  ({len(sig_nights)} night(s), {t.get('sig_pairs', 0)} name-nights; both ways = evening scan bar vs final bar)")
    w(f"    eligible(t) flips: {rate(t.get('elig_flip', 0), t.get('sig_pairs', 0))}  (eligible on final bars {t.get('elig_fin', 0)})")
    w(f"    close vs 50-session average flips: {rate(t.get('sma_flip', 0), t.get('sma_n', 0))}")
    w(f"    breadth gate flips: {rate(t.get('breadth_gate_flip', 0), t.get('breadth_nights', 0))} nights")
    for label, mkey, tests in (("M1", "m1", M1_TESTS), ("M2 (bar tests, no event filter)", "m2", M2_TESTS)):
        either = t.get(f"{mkey}_either", 0)
        w(f"    {label}: signals evening {t.get(f'{mkey}_eve', 0)}, final {t.get(f'{mkey}_fin', 0)}, both {t.get(f'{mkey}_both', 0)}; "
          f"signal flips {rate(t.get(f'{mkey}_flip', 0), either)} of signals")
        w("      test flips per name-night: " + "; ".join(
            f"{x} {t.get(f'{mkey}_t_{x}_flip', 0)} of {t.get(f'{mkey}_n', 0)} (pass on final {t.get(f'{mkey}_t_{x}_pass_fin', 0)})"
            for x in tests))
        if L.get(f"x_{mkey}"):
            w(f"      e.g. {'; '.join(L[f'x_{mkey}'][:examples])}")
    w(f"    falling-knife flag flips: {rate(t.get('knife_flip', 0), t.get('knife_n', 0))}")
    w(f"    SPY gap test (< +1.0%) flips: {rate(t.get('spy_gap_flip', 0), t.get('spy_nights', 0))} nights")
    w(f"    M2-like stratum (bars: |gap| >= 2%, volume >= 2 x ADV30): open differs {rate(t.get('m2like_b_open_diff', 0), t.get('m2like_b_n', 0))}")
    w(f"    names within the night's largest volume revisions of the 3.0x line: {t.get('volume_reach', 0)}")
    w("    order levels T/C/S/P/N per signal (confirmed / changed / disappeared / appeared):")
    for mkey in ("m1", "m2"):
        for kk in PARAMS.stop_k:
            key = f"lv_{mkey}_{kk}"
            c = [t.get(f"{key}_{x}", 0) for x in ("confirmed", "changed", "disappeared", "appeared")]
            fields = ", ".join(f"{f} {t[f'{key}_field_{f}']}" for f in ("T", "C", "S", "P", "N") if t.get(f"{key}_field_{f}"))
            tk = [t.get(f"tk_{mkey}_{kk}_{x}", 0) for x in ("confirmed", "changed", "disappeared", "appeared")]
            w(f"      {mkey.upper()} k={kk}: {c[0]} / {c[1]} / {c[2]} / {c[3]}"
              + (f"  (fields: {fields})" if fields else "") + f";  tickets, breadth on: {tk[0]} / {tk[1]} / {tk[2]} / {tk[3]}")
    if L.get("x_levels"):
        w(f"      e.g. {'; '.join(L['x_levels'][:examples])}")
    w(f"    day-t fill path (fills.step, synthetic orders at -0.5..+0.5 ATR(t-1) around the final open; "
      f"{t.get('fill_names', 0)} names, {t.get('fill_identical_bars', 0)} with identical O/H/L/C):")
    for fam in ("pending", "open, stop near the open", "open, target near the open"):
        w(f"      {fam:28} changed {rate(t.get(f'fill_{fam}: changed', 0), t.get(f'fill_{fam}: orders', 0))}")
    kinds = {k[len('fillkind_'):]: v for k, v in t.items() if k.startswith("fillkind_")}
    if kinds:
        w("      by kind: " + "; ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    w(f"      names with any fill-path change: {rate(t.get('fill_names_changed', 0), t.get('fill_names', 0))}")
    if L.get("x_fill"):
        w(f"      e.g. {'; '.join(L['x_fill'][:examples])}")
    est = report["estimates"]
    _render_evidence(report, nights, t, w)
    if est:
        w(f"    margin-based estimate ({len(est)} signal-sides; deltas pooled over {t.get('delta_n', 0)} name-nights, "
          f"ATR(t-1) units, volume as a log ratio):")
        w(f"      expected flips: {sum(e['p'] for e in est):.3f}; with every component at its 95% upper bound: "
          f"{sum(e['upper'] for e in est):.2f}")
        for e in sorted(est, key=lambda e: -e["upper"])[:examples]:
            tg = e["tightest"]
            w(f"      {e['night']} {e['sym']:6} {e['method']} {e['side']:7} P(flip) {e['p']:.4f} (upper {e['upper']:.3f})"
              + (f"; tightest {tg['test']} margin {tg['margin']:.3f} ({tg['x']} of {tg['n']} deltas beyond it)" if tg else "")
              + ("  FLIPPED" if e["flipped"] else ""))


def _render_evidence(report: dict, nights: list[dict], t: dict, w) -> None:
    """What the pooled nights can and cannot rule out, with exact one-sided 95% bounds."""
    sig_nights = [n for n in nights if (n["signals"] or {}).get("run")]
    tags = Counter(tag for n in nights for tag in n["tags"])
    flip_nights = sum(1 for n in sig_nights if n["tally"].get("m1_flip", 0) or n["tally"].get("m2_flip", 0)
                      or n["tally"].get("breadth_gate_flip", 0))
    w("    EVIDENCE SO FAR (one-sided 95% upper bounds; the owner's bar is applied under ACCEPTANCE BAR):")
    w(f"      nights pooled {len(nights)} (signal level on {len(sig_nights)}); Fridays {tags.get('Fri', 0)}, half days "
      f"{tags.get('half day 13:00', 0)}, expirations {tags.get('monthly expiration', 0) + tags.get('quarterly expiration', 0)}")
    w(f"      nights with an M1, M2 or breadth flip: {rate(flip_nights, len(sig_nights))}")
    for m in ("m1", "m2"):
        w(f"      {m.upper()} signals that flip: {rate(t.get(f'{m}_flip', 0), t.get(f'{m}_either', 0))}")
    w(f"      M2-like name-nights (bars): {t.get('m2like_b_n', 0)}, open differs {rate(t.get('m2like_b_open_diff', 0), t.get('m2like_b_n', 0))}"
      " (review's suggestion: about 200, about 5 earnings-season nights)")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 2 flip measurement: provisional vs final bars, every sampled night")
    ap.add_argument("sessions", nargs="*", help="session dates (YYYY-MM-DD); default with --all: every folder")
    ap.add_argument("--all", action="store_true", help="every session folder under the root")
    ap.add_argument("--root", default=str(SB.OUT))
    ap.add_argument("--bars-only", action="store_true", help="bar level only (reads no look-back bars)")
    ap.add_argument("--include-late", action="store_true", help="pool LATE nights too")
    ap.add_argument("--go-live", help="a go-live date LATER than GO_LIVE_ACTUAL (tightens the guard only; refused "
                                      "while GO_LIVE_ACTUAL is unset)")
    ap.add_argument("--json", help="also write the full report to this path")
    ap.add_argument("--examples", type=int, default=8)
    a = ap.parse_args(argv)
    if not a.all and not a.sessions:
        ap.print_usage()
        print("give session dates or --all")
        return 2
    actual, go_live = go_live_actual(), None
    if a.go_live:
        go_live = dt.date.fromisoformat(a.go_live)
        if actual is None:
            print(f"--go-live {go_live} refused: go-live is not recorded (GO_LIVE_ACTUAL is unset in compare_bars.py), "
                  f"so every night is pre-go-live; params.go_live_target {PARAMS.go_live_target} is only a target. "
                  f"Recording go-live is a reviewed edit of GO_LIVE_ACTUAL, never a flag")
            return 2
        if go_live < actual:
            print(f"--go-live {go_live} is earlier than GO_LIVE_ACTUAL {actual}: refused (the option only tightens "
                  f"the guard; the owner's ruling on pre-go-live look-back, 2026-11-12, spec 3.7, is the "
                  f"PRE_GO_LIVE_LOOKBACK_RULED constant)")
            return 2
    report = build_report(Path(a.root), None if a.all else a.sessions, bars_only=a.bars_only,
                          include_late=a.include_late, go_live=go_live, examples=a.examples)
    print(render(report, a.examples))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(report, fh, indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
