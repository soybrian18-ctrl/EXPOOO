"""Pure analysis logic for the Schwab monitor.

Everything here operates on the plain dictionaries that schwab-py returns from
the Schwab Trader API. There is no network access and no terminal rendering in
this module, which keeps the financial math unit-testable in isolation
(see ``tests/test_analysis.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Schwab vocabulary
# ---------------------------------------------------------------------------

TIF_DAY = "DAY"
TIF_GTC = "GOOD_TILL_CANCEL"

STOP_ORDER_TYPES = frozenset(
    {"STOP", "STOP_LIMIT", "TRAILING_STOP", "TRAILING_STOP_LIMIT"}
)

# Statuses that represent a live / not-yet-terminal order.
OPEN_ORDER_STATUSES = frozenset(
    {
        "WORKING",
        "QUEUED",
        "ACCEPTED",
        "PENDING_ACTIVATION",
        "AWAITING_PARENT_ORDER",
        "AWAITING_STOP_CONDITION",
        "AWAITING_CONDITION",
        "AWAITING_MANUAL_REVIEW",
        "AWAITING_RELEASE_TIME",
        "AWAITING_UR_OUT",
        "PENDING_ACKNOWLEDGEMENT",
        "NEW",
    }
)

# Stop instructions that protect a *short* position (you buy to close a short).
_SHORT_PROTECTING_INSTRUCTIONS = frozenset({"BUY", "BUY_TO_COVER"})

DEFAULT_STOP_PROXIMITY_PCT = 5.0


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PositionRow:
    symbol: str
    quantity: float  # signed: positive = long, negative = short
    avg_price: float
    mark: float
    market_value: float
    pl_dollars: float
    pl_pct: Optional[float]  # None when cost basis is zero

    @property
    def is_short(self) -> bool:
        return self.quantity < 0


def _net_quantity(pos: dict[str, Any]) -> float:
    """Signed share count: long quantity minus short quantity."""
    return float(pos.get("longQuantity", 0) or 0) - float(pos.get("shortQuantity", 0) or 0)


def position_row(pos: dict[str, Any]) -> Optional[PositionRow]:
    """Build a :class:`PositionRow` from a raw Schwab position, or ``None``.

    Returns ``None`` for fully-closed positions (net quantity of zero) so they
    do not clutter the report.
    """
    qty = _net_quantity(pos)
    if qty == 0:
        return None

    avg_price = float(pos.get("averagePrice", 0) or 0)
    market_value = float(pos.get("marketValue", 0) or 0)
    # Mark is derived from the broker-supplied market value so it stays
    # consistent with the account snapshot (no extra quote round-trips).
    mark = market_value / qty if qty != 0 else 0.0

    # (mark - avg) * qty is correct for both longs and shorts because the sign
    # of qty flips the direction of the P/L automatically.
    pl_dollars = (mark - avg_price) * qty
    cost_basis = abs(avg_price * qty)
    pl_pct = (pl_dollars / cost_basis * 100.0) if cost_basis else None

    symbol = (pos.get("instrument") or {}).get("symbol", "?")
    return PositionRow(
        symbol=symbol,
        quantity=qty,
        avg_price=avg_price,
        mark=mark,
        market_value=market_value,
        pl_dollars=pl_dollars,
        pl_pct=pl_pct,
    )


def position_rows(positions: list[dict[str, Any]]) -> list[PositionRow]:
    rows = [position_row(p) for p in positions or []]
    return [r for r in rows if r is not None]


# ---------------------------------------------------------------------------
# Account balances
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AccountSummary:
    net_liquidating_value: Optional[float]
    cash_balance: Optional[float]
    buying_power: Optional[float]
    long_market_value: Optional[float]


def account_summary(securities_account: dict[str, Any]) -> AccountSummary:
    balances = securities_account.get("currentBalances") or {}
    buying_power = balances.get("buyingPower")
    if buying_power is None:
        # Cash accounts do not report buyingPower; fall back to investable cash.
        buying_power = balances.get("cashAvailableForTrading")
    return AccountSummary(
        net_liquidating_value=balances.get("liquidationValue"),
        cash_balance=balances.get("cashBalance"),
        buying_power=buying_power,
        long_market_value=balances.get("longMarketValue"),
    )


def deployed_capital(rows: list[PositionRow]) -> float:
    """Gross capital at work: the absolute market value across all positions."""
    return sum(abs(r.market_value) for r in rows)


def deployed_pct(deployed: float, net_liq: Optional[float]) -> Optional[float]:
    if not net_liq:
        return None
    return deployed / net_liq * 100.0


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OrderRow:
    order_id: Optional[int]
    symbol: str
    instruction: Optional[str]
    order_type: Optional[str]
    quantity: Optional[float]
    limit_price: Optional[float]
    stop_price: Optional[float]
    tif: Optional[str]
    status: Optional[str]

    @property
    def is_day(self) -> bool:
        return self.tif == TIF_DAY

    @property
    def is_stop(self) -> bool:
        return (self.order_type or "") in STOP_ORDER_TYPES


def flatten_orders(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Recursively expand OCO/bracket/trigger orders into individual legs.

    A Schwab order may nest child strategies (e.g. a one-cancels-other bracket
    where one child is the protective stop). We collect every order dict that
    carries an ``orderLegCollection`` so nested stops are never missed.
    """
    out: list[dict[str, Any]] = []
    for order in orders or []:
        if order.get("orderLegCollection"):
            out.append(order)
        children = order.get("childOrderStrategies")
        if children:
            out.extend(flatten_orders(children))
    return out


