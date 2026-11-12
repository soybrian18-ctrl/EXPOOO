"""Phase 2 fill model: the order state machine of spec sections 3.4 and 3.5.

PURE: no network, no clock, no file I/O. One implementation, three callers --
the backtester, the nightly forward tracker and the portfolio simulations -- so
a forward trade is judged by exactly the rules the backtest used.

An order is a buy stop-limit (trigger T, ceiling C) with a first-triggers-OCO
bracket (stop S, target P). ``step`` advances it one session on one daily bar.
Daily bars cannot order intraday events, so every unknowable ordering is
resolved against the trade:

  * stop and target in one bar            -> the stop wins;
  * low <= S on an intraday-trigger entry -> assumed to come after the fill;
  * a gap through the stop                -> filled at the open, not at S;
  * a gap past the target                 -> filled at P, no gap bonus;
  * resting limits (C, P)                 -> need a 1-cent trade-through, at
    the open as well as intraday;
  * a target on the fill-at-C path        -> credited only if the CLOSE is
    through P (the high may have printed before the fill).

Costs (spec 3.4, ruling 2026-11-11), in half-spreads h = max(tier x price, $0.005):
  * intraday trigger entries, fills at C and at P, and marks   -> h;
  * opening fills (gap-up entries, time exits)                 -> 2h;
  * every stop exit, intraday or gap-through                   -> 4h.
There is no separate slippage term: "at the open" holds literally. The "costs
x 2" row (``cost_mult``) doubles every one of these.

Caller contract:
  * Sessions are consumed once, in calendar order. ``step`` refuses a session
    at or before the order's latest one. A re-run never replays a session: it
    rebuilds the order from its signal day with ``run``. That is what makes the
    nightly tracker idempotent, and it is how a bar that arrived late, or a
    recomputed breadth figure, gets applied.
  * Pass EVERY session of the calendar, with ``bar=None`` where the symbol has
    no bar. Looping over a symbol's bars instead would stretch the entry window
    and the 40-session hold.
  * ``breadth_ok`` and ``params`` have no defaults: a forgotten argument is an
    error, never a silently unfiltered or base-cost number.

OOS seal (spec 3.7 step 2): ``step`` refuses every session inside the sealed
out-of-sample window (``params.oos_start`` .. ``params.oos_end``) unless the
caller names an unseal. There are two, and a contract test pins where each may
appear:
  * ``UNSEALED_BY_PICK``    -- passed only by the backtest runner, after it has
    verified the committed pick.json;
  * ``KNOWN_ANSWER_REPLAY`` -- the one exemption, and a narrow one: it lets
    through only exact replays of the experiment's own 14 real fill records
    (known_answer.py lists what "exact" means) on the sessions those trades
    need, entry day through exit day. Any other order or session inside the
    window is refused under it too.
The marking functions (evaluate_at_cutoff, close_at_mark) check the seal on
the cutoff session the same way.

Details the spec leaves to the implementation (each is pinned by a unit test):
  * A missing bar is a session with no fill and no exit. It still counts toward
    the entry window and toward the 40-session hold; a time exit that lands on
    a missing bar happens at the next bar's open, OCO rules first. If no bar
    ever arrives the trade stays open, and a cutoff marks it at its latest
    close like any other open trade.
  * An open at P, or less than a cent above it, is not a gap past the target
    (ruling 2026-11-11). On session 41 such an open is sold by the time exit,
    so a time exit can print up to a fraction of a cent above P before costs;
    net of its 2h it is below P.
  * The crash-bar bound applies only where the spec's condition holds
    literally: open > S and low < S - 1 ATR.
  * When two cancel causes fall on one close, the recorded reason is the first
    of: triggered-unfilled, invalidated, breadth, window expiry.
  * Prices are compared in millionths of a dollar (Schwab bars carry up to six
    decimals), so every boundary test is exact.

Levels (T, C, S, P) are built by signals.py; this module only executes them.
"""

from __future__ import annotations

import datetime as dt
import functools
import math
from dataclasses import dataclass, replace
from typing import Iterable, NamedTuple, Optional

from .known_answer import RECORDS as _KNOWN_ANSWER_RECORDS
from .known_answer import REPLAY_TARGET_MULT as _REPLAY_TARGET_MULT
from .params import Params

