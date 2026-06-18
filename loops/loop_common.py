"""loop_common.py -- shared infrastructure for the loop-engineering scripts.

This module deliberately contains NO loop logic and NO LOOP_CONFIG constants
(those live at the top of each individual loop script, per the spec). It only
provides reusable, side-effect-light helpers:

  * timestamped append-only logging into the git-ignored ``logs/`` directory,
  * macOS desktop notifications via ``osascript`` (no third-party installs),
  * Schwab token discovery / age / validity checks (never logs secret values),
  * an in-process per-iteration timeout (``deadline``) and a subprocess runner
    with a hard timeout,
  * a clean-exit handler installer (SIGTERM/SIGINT/atexit) so a loop killed
    mid-run can flush a final log entry.

All four loops import from here so the four universal guardrails are
implemented once and consistently.
"""

from __future__ import annotations

import atexit
import json
import os
import re
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional, Sequence

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
DEFAULT_TOKEN_FILENAME = "schwab_token.json"

# Schwab's refresh token lives ~7 days; this is the hard lifetime used by the
# token validator. Per-loop *warning* thresholds live in each loop's LOOP_CONFIG.
REFRESH_TOKEN_LIFETIME_DAYS = 7.0


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def iso_now() -> str:
    """Local-timezone ISO-8601 timestamp, e.g. 2026-06-18T12:31:43-04:00."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_logs_dir() -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR


def append_log(log_file: str, message: str) -> None:
    """Append ``"<iso_now> <message>\\n"`` to ``logs/<log_file>`` (crash-safe).

    Opens/writes/closes per call so a killed process never leaves a dangling
    handle. ``log_file`` is a bare filename resolved inside ``logs/``.
    """
    ensure_logs_dir()
    path = LOGS_DIR / log_file
    line = f"{iso_now()} {message}\n"
    # Append + flush + fsync-free close; low frequency so cost is irrelevant.
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences so captured rich output logs as plain text."""
    return _ANSI_RE.sub("", text)


# ---------------------------------------------------------------------------
# macOS desktop notifications (osascript -- no third-party installs)
# ---------------------------------------------------------------------------


