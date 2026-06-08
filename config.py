"""Configuration, credentials, and schwab-py client construction.

This module is the single place where credentials are read and where the
authenticated schwab-py client is built. It deliberately contains **no**
terminal rendering and makes **no** raw HTTP calls -- every Schwab request is
performed through schwab-py.

Design notes
------------
* Credentials live only in ``.env`` (loaded via python-dotenv). Nothing is
  hardcoded and the loaded secrets are never logged.
* ``client_from_token_file`` returns a client whose session refreshes the
  access token automatically (Schwab access tokens live ~30 minutes). The
  refresh token lives ~7 days; when it lapses the user must re-run
  ``setup_auth.py``. The error paths below surface that clearly.
* schwab-py client methods return a raw ``httpx.Response`` and do **not** raise
  on 4xx/5xx, so :func:`unwrap` is mandatory around every response.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from schwab.auth import client_from_token_file
from schwab.client import Client

# Schwab limits the order-history query window to ~60 days of entered time.
# GTC stops entered earlier than this will not be returned by the endpoint.
ORDER_LOOKBACK_DAYS = 60

# ---------------------------------------------------------------------------
# Error taxonomy
# ---------------------------------------------------------------------------


class MonitorError(Exception):
    """Base class for every error this project raises deliberately."""


class ConfigError(MonitorError):
    """Raised when required configuration / credentials are missing."""


class AuthError(MonitorError):
    """Raised when authentication cannot proceed (e.g. no/invalid token)."""


class ApiError(MonitorError):
    """Raised when Schwab returns a non-success HTTP response."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


# Authlib raises these when an automatic token refresh fails (typically because
# the ~7-day refresh token has expired). Import defensively so a future authlib
# layout change cannot break startup; the resulting tuple is used by the CLI
# error handler to tell the user to re-authenticate.
def _auth_refresh_error_types() -> tuple[type[BaseException], ...]:
    candidates: list[type[BaseException]] = []
    for module, name in (
        ("authlib.integrations.base_client.errors", "OAuthError"),
        ("authlib.oauth2.rfc6749.errors", "OAuth2Error"),
    ):
        try:
            mod = __import__(module, fromlist=[name])
            obj = getattr(mod, name)
            if isinstance(obj, type) and issubclass(obj, BaseException):
                candidates.append(obj)
        except Exception:  # pragma: no cover - defensive import only
            continue
    return tuple(candidates)


AUTH_REFRESH_ERRORS: tuple[type[BaseException], ...] = _auth_refresh_error_types()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

REQUIRED_VARS = ("SCHWAB_API_KEY", "SCHWAB_APP_SECRET", "SCHWAB_CALLBACK_URL")


@dataclass(frozen=True)
class Settings:
    """Immutable view of everything we need from the environment."""

    api_key: str
    app_secret: str
    callback_url: str
    token_path: str
    account_index: int = 0

    @property
    def token_exists(self) -> bool:
        return Path(self.token_path).expanduser().is_file()

    def masked_api_key(self) -> str:
        """API key with the middle redacted, safe to print."""
        key = self.api_key
        if len(key) <= 8:
            return "*" * len(key)
        return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"


def load_settings(*, dotenv_path: Optional[str] = None) -> Settings:
    """Load and validate settings from ``.env`` / the process environment.

    Raises
    ------
    ConfigError
        If any required variable is missing or obviously malformed.
    """
    # ``override=False`` keeps real environment variables authoritative over the
    # file, which is the least-surprising behaviour for CI / container secrets.
    load_dotenv(dotenv_path=dotenv_path, override=False)

    missing = [name for name in REQUIRED_VARS if not os.environ.get(name, "").strip()]
    if missing:
        raise ConfigError(
            "Missing required credential(s): "
            + ", ".join(missing)
            + ".\nAdd them to your .env file (see .env.example) or run "
            "setup_auth.py, which can write them for you."
        )

    api_key = os.environ["SCHWAB_API_KEY"].strip()
    app_secret = os.environ["SCHWAB_APP_SECRET"].strip()
    callback_url = os.environ["SCHWAB_CALLBACK_URL"].strip()
    token_path = os.environ.get("SCHWAB_TOKEN_PATH", "./schwab_token.json").strip()

    if not callback_url.lower().startswith("https://"):
        raise ConfigError(
            f"SCHWAB_CALLBACK_URL must be an https URL (got {callback_url!r}). "
            "Schwab rejects non-https callbacks."
        )

    raw_index = os.environ.get("SCHWAB_ACCOUNT_INDEX", "0").strip() or "0"
    try:
        account_index = int(raw_index)
        if account_index < 0:
            raise ValueError
    except ValueError as exc:
        raise ConfigError(
            f"SCHWAB_ACCOUNT_INDEX must be a non-negative integer (got {raw_index!r})."
        ) from exc

    return Settings(
        api_key=api_key,
        app_secret=app_secret,
        callback_url=callback_url,
        token_path=token_path,
        account_index=account_index,
    )


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------