# --- states -----------------------------------------------------------------
PENDING, OPEN, CLOSED, CANCELED, EXPIRED = "PENDING", "OPEN", "CLOSED", "CANCELED", "EXPIRED"
TERMINAL = frozenset({CLOSED, CANCELED, EXPIRED})

# --- how an entry filled ----------------------------------------------------
ENTRY_OPEN = "open"            # T <= open <= C: filled at the open
ENTRY_TRIGGER = "trigger"      # open < T <= high: filled at T
ENTRY_CEILING = "ceiling"      # open > C, low traded through C: filled at C

# --- how a trade exited -----------------------------------------------------
EXIT_STOP = "stop"             # intraday, at S
EXIT_GAP_STOP = "gap_stop"     # open <= S: at the open
EXIT_TARGET = "target"         # at P
EXIT_TIME = "time"             # open of session 41
EXIT_MARK = "mark"             # still open at a cutoff: marked at that close

# --- why a pending order died ----------------------------------------------
CANCEL_TRIGGERED_UNFILLED = "triggered_unfilled"   # gapped above C and never traded back through it
CANCEL_INVALIDATED = "invalidated"                 # a close below the setup's structure
CANCEL_BREADTH = "breadth"                         # breadth fell below 50%
CANCEL_REPLACED = "replaced"                       # a newer signal on the same ticker
_CANCEL_REASONS = frozenset({CANCEL_TRIGGERED_UNFILLED, CANCEL_INVALIDATED, CANCEL_BREADTH, CANCEL_REPLACED})

# --- OOS seal (spec 3.7 step 2) ----------------------------------------------
SEALED = "sealed"                                  # the default: OOS sessions are refused
UNSEALED_BY_PICK = "unsealed_by_pick"              # the backtest runner, after verifying the committed pick
KNOWN_ANSWER_REPLAY = "known_answer_replay"        # the experiment's 14 real fill records and their bars, nothing else
_SEALS = frozenset({SEALED, UNSEALED_BY_PICK, KNOWN_ANSWER_REPLAY})

_SCALE = 1_000_000      # price comparisons in millionths of a dollar


class SealedSessionError(RuntimeError):
    """A session inside the sealed out-of-sample window was passed without a named unseal."""


def _i(price: float) -> int:
    return int(round(price * _SCALE))


def _finite(*values: float) -> bool:
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


@dataclass(frozen=True)
class Bar:
    """One completed daily bar. Impossible bars are rejected, not repaired."""

    date: dt.date
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        if not _finite(self.open, self.high, self.low, self.close):
            raise ValueError(f"impossible bar: {self}")
        lo, hi = _i(self.low), _i(self.high)
        if self.low <= 0 or not (lo <= _i(self.open) <= hi and lo <= _i(self.close) <= hi):
            raise ValueError(f"impossible bar: {self}")


@dataclass(frozen=True)
class Order:
    """A stop-limit entry with its bracket, plus everything that happened to it."""

    ticker: str
    signal_date: dt.date
    trigger: float                 # T
    ceiling: float                 # C
    stop: float                    # S
    target: float                  # P
    window: int                    # entry window in sessions after the signal day
    atr: float                     # ATR14 at the signal close
    tier_bps: float                # half-spread tier, fixed at the signal
    invalidation: Optional[float] = None   # pending order is canceled at any close below this
    # --- state ---
    state: str = PENDING
    last_session: Optional[dt.date] = None
    sessions_pending: int = 0
    cancel_reason: Optional[str] = None
    entry_date: Optional[dt.date] = None
    entry_kind: Optional[str] = None
    entry_raw: Optional[float] = None
    entry_cost: Optional[float] = None
    sessions_held: int = 0         # the fill session is session 0
    exit_date: Optional[dt.date] = None
    exit_kind: Optional[str] = None
    exit_raw: Optional[float] = None
    exit_cost: Optional[float] = None
    crash_bar: bool = False        # the report-only crash-bar bound priced this exit

    def __post_init__(self) -> None:
        if not _finite(self.stop, self.trigger, self.ceiling, self.target, self.atr, self.tier_bps):
            raise ValueError(f"{self.ticker}: levels, atr and tier_bps must be finite numbers")
        if self.invalidation is not None and not (_finite(self.invalidation)
                                                  and _i(self.invalidation) < _i(self.trigger)):
            raise ValueError(f"{self.ticker}: the invalidation level must be a finite number below the trigger")
        if not (0 < _i(self.stop) < _i(self.trigger) <= _i(self.ceiling) < _i(self.target)):
            raise ValueError(f"levels must satisfy 0 < S < T <= C < P: {self.stop}, {self.trigger}, "
                             f"{self.ceiling}, {self.target}")
        if self.window < 1 or self.atr <= 0 or self.tier_bps <= 0:
            raise ValueError("window must be >= 1 and atr, tier_bps must be positive")

    @property
    def planned_risk(self) -> float:
        return self.trigger - self.stop

    @property
    def is_trade(self) -> bool:
        return self.state in (OPEN, CLOSED)


