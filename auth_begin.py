#!/usr/bin/env python3
"""auth_begin.py -- phase 1 of a non-interactive Schwab OAuth login.

Generates the Schwab authorization URL using schwab-py's webapp-flow helper
(``get_auth_context``), persists the resulting AuthContext (callback URL + CSRF
state) to a local, git-ignored file, and automatically opens the URL in the
default browser. Credentials are read from ``.env`` via the project's own
``load_settings`` -- nothing secret is passed on the command line.

After logging in and approving, the redirected URL is handed to
``auth_complete.py`` which performs the token exchange.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

from schwab.auth import get_auth_context

from config import load_settings
from render import console

AUTH_CONTEXT_PATH = ".auth_context.json"


def _open_in_browser(url: str) -> bool:
    """Open ``url`` in the default browser. Returns True on a clean dispatch."""
    try:
        system = platform.system()
        if system == "Darwin":
            subprocess.run(["open", url], check=True)
        elif system == "Windows":  # pragma: no cover - platform dependent
            os.startfile(url)  # type: ignore[attr-defined]
        else:  # pragma: no cover - platform dependent
            subprocess.run(["xdg-open", url], check=True)
        return True
    except Exception:
        return False


def main() -> int:
    settings = load_settings()

    auth_context = get_auth_context(settings.api_key, settings.callback_url)

    # Persist only the non-secret AuthContext fields (callback URL + CSRF state)
    # so auth_complete.py can reconstruct it for the token exchange. 0600.
    fd = os.open(AUTH_CONTEXT_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(
            {
                "callback_url": auth_context.callback_url,
                "state": auth_context.state,
            },
            handle,
        )
    os.chmod(AUTH_CONTEXT_PATH, 0o600)

    opened = _open_in_browser(auth_context.authorization_url)

    console.print()
    console.print("[bold cyan]Schwab authorization URL generated.[/]")
    if opened:
        console.print("[green]✓[/] Opened it in your default browser.")
    else:
        console.print("[yellow]Could not auto-open the browser. Open this URL manually:[/]")
    console.print()
    console.print(auth_context.authorization_url)
    console.print()
    console.print(
        "After approving access, Schwab redirects to "
        f"[bold]{settings.callback_url}/?code=...[/] (the page will look broken — "
        "that's expected). Copy the FULL address-bar URL and run auth_complete.py."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # surface guidance, not a traceback
        console.print(f"[red]auth_begin failed:[/] {type(exc).__name__}: {exc}")
        sys.exit(1)