def order_row(order: dict[str, Any]) -> OrderRow:
    legs = order.get("orderLegCollection") or []
    first = legs[0] if legs else {}
    symbol = (first.get("instrument") or {}).get("symbol", "?")
    return OrderRow(
        order_id=order.get("orderId"),
        symbol=symbol,
        instruction=first.get("instruction"),
        order_type=order.get("orderType"),
        quantity=order.get("quantity"),
        limit_price=order.get("price"),
        stop_price=order.get("stopPrice"),
        tif=order.get("duration"),
        status=order.get("status"),
    )


def working_order_rows(orders: list[dict[str, Any]]) -> list[OrderRow]:
    """Flatten, keep only open/live legs, and return them as rows."""
    rows = [order_row(o) for o in flatten_orders(orders)]
    return [r for r in rows if (r.status or "") in OPEN_ORDER_STATUSES]


# ---------------------------------------------------------------------------
# Stop-loss analysis
# ---------------------------------------------------------------------------


def stop_proximity_pct(mark: float, stop: float, *, is_short: bool) -> float:
    """Percent the mark must move to trigger the stop (negative = breached).

    For a long, the protective stop sits *below* the mark, so a small positive
    number means the price is close to triggering. For a short the stop sits
    *above* the mark and the calculation is mirrored.
    """
    if mark <= 0:
        return 0.0
    if is_short:
        return (stop - mark) / mark * 100.0
    return (mark - stop) / mark * 100.0


@dataclass(frozen=True)
class StopEvaluation:
    symbol: str
    order_id: Optional[int]
    stop_price: float
    tif: Optional[str]
    mark: Optional[float]
    proximity_pct: Optional[float]
    has_position: bool
    is_short: bool
    near_flag: bool  # mark within threshold of stop
    day_flag: bool  # TIF is DAY rather than GTC

    @property
    def is_flagged(self) -> bool:
        return self.near_flag or self.day_flag


@dataclass(frozen=True)
class StopReport:
    threshold_pct: float
    evaluations: list[StopEvaluation] = field(default_factory=list)
    positions_without_stop: list[str] = field(default_factory=list)

    @property
    def red_flags(self) -> list[StopEvaluation]:
        return [e for e in self.evaluations if e.is_flagged]

    @property
    def all_clear(self) -> bool:
        """True when none of the *required* checks (near-stop, DAY TIF) fired."""
        return not self.red_flags


def analyze_stops(
    positions: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    *,
    threshold_pct: float = DEFAULT_STOP_PROXIMITY_PCT,
) -> StopReport:
    """Cross-reference positions with their working stop orders.

    Produces, for every working stop order:
      * whether the mark is within ``threshold_pct`` of the stop, and
      * whether the order's TIF is DAY instead of GTC.
    Also lists open positions that have no protective stop at all.
    """
    rows = position_rows(positions)
    by_symbol: dict[str, PositionRow] = {r.symbol: r for r in rows}

    stop_orders = [r for r in working_order_rows(orders) if r.is_stop]
    symbols_with_stop: set[str] = set()
    evaluations: list[StopEvaluation] = []

    for stop in stop_orders:
        if stop.stop_price is None:
            continue
        symbols_with_stop.add(stop.symbol)
        pos = by_symbol.get(stop.symbol)

        if pos is not None:
            is_short = pos.is_short
            mark: Optional[float] = pos.mark
            has_position = True
        else:
            # Orphan stop (no matching open position): infer direction from the
            # instruction so a DAY-TIF flag can still be reported.
            is_short = (stop.instruction or "") in _SHORT_PROTECTING_INSTRUCTIONS
            mark = None
            has_position = False

        if mark is not None:
            proximity = stop_proximity_pct(mark, stop.stop_price, is_short=is_short)
            near_flag = proximity <= threshold_pct
        else:
            proximity = None
            near_flag = False

        evaluations.append(
            StopEvaluation(
                symbol=stop.symbol,
                order_id=stop.order_id,
                stop_price=stop.stop_price,
                tif=stop.tif,
                mark=mark,
                proximity_pct=proximity,
                has_position=has_position,
                is_short=is_short,
                near_flag=near_flag,
                day_flag=stop.is_day,
            )
        )

    positions_without_stop = sorted(
        r.symbol for r in rows if r.symbol not in symbols_with_stop
    )
    return StopReport(
        threshold_pct=threshold_pct,
        evaluations=evaluations,
        positions_without_stop=positions_without_stop,
    )