class Evaluation(NamedTuple):
    r: float
    status: str        # "closed" or "marked"


# --- costs (spec 3.4) --------------------------------------------------------

def tier_bps(avg_dollar_volume: float, params: Params) -> float:
    """Half-spread tier from the 30-session average dollar volume ending t-1."""
    if not (_finite(avg_dollar_volume) and avg_dollar_volume >= 0):
        raise ValueError(f"average dollar volume must be a finite, non-negative number: {avg_dollar_volume!r}")
    for floor, bps in params.cost_tiers:
        if avg_dollar_volume >= floor:
            return bps
    raise ValueError("cost_tiers must end with a zero floor")


def half_spread(price: float, tier: float, params: Params) -> float:
    """h in dollars per share: max(tier x price, half a cent), times the sensitivity multiplier."""
    if not any(tier == bps for _, bps in params.cost_tiers):
        raise ValueError(f"tier {tier!r} is not one of the half-spread tiers (in bps): "
                         f"{[bps for _, bps in params.cost_tiers]}")
    return max(tier * 1e-4 * price, params.min_half_spread) * params.cost_mult


# --- OOS seal -----------------------------------------------------------------

@functools.lru_cache(maxsize=None)
def _oos_window(start: str, end: str) -> tuple[dt.date, dt.date]:
    return dt.date.fromisoformat(start), dt.date.fromisoformat(end)


def _is_known_answer(order: "Order", session: dt.date) -> bool:
    """True only for an exact replay of one of the 14 real fill records, on a session that trade needs."""
    for r in _KNOWN_ANSWER_RECORDS:
        if not (r.ticker == order.ticker and r.entry_date <= session <= r.exit_date):
            continue
        if not (_i(order.trigger) == _i(order.ceiling) == _i(r.entry) and _i(order.stop) == _i(r.stop)):
            continue
        if not (_i(order.target) == _i(_REPLAY_TARGET_MULT * r.entry) and order.window == 1
                and order.signal_date < r.entry_date):
            continue
        if order.state == PENDING and session != r.entry_date:
            continue
        if order.entry_date is not None and order.entry_date != r.entry_date:
            continue
        return True
    return False


def _check_seal(order: "Order", session: dt.date, seal: str, params: Params) -> None:
    if seal not in _SEALS:
        raise ValueError(f"unknown seal state {seal!r}; pass SEALED, UNSEALED_BY_PICK or KNOWN_ANSWER_REPLAY")
    if seal == UNSEALED_BY_PICK:
        return
    first, last = _oos_window(params.oos_start, params.oos_end)
    if not first <= session <= last:
        return
    if seal == KNOWN_ANSWER_REPLAY and _is_known_answer(order, session):
        return
    scope = " and is not one of the 14 known-answer records" if seal == KNOWN_ANSWER_REPLAY else ""
    raise SealedSessionError(f"{order.ticker}: session {session} is inside the sealed out-of-sample window "
                             f"{first}..{last}{scope} (spec 3.7 step 2)")


# --- transitions --------------------------------------------------------------

def _fill(o: Order, session: dt.date, kind: str, raw: float, params: Params) -> Order:
    mult = params.open_fill_cost_mult if kind == ENTRY_OPEN else 1.0
    return replace(o, state=OPEN, entry_date=session, entry_kind=kind, entry_raw=raw,
                   entry_cost=half_spread(raw, o.tier_bps, params) * mult)


