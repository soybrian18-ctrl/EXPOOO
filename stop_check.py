#!/usr/bin/env python3
"""stop_check.py -- a visually rich protective-stop health check.

Run directly:

    python stop_check.py

Renders, like a small trading terminal:
  * a header panel with the check timestamp and account;
  * a "Positions at Risk" table listing every open position with its current
    price, stop price, and percentage distance to the stop;
  * a bright-green ALL CLEAR banner when nothing is wrong, or one red warning
    panel per issue: a position within 5% of (or through) its stop, or a stop
    order whose time-in-force is DAY instead of GTC.

Exit codes: 0 = all clear, 3 = one or more flags triggered (handy for cron /
alerting), 1/2 = API or configuration errors.

All Schwab access is via schwab-py; the token is refreshed automatically.
"""

from __future__ import annotations

import sys
from datetime import datetime

from rich import box
from rich.align import Align
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
from render import console, fmt_money, fmt_pct, run_cli, tif_text

FLAGS_EXIT_CODE = 3


def _header(account_display: str, threshold_pct: float) -> Panel:
    now = datetime.now().astimezone()
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", justify="left")
    grid.add_column(justify="left")
    grid.add_row("Account", Text(account_display, style="bold white"))
    grid.add_row(
        "Check time",
        Text(now.strftime("%A, %b %d, %Y  %I:%M:%S %p %Z").lstrip("0"), style="white"),
    )
    grid.add_row("Proximity threshold", Text(f"{threshold_pct:g}%", style="white"))
    return Panel(
        grid,
        title=Text("🛡  STOP-LOSS HEALTH CHECK", style="bold cyan"),
        border_style="cyan",
        box=box.DOUBLE,
        expand=False,
    )


def _nearest_stops(report: analysis.StopReport) -> dict[str, analysis.StopEvaluation]:
    """Map each symbol that has a position to its most-at-risk stop evaluation."""
    out: dict[str, analysis.StopEvaluation] = {}
    for ev in report.evaluations:
        if not ev.has_position:
            continue
        cur = out.get(ev.symbol)
        if cur is None or (
            ev.proximity_pct is not None
            and (cur.proximity_pct is None or ev.proximity_pct < cur.proximity_pct)
        ):
            out[ev.symbol] = ev
    return out


def _at_risk_table(
    rows: list[analysis.PositionRow], report: analysis.StopReport
) -> Table:
    table = Table(
        title="Positions at Risk",
        title_style="bold",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
    )
    table.add_column("Symbol", style="bold")
    table.add_column("Side")
    table.add_column("Current", justify="right")
    table.add_column("Stop", justify="right")
    table.add_column("Distance", justify="right")
    table.add_column("TIF", justify="center")
    table.add_column("Status")

    if not rows:
        table.add_row("—", "—", "—", "—", "—", "—", Text("no open positions", style="yellow"))
        return table

    stops = _nearest_stops(report)
    for r in sorted(rows, key=lambda x: x.symbol):
        side = "SHORT" if r.is_short else "LONG"
        current = fmt_money(r.mark)
        ev = stops.get(r.symbol)

        if ev is None:
            stop_cell = Text("— none —", style="yellow")
            dist_cell = Text("no stop", style="yellow")
            tif_cell = Text("—", style="dim")
            status = Text("⚠ UNPROTECTED", style="bold yellow")
            row_style = "yellow"
        else:
            stop_cell = Text(fmt_money(ev.stop_price))
            if ev.proximity_pct is None:
                dist_cell = Text("n/a", style="dim")
            else:
                dist_cell = Text(
                    fmt_pct(ev.proximity_pct),
                    style="bold red" if ev.near_flag else "green",
                )
            tif_cell = tif_text(ev.tif, is_day=ev.day_flag)
            breached = ev.proximity_pct is not None and ev.proximity_pct < 0
            if breached:
                status = Text("⚠ STOP BREACHED", style="bold white on red")
                row_style = "red"
            elif ev.near_flag:
                status = Text("⚠ AT RISK", style="bold white on red")
                row_style = "red"
            elif ev.day_flag:
                status = Text("⚠ DAY TIF", style="bold white on red")
                row_style = "red"
            else:
                status = Text("✓ OK", style="green")
                row_style = "green"

        table.add_row(
            r.symbol, side, current, stop_cell, dist_cell, tif_cell, status, style=row_style
        )
    return table


