"""Phase 2 order construction, paper sizing and ticket lines (spec 3.2, 3.4 "Order", section 4 "Paper book").

PURE: no network, no clock, no file I/O. Nothing here can place, change or cancel an order: it computes the
levels and prints the text the owner types into paperMoney. Every number comes from ``params`` (no spec number
is typed in this file), prices are exact Decimals, and a result depends only on the arguments: the arithmetic
runs in this module's own decimal context, so the caller's decimal settings cannot move a cent.

The rules, each rounded in the conservative direction (spec 3.4: "cents; rounding always conservative"):

    T = high(t) + 0.01, rounded UP to the cent         trigger_from_high   params.trigger_offset
    C = floor(T + 0.25 x ATR)                          build_bracket       params.ceiling_atr
    S = floor(min(S0, T - k x ATR)), k in stop_k       build_bracket       params.stop_k
    P = ceil(T + 3 x (T - S))                          build_bracket       params.target_r
    N = floor(min($15 / (C - S), $262.50 / C))         paper_shares        params.basis x risk_pct,
        sized on the CEILING; under 3 it is unsizable                      basis x position_cap_pct, min_shares

T up keeps the buy stop at least a cent above the high; C and S round down, P up, N down.

RULED 2026-11-12 (spec 3.4): "T is rounded up to the cent." The spec had given T = high(t) + 0.01 but not the
direction a sub-cent T rounds, and about one final daily high in four is not a whole cent (23.7% of the final
candles of the eight sessions 2026-11-02..11-11; spec 3.4). The owner's ruling of 2026-11-12 made the rounding
the rule, so ``trigger_from_high`` is the rule.

Price resolution: every number is read at the nearest millionth of a dollar, the resolution fills.py compares
prices at. That removes binary-float noise (64.12 + 0.01 is 64.13000000000001 as a float and is read as
64.13), and the ticket and the fill model read the same price. Today's inputs are exact at that resolution:
compute_levels rounds ATR to 4 places, M1's structural stop is whole cents and M2's (low - 0.2 ATR) has at most
6 places. A few split-adjusted Schwab bars carry genuine digits beyond the sixth; such an input is read at its
nearest millionth, the resolution fills.py compares at (at an exact half-millionth tie the two can differ by
one millionth: fills.py rounds a float product), so a level that lies within half a millionth of a cent
boundary rounds from that millionth (review note 7).

Who calls what:
  * signals.py (backtest, forward tracker and P5's random entries) builds T with trigger_from_high, passes
    float(T) to compute_levels as ``last``, builds the bracket with build_bracket, and gives fills.py an Order
    made with ``Bracket.for_fills()``, so the tracker runs exactly the levels the ticket carries ("what is
    paper-traded is what is tested").
  * The nightly ticket writer prints ticket_lines and sizing_lines. The PAPERMONEY header, deployment, cash,
    positions and the 2nd-in-sector flag need the ledger and belong to the writer, not here.
  * The 2026-11-11 drill ticket was built by its own copy of this arithmetic (same levels on every realistic
    input). A later drill should call build_bracket(T, atr, 1.5, params, structural_stop=ATR_ONLY) and
    paper_shares instead (review finding 5).
"""

from __future__ import annotations

import functools
import math
import re
from dataclasses import dataclass
from decimal import (ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Context, Decimal, DecimalException,
                     DivisionByZero, Inexact, InvalidOperation, Overflow, localcontext)
from typing import Union

from .params import Params

Number = Union[int, float, Decimal]

CENT = Decimal("0.01")              # every level on a ticket is a whole cent
MILLIONTH = Decimal("0.000001")     # every input is read at this resolution, fills.py's

# Sums, differences and products must be exact (Inexact is trapped). Only the named rounding steps round:
# _floor_cent, _ceil_cent and the millionth read in _read, each in its stated direction.
_EXACT = Context(prec=60, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation, DivisionByZero, Overflow, Inexact])
_ROUNDING = Context(prec=60, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation, DivisionByZero, Overflow])

_SYMBOL = re.compile(r"[A-Z][A-Z0-9./-]*")     # BAC, BRK.B: upper case, no spaces


class _AtrStopOnly:
    """The type of ATR_ONLY, a marker compared by identity."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "ATR_ONLY"

    def __reduce__(self):
        return "ATR_ONLY"          # copy, deepcopy and pickle return the module's one marker


ATR_ONLY = _AtrStopOnly()    # structural_stop=ATR_ONLY: no structural stop, S = floor(T - k x ATR) (the drill)


# --- reading numbers ----------------------------------------------------------------------------------------

def _exact(fn):
    """Run ``fn`` in the module's exact decimal context; a number too large to hold exactly is a ValueError."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            with localcontext(_EXACT):
                return fn(*args, **kwargs)
        except DecimalException as exc:
            raise ValueError(f"{fn.__name__}: a number is too large to hold exactly to the millionth "
                             f"({type(exc).__name__})") from exc

    return wrapper


