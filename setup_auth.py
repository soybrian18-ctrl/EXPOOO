#!/usr/bin/env python3
"""setup_auth.py -- first-time Schwab OAuth setup, step by step.

Run once:

    python setup_auth.py

The Schwab API requires a manual browser redirect on the very first login. This
script walks you through it using schwab-py's built-in manual OAuth flow
(``client_from_manual_flow``): it prints an authorization link, you log in and
approve in your browser, then paste the redirected URL back here. schwab-py
exchanges the code for a token, writes it to ``SCHWAB_TOKEN_PATH``, and from
then on refreshes the access token automatically.

If your credentials are not yet in ``.env`` this script will prompt for them and
(optionally) write them to a private ``.env`` file for you.
"""

from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path
from typing import Optional

from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.text import Text

from dotenv import load_dotenv
from schwab.auth import client_from_manual_flow

from config import (
    Settings,
    load_settings,
    mask_account_number,
    unwrap,
)
from render import console

ENV_PATH = ".env"
DEFAULT_CALLBACK = "https://127.0.0.1"
DEFAULT_TOKEN_PATH = "./schwab_token.json"


# ---------------------------------------------------------------------------
# Credential collection
# ---------------------------------------------------------------------------


def _persist_env(path: str, updates: dict[str, str]) -> None:
    """Merge ``updates`` into ``.env`` and lock the file to 0600."""
    p = Path(path)
    lines = p.read_text().splitlines() if p.exists() else []
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        match = re.match(r"\s*([A-Z0-9_]+)\s*=", line)
        if match and match.group(1) in updates:
            key = match.group(1)
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")

    # Create/truncate with owner-only permissions from the start.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write("\n".join(out) + "\n")
    os.chmod(path, 0o600)


def _prompt(label: str, *, secret: bool = False, default: Optional[str] = None) -> str:
    return Prompt.ask(
        Text(label, style="bold"),
        password=secret,
        default=default,
        show_default=default is not None,
    ).strip()


def ensure_credentials() -> Settings:
    """Return validated settings, prompting for anything missing from .env."""
    load_dotenv(override=False)

    collected: dict[str, str] = {}

    if not os.environ.get("SCHWAB_API_KEY", "").strip():
        collected["SCHWAB_API_KEY"] = _prompt("Schwab App Key (API key)", secret=True)
    if not os.environ.get("SCHWAB_APP_SECRET", "").strip():
        collected["SCHWAB_APP_SECRET"] = _prompt("Schwab App Secret", secret=True)
    if not os.environ.get("SCHWAB_CALLBACK_URL", "").strip():
        collected["SCHWAB_CALLBACK_URL"] = _prompt(
            "Callback URL (must match your Schwab app exactly)",
            default=DEFAULT_CALLBACK,
        )
    if not os.environ.get("SCHWAB_TOKEN_PATH", "").strip():
        # Not secret; only prompt if neither env nor default is desired.
        collected["SCHWAB_TOKEN_PATH"] = _prompt(
            "Token file path", default=DEFAULT_TOKEN_PATH
        )

    # Make the freshly collected values visible to load_settings().
    for key, value in collected.items():
        os.environ[key] = value

    # Persist only the non-secret-safe set if the user agrees. We still offer to
    # save secrets because a local, git-ignored, 0600 .env is the intended store.
    if collected:
        if Confirm.ask(
            Text(
                f"Save these values to {ENV_PATH} (git-ignored, chmod 600)?",
                style="bold",
            ),
            default=True,
        ):
            _persist_env(ENV_PATH, collected)
            console.print(f"[green]✓[/] Wrote {ENV_PATH} (permissions 600).")
        else:
            console.print(
                "[yellow]Not saved.[/] Values are set for this run only."
            )

    return load_settings()


# ---------------------------------------------------------------------------
# Guided OAuth flow
# ---------------------------------------------------------------------------