def _warning_panels(report: analysis.StopReport) -> list[Panel]:
    """One red panel per issue: near/breached stop, or DAY-TIF stop order."""
    panels: list[Panel] = []

    for ev in sorted(
        (e for e in report.evaluations if e.near_flag), key=lambda e: e.symbol
    ):
        breached = ev.proximity_pct is not None and ev.proximity_pct < 0
        if breached:
            title = f"⚠  STOP BREACHED — {ev.symbol}"
            msg = (
                f"Mark {fmt_money(ev.mark)} has moved THROUGH the stop at "
                f"{fmt_money(ev.stop_price)} ({fmt_pct(ev.proximity_pct)}). "
                "The protective stop should already have triggered — verify the fill."
            )
        else:
            title = f"⚠  WITHIN {report.threshold_pct:g}% OF STOP — {ev.symbol}"
            msg = (
                f"Mark {fmt_money(ev.mark)} is only {fmt_pct(ev.proximity_pct)} from the "
                f"stop at {fmt_money(ev.stop_price)} (threshold {report.threshold_pct:g}%). "
                "A small adverse move will trigger it."
            )
        panels.append(
            Panel(Text(msg, style="bold white"), title=title, border_style="red", expand=False)
        )

    for ev in sorted(
        (e for e in report.evaluations if e.day_flag), key=lambda e: e.symbol
    ):
        order_ref = f" (#{ev.order_id})" if ev.order_id is not None else ""
        msg = (
            f"The stop order{order_ref} for {ev.symbol} uses DAY time-in-force. It will "
            "expire at the close and leave the position unprotected overnight. "
            "Convert it to GTC."
        )
        panels.append(
            Panel(
                Text(msg, style="bold white"),
                title=f"⚠  DAY TIF — SHOULD BE GTC — {ev.symbol}",
                border_style="red",
                expand=False,
            )
        )

    return panels


def _all_clear_banner(report: analysis.StopReport) -> Panel:
    txt = Text()
    txt.append("✓   ALL CLEAR   ✓\n", style="bold green")
    txt.append(
        f"No stop is within {report.threshold_pct:g}% of the mark, "
        "and every working stop is GTC.",
        style="green",
    )
    return Panel(Align.center(txt), border_style="green", box=box.DOUBLE, expand=False)


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

    positions = securities_account.get("positions", [])
    rows = analysis.position_rows(positions)
    report = analysis.analyze_stops(
        positions,
        raw_orders,
        threshold_pct=analysis.DEFAULT_STOP_PROXIMITY_PCT,
    )

    console.print()
    console.print(_header(account.display, report.threshold_pct))
    console.print()
    console.print(_at_risk_table(rows, report))
    console.print()

    warnings = _warning_panels(report)
    if warnings:
        console.print(
            Panel(
                Text(
                    f"{len(warnings)} issue(s) require attention — review below.",
                    style="bold white",
                ),
                title="⚠  ACTION REQUIRED",
                border_style="red",
                expand=False,
            )
        )
        console.print()
        for panel in warnings:
            console.print(panel)
            console.print()
    else:
        console.print(_all_clear_banner(report))
        console.print()

    if report.positions_without_stop:
        console.print(
            Panel(
                Text(
                    "No working stop order found for: "
                    + ", ".join(report.positions_without_stop)
                    + ".",
                    style="yellow",
                ),
                title="Advisory — unprotected positions",
                border_style="yellow",
                expand=False,
            )
        )
        console.print()

    return FLAGS_EXIT_CODE if report.red_flags else 0


if __name__ == "__main__":
    sys.exit(run_cli(main))