def _read(x: Number, name: str) -> Decimal:
    """``x`` at the nearest millionth, as an exact Decimal: the exact value of the int, float or Decimal,
    correctly rounded, a tie going to the even millionth (as Python's round() does). For a float that removes
    its binary noise: 64.13000000000001 is read as 64.130000. A bool, a string or None is refused (TypeError),
    and so is a NaN or an infinity (ValueError)."""
    if isinstance(x, bool) or not isinstance(x, (int, float, Decimal)):
        raise TypeError(f"{name} must be an int, float or Decimal, not {type(x).__name__}: {x!r}")
    if (isinstance(x, float) and not math.isfinite(x)) or (isinstance(x, Decimal) and not x.is_finite()):
        raise ValueError(f"{name} must be a finite number: {x!r}")
    return Decimal(x).quantize(MILLIONTH, rounding=ROUND_HALF_EVEN, context=_ROUNDING)


def _positive(x: Number, name: str) -> Decimal:
    d = _read(x, name)
    if d <= 0:
        raise ValueError(f"{name} must be positive: {x!r}")
    return d


def _floor_cent(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_FLOOR, context=_ROUNDING)


def _ceil_cent(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_CEILING, context=_ROUNDING)


def _money(x: Decimal) -> Decimal:
    """A dollar amount in two places when it is whole cents (15.000000000000 -> 15.00); otherwise exact."""
    cents = _floor_cent(x)
    return cents if cents == x else x


def _check_params(params: Params) -> None:
    if not isinstance(params, Params):
        raise TypeError(f"params must be a phase2 Params, not {type(params).__name__}")


# --- records ------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Bracket:
    """One order's four levels: Decimals in whole cents with exactly two places, and 0 < S < T <= C < P (the
    ordering fills.Order enforces). A Bracket that breaks either rule cannot be made, so every Bracket prints
    and records as two-place cents (20.00, never 20.0 or 2E+1)."""

    trigger: Decimal     # T: the buy stop
    ceiling: Decimal     # C: the buy limit
    stop: Decimal        # S: the sell stop
    target: Decimal      # P: the sell limit

    def __post_init__(self) -> None:
        places = CENT.as_tuple().exponent
        for name in ("trigger", "ceiling", "stop", "target"):
            v = getattr(self, name)
            if not isinstance(v, Decimal):
                raise TypeError(f"{name} must be a Decimal, not {type(v).__name__}: {v!r}")
            if not (v.is_finite() and v.as_tuple().exponent == places):
                raise ValueError(f"{name} must be whole cents with two places, e.g. Decimal('20.00'): {v!r}")
        if not (0 < self.stop < self.trigger <= self.ceiling < self.target):
            raise ValueError(f"levels must satisfy 0 < S < T <= C < P: S {self.stop}, T {self.trigger}, "
                             f"C {self.ceiling}, P {self.target}")

    def __iter__(self):
        return iter((self.trigger, self.ceiling, self.stop, self.target))

    @property
    def planned_risk(self) -> Decimal:
        """T - S, the risk per share that R is measured against (spec 3.4, 3.5)."""
        return _EXACT.subtract(self.trigger, self.stop)

    def for_fills(self) -> dict[str, float]:
        """The levels as floats under fills.Order's field names: ``Order(..., **bracket.for_fills(), ...)``.
        fills.py reads prices at the millionth, so the Order carries exactly these cents."""
        return {"trigger": float(self.trigger), "ceiling": float(self.ceiling), "stop": float(self.stop),
                "target": float(self.target)}


@dataclass(frozen=True)
class Sizing:
    """The $1,500-basis share count of one bracket, sized on its ceiling (``paper_shares``)."""

    bracket: Bracket
    basis: Decimal             # $1,500
    risk_budget: Decimal       # basis x risk_pct: $15
    cap: Decimal               # basis x position_cap_pct: $262.50
    risk_per_share: Decimal    # C - S: the risk of one share bought at the ceiling
    risk_limit: Decimal        # risk_budget / (C - S), in shares, cut to the hundredth (never rounded up)
    cap_limit: Decimal         # cap / C, in shares, cut to the hundredth (never rounded up)
    shares: int                # N = floor(min(risk_budget / (C - S), cap / C))
    min_shares: int            # 3
    sizable: bool              # N >= min_shares; otherwise the signal is skipped and logged as unsizable
    cost_at_ceiling: Decimal   # N x C, never above the cap
    risk_at_ceiling: Decimal   # N x (C - S), never above the risk budget