def _exit(o: Order, session: dt.date, kind: str, raw: float, params: Params, crash: bool = False) -> Order:
    if kind in (EXIT_STOP, EXIT_GAP_STOP):
        mult = params.stop_exit_cost_mult
    elif kind == EXIT_TIME:
        mult = params.open_fill_cost_mult
    else:
        mult = 1.0
    return replace(o, state=CLOSED, exit_date=session, exit_kind=kind, exit_raw=raw,
                   exit_cost=half_spread(raw, o.tier_bps, params) * mult, crash_bar=crash)


def _intraday_stop(o: Order, bar: Bar, params: Params) -> tuple[float, bool]:
    """Price of an intraday stop: S, or the low under the report-only crash-bar bound
    (spec 3.4: stop sessions with open > S and low < S - 1 ATR)."""
    if (params.crash_bar_bound and _i(bar.open) > _i(o.stop)
            and _i(bar.low) < _i(o.stop - params.crash_bar_atr * o.atr)):
        return bar.low, True
    return o.stop, False


def _entry_session(o: Order, session: dt.date, bar: Bar, params: Params) -> tuple[Order, bool]:
    """Try to fill a pending order on this bar. Returns (order, triggered_but_unfilled)."""
    through = _i(params.trade_through)
    kind: Optional[str] = None
    raw = 0.0
    if _i(bar.open) >= _i(o.trigger):
        if _i(bar.open) <= _i(o.ceiling):
            kind, raw = ENTRY_OPEN, bar.open
        elif _i(bar.low) <= _i(o.ceiling) - through:
            kind, raw = ENTRY_CEILING, o.ceiling
        else:
            return o, True                       # triggered at the open, limit never reached
    elif _i(bar.high) >= _i(o.trigger):
        kind, raw = ENTRY_TRIGGER, o.trigger
    if kind is None:
        return o, False

    o = _fill(o, session, kind, raw, params)
    # The OCO is live from the fill. The stop wins any tie.
    if _i(bar.low) <= _i(o.stop):
        price, crash = _intraday_stop(o, bar, params)
        return _exit(o, session, EXIT_STOP, price, params, crash), False
    target_through = _i(o.target) + through
    reached = _i(bar.close) >= target_through if kind == ENTRY_CEILING else _i(bar.high) >= target_through
    if reached:
        return _exit(o, session, EXIT_TARGET, o.target, params), False
    return o, False


def _held_session(o: Order, session: dt.date, bar: Bar, params: Params) -> Order:
    """A session after the fill: OCO at the open, then the time exit, then intraday."""
    target_through = _i(o.target) + _i(params.trade_through)
    if _i(bar.open) <= _i(o.stop):                                   # 1. gap through the stop
        return _exit(o, session, EXIT_GAP_STOP, bar.open, params)
    if _i(bar.open) >= target_through:                               # 2. gap past the target: P, no bonus
        return _exit(o, session, EXIT_TARGET, o.target, params)
    if o.sessions_held >= params.time_exit_session:                  # still open after session 40
        return _exit(o, session, EXIT_TIME, bar.open, params)
    if _i(bar.low) <= _i(o.stop):                                    # 3. intraday stop
        price, crash = _intraday_stop(o, bar, params)
        return _exit(o, session, EXIT_STOP, price, params, crash)
    if _i(bar.high) >= target_through:                               # 4. intraday target
        return _exit(o, session, EXIT_TARGET, o.target, params)
    return o


