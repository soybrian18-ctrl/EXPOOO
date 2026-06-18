#!/usr/bin/env python3
"""Read-only Alpaca account/positions snapshot -- the rule-check state source for
the paper executor (analogous to portfolio.py, but for the Alpaca paper account
where execution happens). Reads ALPACA_* from .env. Never places orders; never
logs the secret. PAPER-ONLY guard: refuses unless ALPACA_ENV == 'paper'.

Usage:  python loops/alpaca_account.py   (prints a JSON snapshot)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class AlpacaConfigError(Exception):
    """Raised when Alpaca credentials / environment are missing or not paper."""


def load_creds() -> dict:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    return {
        "key": (os.environ.get("ALPACA_API_KEY") or "").strip(),
        "secret": (os.environ.get("ALPACA_SECRET_KEY") or "").strip(),
        "env": (os.environ.get("ALPACA_ENV") or "paper").strip().lower(),
    }


def get_trading_client(require_paper: bool = True):
    """Return an Alpaca TradingClient. Hard paper-only guard in this phase."""
    creds = load_creds()
    if not creds["key"] or not creds["secret"]:
        raise AlpacaConfigError("ALPACA_API_KEY / ALPACA_SECRET_KEY missing from .env")
    if require_paper and creds["env"] != "paper":
        raise AlpacaConfigError(
            f"ALPACA_ENV is '{creds['env']}', not 'paper' -- refusing (paper-only phase)"
        )
    from alpaca.trading.client import TradingClient  # imported lazily
    return TradingClient(creds["key"], creds["secret"], paper=(creds["env"] == "paper"))


def account_snapshot(client) -> dict:
    """Read-only equity / cash / positions, plus derived deployment figures."""
    acct = client.get_account()
    positions = client.get_all_positions()
    pos = [
        {
            "symbol": p.symbol,
            "qty": float(p.qty),
            "market_value": float(p.market_value),
            "avg_entry_price": float(p.avg_entry_price),
        }
        for p in positions
    ]
    deployed = sum(abs(p["market_value"]) for p in pos)
    equity = float(acct.equity)
    return {
        "env": "paper",
        "account_status": str(getattr(acct, "status", "")),
        "equity": equity,
        "cash": float(acct.cash),
        "buying_power": float(acct.buying_power),
        "portfolio_value": float(acct.portfolio_value),
        "position_count": len(pos),
        "held_symbols": [p["symbol"] for p in pos],
        "positions": pos,
        "deployed_value": round(deployed, 2),
        "deployed_pct": round(deployed / equity * 100, 2) if equity else None,
    }


def main() -> int:
    try:
        snap = account_snapshot(get_trading_client())
    except Exception as exc:  # never crash -> structured error
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps(snap, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