# --- the rules ----------------------------------------------------------------------------------------------

@_exact
def trigger_from_high(high: Number, params: Params) -> Decimal:
    """T for a signal day: the day's high plus ``params.trigger_offset`` ($0.01), rounded UP to the cent.

    Spec 3.2: "a buy stop 1 cent above the signal day's high"; 3.4: "trigger T = high(t) + 0.01".
    Ruled 2026-11-12 (spec 3.4): "T is rounded up to the cent." Up is the
    conservative direction for a buy stop: T is never less than a cent above the high, and less than two:
    at the millionth, high + 0.01 <= T < high + 0.02. A whole-cent high gives exactly high + 0.01 (64.12 -> 64.13); a sub-cent
    one rounds up (49.183 -> 49.20, 41.315 -> 41.33).

    The high is read at the millionth, which removes binary-float noise first, so a float a hair above a cent
    (49.190000000000005) is that cent. Returns a two-place Decimal, the T that compute_levels (as ``last``),
    build_bracket, the fill model and the ticket all carry.
    """
    _check_params(params)
    high = _positive(high, "high")
    offset = _positive(params.trigger_offset, "params.trigger_offset")
    return _ceil_cent(high + offset)


@_exact
def build_bracket(trigger: Number, atr: Number, k: Number, params: Params, *, structural_stop) -> Bracket:
    """The bracket for trigger T (spec 3.4): C = floor(T + 0.25 ATR), S = floor(min(S0, T - k ATR)),
    P = ceil(T + 3 (T - S)).

    ``trigger`` must already be a positive whole-cent price; build it with ``trigger_from_high`` (a sub-cent T
    is refused, never rounded here). It is stored as two-place cents: 50.850 -> 50.85, 5E+1 -> 50.00.
    ``atr`` is ATR14 at the signal close as compute_levels gives it, and must be positive.
    ``k`` must be one of ``params.stop_k`` (spec 3.6: 1.0, 1.5, 2.0). P5's random entries, whose stop is the
    real trade's ATR multiple, pass that stop as structural_stop with the variant's k (it is never above
    T - k ATR, so it is the stop that results).
    ``structural_stop`` is S0, keyword-only and required: M1's L.suggested_stop, M2's low(t) - 0.2 ATR, or
    ATR_ONLY for the ATR stop alone (the drill). It must be below T. None is refused, so a stop that failed to
    compute cannot silently tighten the order and enlarge N (review finding 4).

    Raises ValueError for a bracket that cannot be traded, such as a stop at or below zero.
    """
    _check_params(params)
    t = _positive(trigger, "trigger")
    if t != _floor_cent(t):
        raise ValueError(f"the trigger must be a whole-cent price; build it with trigger_from_high: {trigger!r}")
    t = _floor_cent(t)
    a = _positive(atr, "atr")
    k_ = _read(k, "k")
    if k_ not in [_positive(v, "params.stop_k") for v in params.stop_k]:
        raise ValueError(f"k must be one of the stop widths in params.stop_k {params.stop_k}: {k!r}")
    s_atr = t - k_ * a
    if structural_stop is ATR_ONLY:
        s0 = s_atr
    elif structural_stop is None:
        raise TypeError("structural_stop is required: the method's stop S0, or orders.ATR_ONLY for the ATR stop "
                        "alone (None is refused, so a missing stop cannot tighten the order)")
    else:
        s0 = _read(structural_stop, "structural_stop")
        if s0 >= t:
            raise ValueError(f"the structural stop must be below the trigger {t}: {structural_stop!r}")
        s0 = min(s0, s_atr)
    c = _floor_cent(t + _read(params.ceiling_atr, "params.ceiling_atr") * a)
    s = _floor_cent(s0)
    p = _ceil_cent(t + _read(params.target_r, "params.target_r") * (t - s))
    return Bracket(t, c, s, p)


