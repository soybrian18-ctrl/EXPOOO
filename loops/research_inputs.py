#!/usr/bin/env python3
"""Loop 3 live account inputs (read-only) -- deterministic balance for sizing.

Pre-flight token validation + the live balance/positions the equity-research
command needs to size a candidate against the 2% rule and the 60-70% deployment
band. Reuses the same config/analysis layer portfolio.py uses. Emits JSON.

Usage:  python loops/research_inputs.py
On a bad token it emits {"token_ok": false, ...} (exit 1) so the command can stop
gracefully instead of crashing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # for config/analysis
sys.path.insert(0, str(Path(__file__).resolve().parent))          # for loop_common

import analysis  # noqa: E402
import loop_common as lc  # noqa: E402
from config import (  # noqa: E402
    build_client,
    fetch_securities_account,
    load_settings,
    resolve_account,
)

WARN_DAYS = 6.0
CRITICAL_DAYS = 6.5
DEPLOY_CAP = 0.70


def main() -> int:
    tok = lc.validate_token(lc.resolve_token_path(), warn_days=WARN_DAYS, critical_days=CRITICAL_DAYS)
    if not tok.ok:
        print(json.dumps({"token_ok": False, "token_status": tok.status, "reason": tok.reason}))
        return 1
    try:
        settings = load_settings()
        client = build_client(settings)
        account = resolve_account(client, settings)
        sa = fetch_securities_account(client, account.account_hash)
        summary = analysis.account_summary(sa)
        rows = analysis.position_rows(sa.get("positions", []))
        deployed = analysis.deployed_capital(rows)
        nl = summary.net_liquidating_value
        dp = analysis.deployed_pct(deployed, nl)
        out = {
            "token_ok": True,
            "token_status": tok.status,
            "net_liq": nl,
            "cash": summary.cash_balance,
            "deployed": round(deployed, 2),
            "deployed_pct": round(dp, 2) if dp is not None else None,
            "position_count": len(rows),
            "positions": [{"symbol": r.symbol, "qty": r.quantity} for r in rows],
            "headroom_to_70pct": round(DEPLOY_CAP * nl - deployed, 2) if nl else None,
            "two_pct_risk_budget": round(0.02 * nl, 2) if nl else None,
        }
        print(json.dumps(out, indent=2))
        return 0
    except Exception as exc:  # never crash -> structured error
        print(json.dumps({"token_ok": True, "error": f"{type(exc).__name__}: {exc}"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