def step(order: Order, session: dt.date, bar: Optional[Bar], *, breadth_ok: bool, params: Params,
         seal: str = SEALED) -> Order:
    """Advance one session. ``bar`` is None when the symbol has no bar that session.

    ``breadth_ok`` is the breadth test at THIS session's close (pass True with
    the filter off). A pending order that is still unfilled after a close with
    breadth below 50% is canceled, so every later fill had breadth at its prior
    close. Breadth never touches a filled trade.

    A terminal order is returned unchanged. For a live order the session must be
    after its latest one (see the caller contract in the module docstring).
    """
    _check_seal(order, session, seal, params)
    if breadth_ok is not True and breadth_ok is not False:
        raise TypeError(f"{order.ticker}: breadth_ok must be True or False, not {breadth_ok!r}")
    if order.state in TERMINAL:
        return order
    if order.last_session is not None and session <= order.last_session:
        raise ValueError(f"{order.ticker}: session {session} is not after {order.last_session}; sessions are "
                         "consumed once, in order (rebuild the order from its signal day to re-run)")
    if session <= order.signal_date:
        raise ValueError(f"{order.ticker}: an order cannot act on or before its signal day")
    if bar is not None and bar.date != session:
        raise ValueError(f"{order.ticker}: bar dated {bar.date} passed for session {session}")

    if order.state == PENDING:
        o = replace(order, last_session=session, sessions_pending=order.sessions_pending + 1)
        triggered_unfilled = False
        if bar is not None:
            o, triggered_unfilled = _entry_session(o, session, bar, params)
            if o.state != PENDING:
                return o
        if triggered_unfilled:
            return replace(o, state=CANCELED, cancel_reason=CANCEL_TRIGGERED_UNFILLED)
        if bar is not None and o.invalidation is not None and _i(bar.close) < _i(o.invalidation):
            return replace(o, state=CANCELED, cancel_reason=CANCEL_INVALIDATED)
        if not breadth_ok:
            return replace(o, state=CANCELED, cancel_reason=CANCEL_BREADTH)
        if o.sessions_pending >= o.window:
            return replace(o, state=EXPIRED)
        return o

    o = replace(order, last_session=session, sessions_held=order.sessions_held + 1)
    if bar is None:
        return o
    return _held_session(o, session, bar, params)


def run(order: Order, sessions: Iterable[tuple[dt.date, Optional[Bar], bool]], *, params: Params,
        seal: str = SEALED) -> Order:
    """Advance through (session, bar, breadth_ok) tuples until the order is terminal.

    Running an order from its signal day over the stored sessions is the one way
    to (re)compute its state; the result depends only on the inputs.
    """
    for session, bar, breadth_ok in sessions:
        order = step(order, session, bar, breadth_ok=breadth_ok, params=params, seal=seal)
        if order.state in TERMINAL:
            break
    return order


def cancel(order: Order, reason: str) -> Order:
    """Cancel a pending order outside ``step``: replacement by a newer signal (spec 3.2)."""
    if order.state != PENDING:
        raise ValueError(f"{order.ticker}: only a pending order can be canceled (state {order.state})")
    if reason not in _CANCEL_REASONS:
        raise ValueError(f"{order.ticker}: unknown cancel reason {reason!r}")
    return replace(order, state=CANCELED, cancel_reason=reason)


# --- R (spec 3.5) -------------------------------------------------------------

def _check_mark(order: Order, close: Optional[float], params: Params) -> None:
    """A trade that is still open closed above S and less than a cent through P, or it would have
    exited. Any other close is on another basis (an unapplied split or distribution) or is another
    symbol's: an error, never a mark."""
    if close is None or not _finite(close):
        raise ValueError(f"{order.ticker}: a close is required to mark an open trade")
    if not (_i(order.stop) < _i(close) < _i(order.target) + _i(params.trade_through)):
        raise ValueError(f"{order.ticker}: {close} cannot be the close of a trade still open between "
                         f"S {order.stop} and P {order.target}")


def net_entry(order: Order) -> float:
    return order.entry_raw + order.entry_cost


def r_multiple(order: Order) -> float:
    """R = (net exit - net entry) / (T - S), against the planned risk."""
    if order.state != CLOSED:
        raise ValueError(f"{order.ticker}: R is defined for closed trades (state {order.state})")
    return ((order.exit_raw - order.exit_cost) - net_entry(order)) / order.planned_risk