def _applescript_quote(value: str) -> str:
    """Escape a string for embedding inside an AppleScript double-quoted literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def notify(title: str, message: str, *, sound: Optional[str] = "Submarine") -> bool:
    """Send a macOS desktop notification. Returns True on success.

    Never raises: a notification failure (no GUI session, osascript missing) is
    logged as a warning by the caller's convention and must not crash a loop.
    """
    body = _applescript_quote(message)
    head = _applescript_quote(title)
    script = f'display notification "{body}" with title "{head}"'
    if sound:
        script += f' sound name "{_applescript_quote(sound)}"'
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=True,
            capture_output=True,
            timeout=15,
        )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Schwab token discovery / validation (no secret values are ever logged)
# ---------------------------------------------------------------------------


def resolve_token_path() -> Path:
    """Resolve the Schwab token path the same way the app does, WITHOUT requiring
    API credentials to be present (so the token monitor works even if creds are
    missing). Reads ``SCHWAB_TOKEN_PATH`` from ``.env`` / the environment.
    """
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    raw = (os.environ.get("SCHWAB_TOKEN_PATH") or f"./{DEFAULT_TOKEN_FILENAME}").strip()
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()


# Token status vocabulary
HEALTHY = "HEALTHY"
WARN = "WARN"
CRITICAL = "CRITICAL"
MISSING = "MISSING"
CORRUPT = "CORRUPT"


def token_age_days(token_path: Path) -> float:
    """Age in days of the refresh token, from the file's ``creation_timestamp``.

    schwab-py writes ``creation_timestamp`` (epoch seconds) once at auth and
    preserves it across automatic access-token refreshes, so it tracks the
    refresh token's age. Raises FileNotFoundError / ValueError / KeyError on a
    missing, unreadable, or malformed file (caller maps these to MISSING/CORRUPT).
    """
    token_path = Path(token_path)
    with open(token_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    ts = data["creation_timestamp"]
    if not isinstance(ts, (int, float)):
        raise ValueError("creation_timestamp is not numeric")
    created = datetime.fromtimestamp(float(ts), tz=timezone.utc)
    age = (datetime.now(timezone.utc) - created).total_seconds() / 86400.0
    return age


@dataclass(frozen=True)
class TokenCheck:
    ok: bool          # True only if a valid, non-expired refresh token is present
    status: str       # HEALTHY / WARN / CRITICAL / MISSING / CORRUPT
    age_days: Optional[float]
    reason: str


def validate_token(
    token_path: Path,
    *,
    warn_days: float,
    critical_days: float,
    lifetime_days: float = REFRESH_TOKEN_LIFETIME_DAYS,
) -> TokenCheck:
    """Classify the Schwab token file. Used by every API-touching loop as a
    pre-flight check and by the token monitor as its core evaluator. ``ok`` is
    True only when the refresh token exists and is within its lifetime.
    """
    token_path = Path(token_path)
    if not token_path.exists():
        return TokenCheck(False, MISSING, None, f"token file not found at {token_path}")
    try:
        with open(token_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if "creation_timestamp" not in data:
            return TokenCheck(False, CORRUPT, None, "no creation_timestamp in token file")
        token = data.get("token")
        if not isinstance(token, dict) or not token.get("refresh_token"):
            return TokenCheck(False, CORRUPT, None, "no refresh_token in token file")
        age = token_age_days(token_path)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return TokenCheck(False, CORRUPT, None, f"unreadable token file: {type(exc).__name__}")

    if age >= lifetime_days:
        return TokenCheck(False, CRITICAL, age, f"refresh token expired (~{lifetime_days:g}d lifetime)")
    if age > critical_days:
        return TokenCheck(True, CRITICAL, age, f"refresh token {age:.2f}d old (>{critical_days:g}d)")
    if age > warn_days:
        return TokenCheck(True, WARN, age, f"refresh token {age:.2f}d old (>{warn_days:g}d)")
    return TokenCheck(True, HEALTHY, age, f"refresh token {age:.2f}d old")


# ---------------------------------------------------------------------------
# Per-iteration timeout (in-process) -- guardrail G2 for fast in-process work
# ---------------------------------------------------------------------------


class DeadlineExceeded(Exception):
    """Raised when an iteration exceeds its wall-clock budget."""


@contextmanager
def deadline(seconds: float) -> Iterator[None]:
    """Raise :class:`DeadlineExceeded` if the block runs longer than ``seconds``.

    Uses SIGALRM (main thread, Unix/macOS). Restores any prior handler on exit.
    """
    def _handler(signum, frame):  # noqa: ANN001
        raise DeadlineExceeded(f"iteration exceeded {seconds:g}s")

    previous = signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, max(0.001, float(seconds)))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@dataclass(frozen=True)
class SubprocessResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float


def run_subprocess(
    cmd: Sequence[str],
    *,
    timeout_s: float,
    cwd: Optional[Path] = None,
    env: Optional[dict] = None,
) -> SubprocessResult:
    """Run ``cmd`` with a hard timeout (guardrail G2 for the script-running loops).

    Returns a structured result; on timeout the child is killed and
    ``timed_out=True`` with exit_code 124 (conventional timeout code). ``env``,
    when given, fully replaces the child environment (callers merge with
    ``os.environ`` themselves).
    """
    start = time.monotonic()
    try:
        proc = subprocess.run(
            list(cmd),
            cwd=str(cwd or PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )
        return SubprocessResult(
            exit_code=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            timed_out=False,
            duration_s=time.monotonic() - start,
        )
    except subprocess.TimeoutExpired as exc:
        return SubprocessResult(
            exit_code=124,
            stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
            timed_out=True,
            duration_s=time.monotonic() - start,
        )


# ---------------------------------------------------------------------------
# Clean-exit handler -- guardrail G4
# ---------------------------------------------------------------------------


def install_clean_exit(finalize) -> None:  # noqa: ANN001
    """Register ``finalize(reason: str)`` to run on SIGTERM (launchd kill),
    SIGINT, and normal interpreter exit. ``finalize`` MUST be idempotent (guard
    with a flag) -- it may be invoked more than once.
    """
    def _handler(signum, frame):  # noqa: ANN001
        try:
            finalize(f"signal:{signal.Signals(signum).name}")
        finally:
            sys.exit(128 + signum)

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)
    atexit.register(lambda: finalize("atexit"))
