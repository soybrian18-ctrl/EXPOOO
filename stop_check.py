#!/usr/bin/env python3
"""stop_check.py -- protective-stop health check for a Schwab account.

Run directly:

    python stop_check.py

For every open position and its working stop order it:
  * flags any stop where the current mark is within 5% of the stop price, and
  * flags any stop whose time-in-force is DAY instead of GTC.
If nothing is flagged it prints a clean all-clear message.

Exit codes: 0 = all clear, 3 = one or more flags triggered (handy for cron /
alerting), 1/2 = API or configuration errors.

All Schwab access is via schwab-py; the token is refreshed automatically.
"""

from __future__ import annotations

import sys

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import analysis
from config import (
    build_client,
    fetch_securities_account,
    fetch_working_orders,
    load_settings,
    resolve_account,
)
from render import console, fmt_money, fmt_pct, run_cli, tif_text

FLAGS_EXIT_CODE = 3


def _alert_text(ev: analysis.StopEvaluation, threshold_pct: float) -> Text:
    parts: list[str] = []
    if ev.near_flag:
        if ev.proximity_pct is not None and ev.proximity_pct < 0:
            parts.append("STOP BREACHED")
        else:
            parts.append(f"WITHIN {threshold_pct:g}%")
    if ev.day_flag:
        parts.append("DAY TIF")
    if not parts:
        return Text("clear", style="green")
    return Text("⚠ " + " + ".join(parts), style="bold white on red")


def _stops_table(report: analysis.StopReport) -> Table:
    table = Table(
        title="Working Stop Orders",
        title_style="bold",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
    )
    table.add_column("Symbol", style="bold")
    table.add_column("Side")
    table.add_column("Mark", justify="right")
    table.add_column("Stop", justify="right")
    table.add_column("To Stop", justify="right")
    table.add_column("TIF", justify="center")
    table.add_column("Alert")

    if not report.evaluations:
        table.add_row("—", "—", "—", "—", "—", "—", Text("no stops found", style="yellow"))
        return table

    for ev in sorted(report.evaluations, key=lambda e: e.symbol):
        side = "—" if not ev.has_position else ("SHORT" if ev.is_short else "LONG")
        mark = fmt_money(ev.mark) if ev.mark is not None else "n/a"
        to_stop = fmt_pct(ev.proximity_pct) if ev.proximity_pct is not None else "n/a"
        to_stop_style = "red" if ev.near_flag else "white"
        table.add_row(
            ev.symbol,
            side,
            mark,
            fmt_money(ev.stop_price),
            Text(to_stop, style=to_stop_style),
            tif_text(ev.tif, is_day=ev.day_flag),
            _alert_text(ev, report.threshold_pct),
        )
    return table


def _render_summary(report: analysis.StopReport) -> None:
    red = report.red_flags
    if red:
        lines = Text()
        for ev in red:
            reasons = []
            if ev.near_flag:
                if ev.proximity_pct is not None and ev.proximity_pct < 0:
                    reasons.append("mark has breached the stop")
                else:
                    reasons.append(
                        f"mark is {fmt_pct(ev.proximity_pct)} from the stop "
                        f"(threshold {report.threshold_pct:g}%)"
                    )
            if ev.day_flag:
                reasons.append("TIF is DAY, not GTC")
            lines.append(f"  • {ev.symbol}: ", style="bold")
            lines.append("; ".join(reasons) + "\n")
        console.print(
            Panel(
                lines,
                title=f"⚠  {len(red)} STOP WARNING(S)",
                border_style="red",
                expand=False,
            )
        )
    else:
        console.print(
            Panel(
                Text(
                    "ALL CLEAR — no stop is within "
                    f"{report.threshold_pct:g}% of the mark and every working "
                    "stop is GTC.",
                    style="bold green",
                ),
                title="✓  ALL CLEAR",
                border_style="green",
                expand=False,
            )
        )

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


def main() -> int:
    settings = load_settings()
    client = build_client(settings)
    account = resolve_account(client, settings)

    securities_account = fetch_securities_account(client, account.account_hash)
    raw_orders = fetch_working_orders(client, account.account_hash)

    report = analysis.analyze_stops(
        securities_account.get("positions", []),
        raw_orders,
        threshold_pct=analysis.DEFAULT_STOP_PROXIMITY_PCT,
    )

    console.print()
    console.print(
        Panel(
            Text(f"Stop check for account {account.display}", style="bold cyan"),
            border_style="cyan",
            expand=False,
        )
    )
    console.print()
    console.print(_stops_table(report))
    console.print()
    _render_summary(report)
    console.print()

    return FLAGS_EXIT_CODE if report.red_flags else 0


if __name__ == "__main__":
    sys.exit(run_cli(main))
