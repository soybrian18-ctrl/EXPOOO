"""Shared rich rendering helpers and the CLI error handler.

All terminal output in this project goes through ``rich`` -- no bare ``print``
statements. Centralising the console and the formatters keeps portfolio.py and
stop_check.py visually consistent and DRY.
"""

from __future__ import annotations

from typing import Callable, Optional

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from config import (
    AUTH_REFRESH_ERRORS,
    ApiError,
    AuthError,
    ConfigError,
    MonitorError,
)

console = Console()


# ---------------------------------------------------------------------------
# Number / money formatting
# ---------------------------------------------------------------------------


def fmt_money(value: Optional[float], *, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    body = f"${abs(value):,.2f}"
    if value < 0:
        return f"-{body}"
    return f"+{body}" if signed else body


def fmt_pct(value: Optional[float], *, signed: bool = True) -> str:
    if value is None:
        return "n/a"
    body = f"{abs(value):,.2f}%"
    if value < 0:
        return f"-{body}"
    return f"+{body}" if signed else body


def fmt_shares(qty: Optional[float]) -> str:
    if qty is None:
        return "n/a"
    if float(qty).is_integer():
        return f"{int(qty):,}"
    return f"{qty:,.4f}".rstrip("0").rstrip(".")


def pl_color(value: Optional[float]) -> str:
    if value is None:
        return "white"
    return "green" if value >= 0 else "red"


def pl_text(value: Optional[float], *, is_pct: bool = False) -> Text:
    """Coloured, sign-prefixed P/L cell."""
    label = fmt_pct(value) if is_pct else fmt_money(value, signed=True)
    return Text(label, style=f"bold {pl_color(value)}")


def tif_text(tif: Optional[str], *, is_day: bool) -> Text:
    """TIF cell -- a bright red warning flag when the order is DAY, not GTC."""
    if is_day:
        return Text(" DAY ⚠ ", style="bold white on red")
    label = "GTC" if tif == "GOOD_TILL_CANCEL" else (tif or "n/a")
    return Text(label, style="green" if tif == "GOOD_TILL_CANCEL" else "yellow")


# ---------------------------------------------------------------------------
# CLI error handling
# ---------------------------------------------------------------------------


def _panel(message: str, *, title: str, style: str = "red") -> None:
    console.print(Panel(Text(message), title=title, border_style=style, expand=False))


def run_cli(main: Callable[[], Optional[int]]) -> int:
    """Run a script ``main`` and translate known failures into clean output.

    Returns a process exit code:
      0  success
      1  Schwab API / network failure
      2  configuration or authentication problem
      130 interrupted
    """
    try:
        return main() or 0
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/]")
        return 130
    except ConfigError as exc:
        _panel(str(exc), title="Configuration error")
        return 2
    except AuthError as exc:
        _panel(str(exc), title="Authentication required")
        return 2
    except AUTH_REFRESH_ERRORS as exc:  # empty tuple simply never matches
        _panel(
            "Automatic token refresh failed. The refresh token has most likely "
            "expired (~7 day lifetime).\n\n"
            "Re-run 'python setup_auth.py' to re-authenticate.\n\n"
            f"Detail: {exc}",
            title="Token refresh failed",
        )
        return 2
    except ApiError as exc:
        _panel(str(exc), title=f"Schwab API error ({exc.status_code})")
        return 1
    except httpx.HTTPError as exc:
        _panel(
            f"Network error communicating with Schwab: {exc}",
            title="Network error",
        )
        return 1
    except MonitorError as exc:  # any other deliberate error
        _panel(str(exc), title="Error")
        return 1
