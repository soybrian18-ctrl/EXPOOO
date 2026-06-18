#!/usr/bin/env python3
"""Alpaca PAPER order executor -- the ONLY order-placement file in the project.

Triggered when the user types "approved" after /equity-research presents a report.
Reads the structured handoff (logs/pending_order.json), re-validates EVERY trading
rule against the live Alpaca paper account, and -- only if all gates pass -- submits
a single native Alpaca BRACKET order (limit buy + one-cancels-other take-profit /
stop-loss, all GTC) which is the "1st Triggers OCO" equivalent.

Hard safety:
  * PAPER ONLY -- refuses unless ALPACA_ENV == 'paper'.
  * Kill switch -- if TRADING_HALTED exists in the project root, logs + exits, no order.
  * Never margin/options/short; never > $200 notional; one order per ticker per day.
  * Any Alpaca API error -> log + desktop notification, NO automatic retry.
  * Every attempt logged to logs/order_execution.txt (never logs the API secret).

Usage:  python loops/order_executor.py [path/to/pending_order.json]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import loop_common as lc
from alpaca_account import (
    PROJECT_ROOT,
    account_snapshot,
    get_trading_client,
)

# ===========================================================================
# EXEC_CONFIG  -- all gates/limits as named constants (never inline)
# ===========================================================================
EXEC_CONFIG = {
    "REQUIRED_ENV": "paper",
    "DEPLOY_CAP_PCT": 70.0,
    "MAX_POSITIONS": 4,
    "MAX_RISK_PCT": 2.0,
    "MAX_NOTIONAL_USD": 200.0,
    "PENDING_TTL_SECONDS": 900,            # handoff freshness (15 min)
    "KILL_SWITCH_FILE": "TRADING_HALTED",  # in PROJECT_ROOT
    "PENDING_FILE": "pending_order.json",  # under logs/
    "LOG_FILE": "order_execution.txt",
    "RULES_FILE": "references/trading-rules.md",
    "NOTIFY_TITLE": "Alpaca Paper Executor",
    "REQUIRED_FIELDS": ["ticker", "shares", "entry_limit", "stop", "target_t1", "env"],
}

# Exit codes: 0 placed | 1 rejected/api-error | 2 config/handoff problem | 3 kill-switch


def _log(message: str) -> None:
    lc.append_log(EXEC_CONFIG["LOG_FILE"], f"LOOP=order_executor {message}")


def _notify(message: str) -> bool:
    return lc.notify(EXEC_CONFIG["NOTIFY_TITLE"], message)


def kill_switch_active() -> bool:
    return (PROJECT_ROOT / EXEC_CONFIG["KILL_SWITCH_FILE"]).exists()


def rules_present() -> tuple[bool, str]:
    """Re-read trading-rules.md before every execution (binding context)."""
    path = PROJECT_ROOT / EXEC_CONFIG["RULES_FILE"]
    if not path.exists():
        return False, "trading-rules.md missing"
    text = path.read_text(encoding="utf-8")
    if "Awaiting rules" in text or len(text.strip()) < 200:
        return False, "trading-rules.md is a placeholder"
    return True, "ok"


def load_pending_order(path: Path) -> dict:
    """Load + structurally validate the handoff; enforce env=paper and TTL freshness."""
    if not path.exists():
        raise ValueError(f"no pending order at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in EXEC_CONFIG["REQUIRED_FIELDS"] if k not in data]
    if missing:
        raise ValueError(f"pending order missing fields: {missing}")
    if str(data.get("env", "")).lower() != EXEC_CONFIG["REQUIRED_ENV"]:
        raise ValueError(f"pending order env={data.get('env')!r}, expected 'paper'")
    ca = data.get("computed_at")
    if ca:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(ca).astimezone(timezone.utc)).total_seconds()
            if age > EXEC_CONFIG["PENDING_TTL_SECONDS"]:
                raise ValueError(f"pending order is stale ({int(age)}s > {EXEC_CONFIG['PENDING_TTL_SECONDS']}s TTL)")
        except ValueError:
            raise
        except Exception:
            raise ValueError("pending order has an unparseable computed_at timestamp")
    return data


def ordered_today(ticker: str) -> bool:
    """True if an ENTRY for this ticker was already placed today (one/ticker/day)."""
    path = lc.LOGS_DIR / EXEC_CONFIG["LOG_FILE"]
    if not path.exists():
        return False
    today = datetime.now().astimezone().date().isoformat()
    needle_t = f"ticker={ticker.upper()}"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(today) and needle_t in line and "action=ENTRY" in line:
            return True
    return False


def evaluate_rules(order: dict, snap: dict) -> list[str]:
    """PURE rule evaluation (testable). Returns the list of failed-rule tags; empty = OK."""
    fails: list[str] = []
    ticker = str(order["ticker"]).upper()
    shares = float(order["shares"])
    entry = float(order["entry_limit"])
    stop = float(order["stop"])
    target = float(order["target_t1"])
    equity = float(snap["equity"])
    cash = float(snap["cash"])
    deployed = float(snap["deployed_value"])
    held = [s.upper() for s in snap.get("held_symbols", [])]

    notional = shares * entry
    risk = shares * (entry - stop)

    if shares <= 0:
        fails.append("invalid_shares")
    if not (stop < entry < target):
        fails.append("invalid_levels(stop<entry<target)")
    if notional > EXEC_CONFIG["MAX_NOTIONAL_USD"]:
        fails.append(f"over_$200_notional(${notional:.2f})")
    if equity and risk > (EXEC_CONFIG["MAX_RISK_PCT"] / 100.0) * equity:
        fails.append(f"risk_over_2pct(${risk:.2f}>${0.02*equity:.2f})")
    if equity and (deployed + notional) / equity * 100.0 > EXEC_CONFIG["DEPLOY_CAP_PCT"]:
        fails.append("deployment_over_70pct")
    if ticker in held:
        fails.append("already_holding")
    if (snap["position_count"] + (0 if ticker in held else 1)) > EXEC_CONFIG["MAX_POSITIONS"]:
        fails.append("exceeds_4_positions")
    if notional > cash:
        fails.append("would_use_margin(notional>cash)")
    return fails


def place_bracket(client, order: dict):
    """Submit ONE native Alpaca bracket order (limit buy + OCO TP/SL, all GTC).

    Isolated so tests can patch/verify it is never reached on a blocked path.
    """
    from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
    from alpaca.trading.requests import LimitOrderRequest, StopLossRequest, TakeProfitRequest

    req = LimitOrderRequest(
        symbol=str(order["ticker"]).upper(),
        qty=int(order["shares"]),
        side=OrderSide.BUY,
        time_in_force=TimeInForce.GTC,
        limit_price=round(float(order["entry_limit"]), 2),
        order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(limit_price=round(float(order["target_t1"]), 2)),
        stop_loss=StopLossRequest(stop_price=round(float(order["stop"]), 2)),
    )
    return client.submit_order(order_data=req)


def main(argv: list[str]) -> int:
    pending_path = Path(argv[1]) if len(argv) > 1 else (lc.LOGS_DIR / EXEC_CONFIG["PENDING_FILE"])

    # 1) Kill switch -- checked FIRST, before anything else.
    if kill_switch_active():
        _log(f"HALTED kill_switch=TRADING_HALTED pending={pending_path.name}")
        _notify("Order blocked: TRADING_HALTED kill switch is active.")
        return 3

    # 2) Re-read trading rules (binding context).
    ok, reason = rules_present()
    if not ok:
        _log(f"ABORT reason=\"{reason}\"")
        _notify(f"Order aborted: {reason}.")
        return 2

    # 3) Load + freshness-check the handoff.
    try:
        order = load_pending_order(pending_path)
    except Exception as exc:
        _log(f"ABORT reason=\"pending_invalid: {exc}\"")
        _notify(f"Order aborted: {exc}.")
        return 2
    ticker = str(order["ticker"]).upper()

    # 4) One order per ticker per day.
    if ordered_today(ticker):
        _log(f"REJECT ticker={ticker} action=reject rule=one_order_per_ticker_per_day")
        _notify(f"Order for {ticker} blocked: already ordered today (one per ticker/day).")
        return 1

    # 5) Connect to Alpaca PAPER + read account state (read-only).
    try:
        client = get_trading_client(require_paper=True)
        snap = account_snapshot(client)
    except Exception as exc:
        _log(f"ERROR ticker={ticker} stage=connect detail=\"{type(exc).__name__}: {exc}\"")
        _notify(f"Order for {ticker} failed: Alpaca connection/auth error ({type(exc).__name__}).")
        return 1

    # 6) Enforce ALL trading rules against the live paper account.
    fails = evaluate_rules(order, snap)
    if fails:
        _log(
            f"REJECT ticker={ticker} action=reject rules_failed={';'.join(fails)} "
            f"equity={snap['equity']} deployed_pct={snap['deployed_pct']} positions={snap['position_count']}"
        )
        _notify(f"Order for {ticker} REJECTED — rule(s) failed: {', '.join(fails)}.")
        return 1

    # 7) All gates passed -> submit the bracket (the only place an order is sent).
    notional = float(order["shares"]) * float(order["entry_limit"])
    _log(
        f"ATTEMPT ticker={ticker} action=submit qty={order['shares']} entry={order['entry_limit']} "
        f"stop={order['stop']} target={order['target_t1']} notional={notional:.2f} env=paper"
    )
    try:
        placed = place_bracket(client, order)
    except Exception as exc:
        _log(f"ERROR ticker={ticker} stage=submit detail=\"{type(exc).__name__}: {exc}\"")
        _notify(f"Order for {ticker} FAILED at submit: {type(exc).__name__}: {exc}. No retry.")
        return 1

    oid = getattr(placed, "id", None)
    status = str(getattr(placed, "status", ""))
    _log(
        f"ENTRY ticker={ticker} action=ENTRY qty={order['shares']} entry_limit={order['entry_limit']} "
        f"stop={order['stop']} target={order['target_t1']} notional={notional:.2f} "
        f"order_class=bracket tif=GTC env=paper alpaca_order_id={oid} status={status} result=submitted"
    )
    _notify(f"✅ Paper bracket placed: BUY {order['shares']} {ticker} @ {order['entry_limit']} "
            f"(stop {order['stop']} / target {order['target_t1']}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