def evaluate_at_cutoff(order: Order, cutoff: dt.date, cutoff_close: Optional[float],
                       params: Params, *, seal: str = SEALED) -> Optional[Evaluation]:
    """Value a trade at a cutoff session's close. THE one rule for trades open at a cutoff.

    The forward window, every historical analog band window, the in-sample pick
    marks and the end of the data all go through this function, so a trade that
    is still open is treated identically everywhere (spec section 6):

      * closed by the cutoff      -> its realized R;
      * filled and still open     -> marked at ``cutoff_close`` net of the exit
                                     half-spread (h, an ordinary intraday exit);
      * never filled              -> None: not a trade.

    The order must have been advanced exactly through ``cutoff`` (an order
    signaled at the cutoff close has had no session yet). Anything else is an
    error, never a number: a stale order could have filled by the cutoff, and
    an order advanced past it would leak later prices into the mark. If the
    symbol has no bar on the cutoff session, pass its latest earlier close.
    A close at or below S, or a cent or more through P, is refused: a trade
    that is still open cannot have closed there.
    """
    _check_seal(order, cutoff, seal, params)
    if order.signal_date > cutoff:
        raise ValueError(f"{order.ticker}: signaled {order.signal_date}, after the cutoff {cutoff}")
    if order.state == CLOSED:
        if order.exit_date > cutoff:
            raise ValueError(f"{order.ticker}: order was advanced past the cutoff {cutoff}")
        return Evaluation(r_multiple(order), "closed")
    if order.state == OPEN:
        if order.last_session != cutoff:
            raise ValueError(f"{order.ticker}: an open order must be advanced exactly through {cutoff}")
        _check_mark(order, cutoff_close, params)
        net_exit = cutoff_close - half_spread(cutoff_close, order.tier_bps, params)
        return Evaluation((net_exit - net_entry(order)) / order.planned_risk, "marked")
    if order.state == PENDING:
        advanced = order.last_session if order.last_session is not None else order.signal_date
        if advanced < cutoff:
            raise ValueError(f"{order.ticker}: a pending order must be advanced through {cutoff} "
                             f"before it is called 'not a trade' (advanced through {advanced})")
    return None


def close_at_mark(order: Order, cutoff: dt.date, cutoff_close: float, params: Params, *,
                  seal: str = SEALED) -> Order:
    """Close a still-open trade at a cutoff close (exit kind "mark"). Same number as evaluate_at_cutoff."""
    _check_seal(order, cutoff, seal, params)
    if order.state != OPEN or order.last_session != cutoff:
        raise ValueError(f"{order.ticker}: only a trade open through {cutoff} can be marked")
    _check_mark(order, cutoff_close, params)
    return replace(order, state=CLOSED, exit_date=cutoff, exit_kind=EXIT_MARK, exit_raw=cutoff_close,
                   exit_cost=half_spread(cutoff_close, order.tier_bps, params))


# --- corporate actions (spec 3.1 and section 4) -------------------------------

def rescale(order: Order, ratio: float) -> Order:
    """Rebase an order after a split: every price is multiplied by new/old (0.5 for a 2:1 split).

    Exact scaling, no re-rounding: the tracked trade keeps its R, its entry
    window and its hold clock. Cent rounding applies only to the replacement
    paper ticket, which the paper module builds.
    """
    if not (_finite(ratio) and ratio > 0):
        raise ValueError("ratio must be a finite, positive number")

    def f(x: Optional[float]) -> Optional[float]:
        return None if x is None else x * ratio

    return replace(order, trigger=order.trigger * ratio, ceiling=order.ceiling * ratio,
                   stop=order.stop * ratio, target=order.target * ratio, atr=order.atr * ratio,
                   invalidation=f(order.invalidation), entry_raw=f(order.entry_raw),
                   entry_cost=f(order.entry_cost), exit_raw=f(order.exit_raw), exit_cost=f(order.exit_cost))


def shift(order: Order, dollars: float) -> Order:
    """Rebase an order after a special distribution: every price moves by ``dollars``
    (new basis minus old: -1.60 for FRO's 2026-09-18 distribution, spec 3.1).

    A dollar shift keeps every price difference, so the planned risk, the ATR
    and the R of a closed trade are unchanged, and so are the costs already
    paid. A later exit pays its bps cost on the new, lower price.
    """
    if not _finite(dollars):
        raise ValueError("the shift must be a finite dollar amount")

    def f(x: Optional[float]) -> Optional[float]:
        return None if x is None else x + dollars

    return replace(order, trigger=order.trigger + dollars, ceiling=order.ceiling + dollars,
                   stop=order.stop + dollars, target=order.target + dollars,
                   invalidation=f(order.invalidation), entry_raw=f(order.entry_raw), exit_raw=f(order.exit_raw))
