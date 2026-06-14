#!/usr/bin/env python3
"""auth_complete.py -- phase 2 of a non-interactive Schwab OAuth login.

Reads the AuthContext saved by ``auth_begin.py`` and the redirected URL the user
pasted (from ``.redirect_url.txt`` or argv[1]), then uses schwab-py's
``client_from_received_url`` to exchange the authorization code for a token,
write it to ``SCHWAB_TOKEN_PATH`` in the library's exact metadata-wrapped format,
lock it to 0600, and verify it by listing the linked account(s).

Usage:
    python auth_complete.py                      # reads .redirect_url.txt
    python auth_complete.py "https://127.0.0.1/?code=..."
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

from rich.panel import Panel
from rich.text import Text

from schwab.auth import AuthContext, client_from_received_url

from config import load_settings, mask_account_number, unwrap
from render import console

AUTH_CONTEXT_PATH = ".auth_context.json"
REDIRECT_URL_PATH = ".redirect_url.txt"


def _load_received_url() -> str:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1].strip()
    p = Path(REDIRECT_URL_PATH)
    if not p.exists():
        raise SystemExit(
            f"No redirect URL provided. Pass it as an argument or write it to "
            f"{REDIRECT_URL_PATH}."
        )
    return p.read_text().strip()


def main() -> int:
    settings = load_settings()

    ctx_path = Path(AUTH_CONTEXT_PATH)
    if not ctx_path.exists():
        raise SystemExit(
            f"{AUTH_CONTEXT_PATH} not found. Run auth_begin.py first to start the flow."
        )
    saved = json.loads(ctx_path.read_text())
    auth_context = AuthContext(
        callback_url=saved["callback_url"],
        authorization_url=None,  # not needed for the token exchange
        state=saved["state"],
    )

    received_url = _load_received_url()

    token_path = str(Path(settings.token_path).expanduser())

    def token_write_func(token, *args, **kwargs):
        # client_from_received_url wraps this with TokenMetadata; we just persist
        # whatever object it hands us as JSON, owner-only.
        os.umask(0o077)
        with open(token_path, "w") as handle:
            json.dump(token, handle)
        os.chmod(token_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600

    client = client_from_received_url(
        settings.api_key,
        settings.app_secret,
        auth_context,
        received_url,
        token_write_func,
    )

    # Verify the token works by listing the linked account(s) (masked).
    data = unwrap(client.get_account_numbers(), context="Verifying token")
    accounts = data if isinstance(data, list) else []
    body = Text()
    body.append("Token exchange succeeded and was written.\n\n", style="bold green")
    body.append("Token file   ", style="dim")
    body.append(token_path + "\n")
    body.append("Linked account(s):\n", style="bold")
    for entry in accounts:
        body.append("  • " + mask_account_number(entry.get("accountNumber", "")) + "\n")
    console.print(Panel(body, title="✓ Authenticated", border_style="green", expand=False))

    # Clean up transient artifacts (CSRF state + one-time auth code).
    for transient in (AUTH_CONTEXT_PATH, REDIRECT_URL_PATH):
        try:
            os.remove(transient)
        except FileNotFoundError:
            pass

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # surface guidance, not a traceback
        console.print(
            Panel(
                Text(
                    "Token exchange did not complete.\n\n"
                    f"{type(exc).__name__}: {exc}\n\n"
                    "Most common cause: the pasted redirect URL was incomplete, or "
                    "the login session expired. Re-run auth_begin.py and try again.",
                    style="white",
                ),
                title="OAuth completion failed",
                border_style="red",
                expand=False,
            )
        )
        sys.exit(1)
