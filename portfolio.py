#!/usr/bin/env python3
"""portfolio.py -- a visually rich terminal snapshot of a Schwab trading account.

Run directly:

    python portfolio.py

Renders, like a small trading terminal:
  * a header panel with account, date, time, and net liquidating value in
    oversized "marquee" digits;
  * a positions table whose rows are tinted green (winners) or red (losers);
  * a capital-deployment progress bar (deployed vs. cash) colour-coded against
    the 60-70% target band;
  * a working-orders table with GTC flagged green and DAY flagged bright red;
  * a bottom summary panel with total open P/L coloured by direction.

All Schwab access is via schwab-py; the token is refreshed automatically.
"""

from __future__ import annotations

import sys
from datetime import datetime

from rich import box
from rich.columns import Columns
from rich.panel import Panel
from rich.progress_bar import ProgressBar
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
    big_text,
    console,
    fmt_money,
    fmt_pct,
    fmt_shares,
    pl_color,
    pl_text,
    run_cli,
    tif_text,
)

# Rules-of-the-experiment deployment band, used only to colour the bar.
TARGET_DEPLOY_LOW = 60.0
TARGET_DEPLOY_HIGH = 70.0


def _header(account_display: str, account_type: str, net_liq) -> Panel:
    now = datetime.now().astimezone()

    meta = Table.grid(padding=(0, 2))
    meta.add_column(style="dim", justify="left")
    meta.add_column(justify="left")
    meta.add_row("Account", Text(f"{account_display}  ({account_type})", style="bold white"))
    meta.add_row("Date", Text(now.strftime("%A, %b %d, %Y"), style="white"))
    meta.add_row("Time", Text(now.strftime("%I:%M:%S %p %Z").lstrip("0"), style="white"))

    netliq = Table.grid()
    netliq.add_column(justify="right")
    netliq.add_row(Text("NET LIQUIDATING VALUE  ($)", style="bold cyan"))
    if net_liq is not None:
        netliq.add_row(big_text(f"{net_liq:,.2f}", style="bold green"))
    else:
        netliq.add_row(Text("n/a", style="bold red"))

    outer = Table.grid(expand=True, padding=(0, 4))
    outer.add_column(justify="left", ratio=1)
    outer.add_column(justify="right")
    outer.add_row(meta, netliq)

    return Panel(
        outer,
        title=Text("SCHWAB ACCOUNT MONITOR", style="bold cyan"),
        border_style="cyan",
        box=box.DOUBLE,
        expand=True,
    )


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
        # Whole-row tint: green for winners, red for losers, default for flat.
        if r.pl_dollars > 0:
            row_style = "green"
        elif r.pl_dollars < 0:
            row_style = "red"
        else:
            row_style = None
        table.add_row(
            r.symbol,
            fmt_shares(r.quantity),
            fmt_money(r.avg_price),
            fmt_money(r.mark),
            fmt_money(r.market_value),
            pl_text(r.pl_dollars),
            pl_text(r.pl_pct, is_pct=True),
            style=row_style,
        )
    return table


def _deployment_panel(deployed, deployed_pct, net_liq, cash, buying_power) -> Panel:
    pct = deployed_pct or 0.0
    cash_pct = (cash / net_liq * 100.0) if (cash is not None and net_liq) else None

    if pct > TARGET_DEPLOY_HIGH:
        bar_color, band_note = "red", "OVER the 60–70% target band"
    elif pct < TARGET_DEPLOY_LOW:
        bar_color, band_note = "yellow", "UNDER the 60–70% target band"
    else:
        bar_color, band_note = "green", "within the 60–70% target band"

    bar = ProgressBar(
        total=100.0,
        completed=min(max(pct, 0.0), 100.0),
        width=54,
        complete_style=bar_color,
        finished_style=bar_color,
        style="grey30",
    )

    legend = Text()
    legend.append("█ ", style=bar_color)
    legend.append("Deployed ", style="bold")
    legend.append(f"{fmt_money(deployed)}  {fmt_pct(pct, signed=False)}", style=f"bold {bar_color}")
    legend.append("        ")
    legend.append("█ ", style="grey50")
    legend.append("Cash ", style="bold")
    cash_str = fmt_money(cash)
    if cash_pct is not None:
        cash_str += f"  {fmt_pct(cash_pct, signed=False)}"
    legend.append(cash_str, style="bold cyan")

    details = Table.grid(padding=(0, 3))
    details.add_column(style="dim")
    details.add_column(justify="right")
    details.add_row("Buying power", Text(fmt_money(buying_power), style="bold green"))

    body = Table.grid()
    body.add_column()
    body.add_row(bar)
    body.add_row(legend)
    body.add_row(Text(f"Currently {band_note}.", style="dim"))
    body.add_row(Text(""))
    body.add_row(details)

    return Panel(body, title="Capital Deployment", border_style="blue", expand=False)


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
        side_style = "green" if (o.instruction or "").startswith("BUY") else "red"
        table.add_row(
            str(o.order_id) if o.order_id is not None else "—",
            o.symbol,
            Text(o.instruction or "—", style=side_style),
            o.order_type or "—",
            fmt_shares(o.quantity),
            fmt_money(o.limit_price) if o.limit_price is not None else "—",
            fmt_money(o.stop_price) if o.stop_price is not None else "—",
            tif_text(o.tif, is_day=o.is_day),
        )
    return table


def _summary_panel(rows: list[analysis.PositionRow]) -> Panel:
    total_pl = sum(r.pl_dollars for r in rows)
    total_cost = sum(abs(r.avg_price * r.quantity) for r in rows)
    total_pct = (total_pl / total_cost * 100.0) if total_cost else None
    color = pl_color(total_pl)

    body = Text()
    body.append("Total Open P/L    ", style="dim")
    body.append(fmt_money(total_pl, signed=True), style=f"bold {color}")
    if total_pct is not None:
        body.append("    " + fmt_pct(total_pct), style=f"bold {color}")
    arrow = "▲" if total_pl > 0 else ("▼" if total_pl < 0 else "■")
    body.append(f"   {arrow}", style=f"bold {color}")

    return Panel(
        body,
        title=Text("SUMMARY — OPEN P/L", style=f"bold {color}"),
        border_style=color,
        expand=False,
    )


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
                _deployment_panel(
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
    console.print(_summary_panel(rows))
    console.print()
    return 0


if __name__ == "__main__":
    sys.exit(run_cli(main))