def _intro_panel(settings: Settings) -> None:
    body = Text()
    body.append("This will link your Schwab account via OAuth 2.0.\n\n", style="bold")
    body.append("App Key      ", style="dim")
    body.append(settings.masked_api_key() + "\n")
    body.append("Callback URL ", style="dim")
    body.append(settings.callback_url + "\n")
    body.append("Token file   ", style="dim")
    body.append(settings.token_path + "\n")
    console.print(Panel(body, title="Schwab OAuth setup", border_style="cyan", expand=False))


def _steps_panel(settings: Settings) -> None:
    steps = Text()
    steps.append("What happens next\n\n", style="bold")
    steps.append("1. ", style="bold cyan")
    steps.append("schwab-py prints an authorization link below.\n")
    steps.append("2. ", style="bold cyan")
    steps.append("Open it in your browser and log in to Schwab; approve access.\n")
    steps.append("3. ", style="bold cyan")
    steps.append(
        f"Schwab redirects you to {settings.callback_url}/?code=...  Your browser "
        "will likely show a 'site can't be reached' page — that is EXPECTED, "
        "because nothing is listening on the loopback address.\n"
    )
    steps.append("4. ", style="bold cyan")
    steps.append(
        "Copy the FULL URL from the browser address bar and paste it back here "
        "when prompted.\n"
    )
    console.print(Panel(steps, title="Manual browser redirect", border_style="blue", expand=False))


def _lock_down_token(token_path: str) -> None:
    p = Path(token_path).expanduser()
    if p.exists():
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)  # 0600


def _verify(client) -> None:
    data = unwrap(client.get_account_numbers(), context="Verifying token")
    accounts = data if isinstance(data, list) else []
    body = Text()
    body.append("Token verified. Linked account(s):\n", style="bold green")
    for entry in accounts:
        body.append("  • " + mask_account_number(entry.get("accountNumber", "")) + "\n")
    console.print(Panel(body, title="✓ Success", border_style="green", expand=False))


def main() -> int:
    console.print()
    settings = ensure_credentials()
    _intro_panel(settings)

    token_path = Path(settings.token_path).expanduser()
    if token_path.exists():
        console.print(
            f"[yellow]A token already exists at {token_path}.[/]"
        )
        if not Confirm.ask(
            Text("Re-run the login flow and overwrite it?", style="bold"),
            default=False,
        ):
            console.print("[green]Keeping existing token. Nothing to do.[/]")
            return 0

    _steps_panel(settings)
    console.print(
        "[bold]Starting the manual OAuth flow — follow schwab-py's prompt below.[/]\n"
    )

    try:
        client = client_from_manual_flow(
            api_key=settings.api_key,
            app_secret=settings.app_secret,
            callback_url=settings.callback_url,
            token_path=str(token_path),
        )
    except Exception as exc:  # interactive, one-off: present guidance, don't dump a trace
        console.print(
            Panel(
                Text(
                    "OAuth flow did not complete.\n\n"
                    f"{type(exc).__name__}: {exc}\n\n"
                    "Common causes: the callback URL does not EXACTLY match your "
                    "Schwab app, the App Key/Secret are wrong, or the pasted URL "
                    "was incomplete. Fix and run setup_auth.py again.",
                    style="white",
                ),
                title="OAuth setup failed",
                border_style="red",
                expand=False,
            )
        )
        return 1

    _lock_down_token(str(token_path))
    _verify(client)

    notes = Text()
    notes.append("You're all set.\n\n", style="bold green")
    notes.append("• Access tokens last ~30 min and refresh automatically.\n")
    notes.append("• The refresh token lasts ~7 days; re-run this script when it lapses.\n")
    notes.append("• Next: 'python portfolio.py' or 'python stop_check.py'.\n")
    console.print(Panel(notes, title="Next steps", border_style="cyan", expand=False))
    console.print()
    return 0


if __name__ == "__main__":
    # setup_auth has its own try/except around the interactive flow; a thin guard
    # here keeps Ctrl-C clean.
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Setup cancelled.[/]")
        sys.exit(130)