def build_client(settings: Settings) -> Client:
    """Build a token-backed schwab-py client with automatic refresh.

    Uses ``client_from_token_file`` rather than a login flow so that the
    reporting scripts never block on a browser. If the token file is absent the
    user is told to run ``setup_auth.py`` first.

    Raises
    ------
    AuthError
        If the token file does not exist or cannot be parsed.
    """
    token_path = Path(settings.token_path).expanduser()
    if not token_path.is_file():
        raise AuthError(
            f"No Schwab token found at {token_path}.\n"
            "Run 'python setup_auth.py' once to complete the browser login flow."
        )
    try:
        return client_from_token_file(
            str(token_path),
            api_key=settings.api_key,
            app_secret=settings.app_secret,
        )
    except (ValueError, KeyError) as exc:  # corrupt / incompatible token file
        raise AuthError(
            f"Token file at {token_path} could not be read ({exc}). "
            "Delete it and re-run 'python setup_auth.py'."
        ) from exc


# ---------------------------------------------------------------------------
# Response handling
# ---------------------------------------------------------------------------


def unwrap(resp: httpx.Response, *, context: str) -> Any:
    """Return ``resp.json()`` or raise :class:`ApiError` with useful detail.

    schwab-py hands back the raw response and never raises for HTTP errors, so
    every call site must funnel through here.
    """
    if resp.is_success:
        try:
            return resp.json()
        except ValueError as exc:
            raise ApiError(
                resp.status_code,
                f"{context}: Schwab returned a non-JSON body.",
            ) from exc

    if resp.status_code == 401:
        raise ApiError(
            401,
            f"{context}: Schwab rejected the access token (401 Unauthorized).\n"
            "The refresh token may have expired (~7 day lifetime). "
            "Re-run 'python setup_auth.py' to re-authenticate.",
        )
    if resp.status_code == 403:
        raise ApiError(
            403,
            f"{context}: Forbidden (403). The account may not be enabled for "
            "the Trader API, or the app lacks the required scope.",
        )
    if resp.status_code == 429:
        raise ApiError(
            429,
            f"{context}: Rate limited by Schwab (429). Wait a moment and retry.",
        )

    # Fall back to a trimmed body for any other status.
    body = (resp.text or "").strip().replace("\n", " ")
    if len(body) > 280:
        body = body[:277] + "..."
    raise ApiError(
        resp.status_code,
        f"{context}: Schwab returned HTTP {resp.status_code}. {body}",
    )


# ---------------------------------------------------------------------------
# Account selection
# ---------------------------------------------------------------------------


def mask_account_number(number: str) -> str:
    """Show only the last four digits of an account number."""
    number = str(number)
    if len(number) <= 4:
        return "****"
    return "****" + number[-4:]


@dataclass(frozen=True)
class AccountRef:
    """A resolved account: its display number (masked) and its API hash."""

    display: str  # masked, safe to print
    account_hash: str  # the hashed value Schwab requires for every request


def resolve_account(client: Client, settings: Settings) -> AccountRef:
    """Resolve the configured account into its hashed identifier.

    Schwab requires the *hashed* account number on every account/order request;
    schwab-py obtains it via ``get_account_numbers``. We never expose the raw
    number or the full hash in output.

    Raises
    ------
    ApiError, ConfigError
    """
    data = unwrap(client.get_account_numbers(), context="Fetching account numbers")
    if not isinstance(data, list) or not data:
        raise ApiError(200, "Schwab returned no linked accounts for this login.")

    if settings.account_index >= len(data):
        raise ConfigError(
            f"SCHWAB_ACCOUNT_INDEX={settings.account_index} is out of range; "
            f"this login has {len(data)} account(s) (valid indices 0..{len(data) - 1})."
        )

    entry = data[settings.account_index]
    account_hash = entry.get("hashValue")
    raw_number = entry.get("accountNumber", "")
    if not account_hash:
        raise ApiError(200, "Account entry is missing its hashValue.")

    return AccountRef(display=mask_account_number(raw_number), account_hash=account_hash)


# ---------------------------------------------------------------------------
# Data fetch helpers (the only place these endpoints are called)
# ---------------------------------------------------------------------------


def fetch_securities_account(client: Client, account_hash: str) -> dict[str, Any]:
    """Return the ``securitiesAccount`` block, including positions and balances."""
    resp = client.get_account(account_hash, fields=Client.Account.Fields.POSITIONS)
    data = unwrap(resp, context="Fetching account positions/balances")
    return data.get("securitiesAccount", data)


def fetch_working_orders(
    client: Client,
    account_hash: str,
    *,
    lookback_days: int = ORDER_LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    """Return raw working orders entered within the lookback window."""
    now = datetime.now(timezone.utc)
    resp = client.get_orders_for_account(
        account_hash,
        from_entered_datetime=now - timedelta(days=lookback_days),
        to_entered_datetime=now + timedelta(days=1),
        status=Client.Order.Status.WORKING,
    )
    data = unwrap(resp, context="Fetching working orders")
    return data if isinstance(data, list) else []
