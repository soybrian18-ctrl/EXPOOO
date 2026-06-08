#!/usr/bin/env python3
"""portfolio.py -- a clean terminal snapshot of a Schwab trading account.

Run directly:

    python portfolio.py

Shows net liquidating value, every open position with P/L, deployed capital,
cash / buying power, and all working orders -- with a bright red flag on any
order whose time-in-force is DAY instead of GTC.

All Schwab access is via schwab-py; the token is refreshed automatically.
"""

from __future__ import annotations

import sys

from rich import box
from rich.columns import Columns
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import analysis
from config import (
    build_client,
    fetch_securities_account,
    fetch_working_orders,
    instance_lock,
    load_settings,
    resolve_account,
)
from render import (
    console,
    fmt_money,
    fmt_pct,
    fmt_shares,
    pl_text,
    run_cli,
    tif_text,
)


def _header(account_display: str, account_type: str, net_liq) -> Panel:
    title = Text("SCHWAB ACCOUNT MONITOR", style="bold cyan")
    body = Text()
    body.append("Account   ", style="dim")
    body.append(f"{account_display}  ({account_type})\n")
    body.append("Net Liq   ", style="dim")
    body.append(fmt_money(net_liq), style="bold white")
    return Panel(body, title=title, border_style="cyan", expand=False)


def _positions_table(rows: list[analysis.PositionRow]) -> Table:
    table = Table(
        title="Open Positions",
        title_style="bold",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
    )
    table.add_column("Symbol", style="bold")
    table.add_column("Shares", justify="right")
    table.add_column("Avg Cost", justify="right")
    table.add_column("Mark", justify="right")
    table.add_column("Mark Value", justify="right")
    table.add_column("Open P/L $", justify="right")
    table.add_column("Open P/L %", justify="right")

    if not rows:
        table.add_row("—", "—", "—", "—", "—", "—", "—")
        return table

    for r in sorted(rows, key=lambda x: x.symbol):
        table.add_row(
            r.symbol,
            fmt_shares(r.quantity),
            fmt_money(r.avg_price),
            fmt_money(r.mark),
            fmt_money(r.market_value),
            pl_text(r.pl_dollars),
            pl_text(r.pl_pct, is_pct=True),
        )
    return table


def _capital_panel(
    deployed: float, deployed_pct, net_liq, cash, buying_power
) -> Panel:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="left", style="dim")
    grid.add_column(justify="right")

    pct_label = fmt_pct(deployed_pct, signed=False) if deployed_pct is not None else "n/a"
    grid.add_row("Deployed capital", Text(fmt_money(deployed), style="bold"))
    grid.add_row("  as % of account", Text(pct_label, style="bold"))
    grid.add_row("Cash balance", Text(fmt_money(cash), style="bold"))
    grid.add_row("Buying power", Text(fmt_money(buying_power), style="bold green"))
    return Panel(grid, title="Capital", border_style="blue", expand=False)


def _orders_table(rows: list[analysis.OrderRow]) -> Table:
    table = Table(
        title="Working Orders",
        title_style="bold",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
    )
    table.add_column("Order #", justify="right")
    table.add_column("Symbol", style="bold")
    table.add_column("Side")
    table.add_column("Type")
    table.add_column("Qty", justify="right")
    table.add_column("Limit", justify="right")
    table.add_column("Stop", justify="right")
    table.add_column("TIF", justify="center")

    if not rows:
        table.add_row("—", "—", "—", "—", "—", "—", "—", "—")
        return table

    for o in rows:
        table.add_row(
            str(o.order_id) if o.order_id is not None else "—",
            o.symbol,
            o.instruction or "—",
            o.order_type or "—",
            fmt_shares(o.quantity),
            fmt_money(o.limit_price) if o.limit_price is not None else "—",
            fmt_money(o.stop_price) if o.stop_price is not None else "—",
            tif_text(o.tif, is_day=o.is_day),
        )
    return table


def main() -> int:
    settings = load_settings()
    with instance_lock(settings.token_path) as locked:
        if locked is False:
            console.print(
                "[yellow]Another monitor instance holds the token lock; "
                "proceeding without it.[/]"
            )
        client = build_client(settings)
        account = resolve_account(client, settings)
        securities_account = fetch_securities_account(client, account.account_hash)
        raw_orders = fetch_working_orders(client, account.account_hash)

    rows = analysis.position_rows(securities_account.get("positions", []))
    summary = analysis.account_summary(securities_account)
    deployed = analysis.deployed_capital(rows)
    deployed_pct = analysis.deployed_pct(deployed, summary.net_liquidating_value)
    orders = analysis.working_order_rows(raw_orders)

    console.print()
    console.print(
        _header(
            account.display,
            securities_account.get("type", "—"),
            summary.net_liquidating_value,
        )
    )
    console.print()
    console.print(_positions_table(rows))
    console.print()
    console.print(
        Columns(
            [
                _capital_panel(
                    deployed,
                    deployed_pct,
                    summary.net_liquidating_value,
                    summary.cash_balance,
                    summary.buying_power,
                )
            ]
        )
    )
    console.print()
    console.print(_orders_table(orders))

    day_orders = [o for o in orders if o.is_day]
    if day_orders:
        console.print()
        console.print(
            Panel(
                Text(
                    f"{len(day_orders)} working order(s) use DAY time-in-force and "
                    "will expire at the close. Convert to GTC if they are meant to "
                    "persist.",
                    style="bold white",
                ),
                title="⚠  DAY-TIF WARNING",
                border_style="red",
                expand=False,
            )
        )
    console.print()
    return 0


if __name__ == "__main__":
    sys.exit(run_cli(main))