@_exact
def paper_shares(bracket: Bracket, params: Params) -> Sizing:
    """N = floor(min(basis x risk_pct / (C - S), basis x position_cap_pct / C)) on the fixed basis: with the
    spec's numbers floor(min($15 / (C - S), $262.50 / C)). At least ``params.min_shares`` (3) or unsizable.

    Sized on the CEILING, never the trigger (trading-rules Phase 2: "sized on the ceiling price"): the entry
    can fill anywhere up to C, so N keeps both limits at C, and N + 1 would break one of them. Both counts are
    exact integer parts, so a whole-number quotient (262.50 / 26.25 = 10) is not cut to 9 and a quotient a
    hair below a whole number is never rounded up. Under the spec's numbers a bracket is unsizable exactly
    when C > $87.50 or C - S > $5.00 (spec 4).
    """
    _check_params(params)
    if not isinstance(bracket, Bracket):
        raise TypeError(f"paper_shares needs a Bracket (build_bracket makes one), not {type(bracket).__name__}")
    basis = _money(_positive(params.basis, "params.basis"))
    risk_budget = _money(basis * _positive(params.risk_pct, "params.risk_pct"))
    cap = _money(basis * _positive(params.position_cap_pct, "params.position_cap_pct"))
    min_shares = params.min_shares
    if isinstance(min_shares, bool) or not isinstance(min_shares, int) or min_shares < 1:
        raise ValueError(f"params.min_shares must be a positive whole number: {min_shares!r}")
    c = bracket.ceiling
    risk = c - bracket.stop                         # positive: a Bracket has S < T <= C
    n = int(min(risk_budget // risk, cap // c))     # exact integer parts of the two limits
    return Sizing(bracket=bracket, basis=basis, risk_budget=risk_budget, cap=cap, risk_per_share=risk,
                  risk_limit=(risk_budget // (risk * CENT)) * CENT, cap_limit=(cap // (c * CENT)) * CENT,
                  shares=n, min_shares=min_shares, sizable=n >= min_shares,
                  cost_at_ceiling=n * c, risk_at_ceiling=n * risk)


@_exact
def ticket_lines(symbol: str, bracket: Bracket, params: Params) -> list[str]:
    """The order exactly as it is entered in thinkorswim (spec section 4):

        BUY +N SYM STP <T> LMT <C> GTC  (trigger: STD)
           1st trgs OCO:  SELL -N SYM LMT <P> GTC  /  SELL -N SYM STP <S> GTC  (trigger: STD)

    N is not an argument: it is paper_shares' count for this bracket, so a ticket cannot carry any other
    quantity (8-check item 1 fails any other, the platform's 100-share default included). An unsizable bracket
    gets no ticket (ValueError; spec 4: it is skipped and logged as unsizable). Every price prints with exactly
    two decimals. The symbol must be an upper-case ticker with no spaces.

    The format marks the trigger method (STD) on both stops, the buy stop and the sell stop, as spec 4 prints
    it: ruled 2026-11-12, 8-check item 5 also scores STD on the sell stop (spec 5), since the model stops out
    on low <= S.
    """
    if not isinstance(symbol, str):
        raise TypeError(f"the symbol must be a str, not {type(symbol).__name__}: {symbol!r}")
    if not _SYMBOL.fullmatch(symbol):
        raise ValueError(f"the symbol must be an upper-case ticker such as 'BAC' or 'BRK.B': {symbol!r}")
    z = paper_shares(bracket, params)
    if not z.sizable:
        raise ValueError(f"{symbol}: {z.shares} shares is under the {z.min_shares}-share minimum; an unsizable "
                         "signal gets no ticket")
    n, b = z.shares, bracket
    return [f"BUY +{n} {symbol} STP {b.trigger:.2f} LMT {b.ceiling:.2f} GTC  (trigger: STD)",
            f"   1st trgs OCO:  SELL -{n} {symbol} LMT {b.target:.2f} GTC  /  "
            f"SELL -{n} {symbol} STP {b.stop:.2f} GTC  (trigger: STD)"]


@_exact
def sizing_lines(bracket: Bracket, params: Params) -> list[str]:
    """The sizing math a ticket shows (spec 4: "It shows the sizing math"). The format is this function's,
    ruled 2026-11-12 (the spec fixes no format of its own).

    The two limits print cut to the hundredth, never rounded up, so N is visibly floor(min) of the printed
    numbers: 262.50 / 16.41 = 15.996 prints 15.99 above N = 15, not 16.00 (review finding 6).
    """
    z = paper_shares(bracket, params)
    b = bracket
    if z.sizable:
        verdict = (f"risk at C ${z.risk_at_ceiling:,.2f} (limit ${z.risk_budget:,.2f}), "
                   f"cost at C ${z.cost_at_ceiling:,.2f} (cap ${z.cap:,.2f})")
    else:
        verdict = f"under the {z.min_shares}-share minimum: unsizable, skipped and logged, no ticket"
    return [f"Sizing on the ${z.basis:,.2f} basis, at the ceiling: C {b.ceiling:.2f}, S {b.stop:.2f}, "
            f"C - S {z.risk_per_share:.2f} a share",
            f"  risk limit  ${z.risk_budget:,.2f} / {z.risk_per_share:.2f} = {z.risk_limit:.2f} shares",
            f"  cap limit   ${z.cap:,.2f} / {b.ceiling:.2f} = {z.cap_limit:.2f} shares",
            f"  N = floor(min({z.risk_limit:.2f}, {z.cap_limit:.2f})) = {z.shares} shares: {verdict}"]
