#!/usr/bin/env python3
"""Phase 2 flip-measurement sampler: the thin runner, OUTSIDE loops/phase2, that builds the Schwab client.

Spec 2: phase2 code sees only a wrapped client. loops/phase2/sample_bars.py builds no client, imports nothing that
can (review D7), and reads neither the token nor the settings (safety S5). This runner is the one place the
sampler's client is built and its token read. It passes sample_bars.main four callables:
  * market_data: a factory that reads the settings and the token through config.py, builds the client and wraps
    it in sample_bars.MarketData -- three read closures (daily candles, 1-minute candles, quotes), each behind the
    shared cross-process request limiter. main calls it once PER PULL, after that pull's own token check, and
    refuses anything that is not a MarketData; the client object itself never reaches the package. When bars.py's
    wrapped client exists, build that here instead.
  * token_hours: the refresh token's hours of life left and its expiry, from the token file's creation time
    (loop_common, the token monitor's reader); (None, None) when unreadable, which fails the run closed. The expiry
    is the hours left added in UTC and given in New York time, so it stays right across a DST change. It never
    prints the token.
  * notify: loop_common.notify (macOS notifications on this Mac).
  * awake: the idle-sleep assertion, ``/usr/bin/caffeinate -i -w <this process>``, held from 10 minutes before the
    evening sample to the night's last overnight pull and released on exit (caffeinate also exits by itself when
    this process ends, however it ends). A daytime start waits without it.

The token file: schwab-py rewrites the token file on each access-token refresh; that is the sampler's one write
outside logs/phase2/. The client is rebuilt for every pull, so a re-authentication between pulls is picked up and
never reverted (a client built at 17:30 would write the creation time it loaded back at its first refresh after
the re-auth). Do not re-authenticate while a pull is running (about 20 minutes). The night's token warning is
sent when the evening pull has finished, and no pull runs from then until a retry or 00:30, so re-authenticating
when it arrives is safe.

READ-ONLY: the wrapper exposes price history and quotes only. Nothing here calls, names or wraps an account or
order endpoint.

Usage (the same arguments as sample_bars.py; its docstring has the modes, files and states):
  loops/run.sh loops/phase2_sample.py night      the flip-measurement sampler's night job; defaults --evening-at
                                                 17:30 (retries 18:15, 19:00) --final-at
                                                 00:30,01:00,01:30,04:30,06:30,07:30 --full-at 06:30; the catch-up
                                                 pulls run before the evening on a start before 17:20, after it on
                                                 one at 17:20 or later (the launchd launch included), and a night
                                                 already complete gets nothing more
  launchd (one label): <root>/loops/run.sh loops/phase2_sample.py night, weekdays 17:20 and RunAtLoad (a login
                       or restart starts it); no caffeinate in the plist: this runner holds the power assertion
  loops/run.sh loops/phase2_sample.py final --session 2026-11-30 --full       one manual full re-pull
  loops/run.sh loops/phase2_sample.py plan --now 2026-11-30T17:35:00-05:00     (no network, no token)
"""

from __future__ import annotations

import atexit
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

HERE = Path(__file__).resolve()
LOOPS, ROOT = HERE.parent, HERE.parents[1]
for _p in (str(ROOT), str(LOOPS)):                    # config.py lives in the project root; phase2 under loops/
    if _p not in sys.path:
        sys.path.insert(0, _p)

from phase2 import sample_bars as SB  # noqa: E402

CAFFEINATE = "/usr/bin/caffeinate"


def read_only_market_data(client, limiter: SB.SharedRateLimiter) -> SB.MarketData:
    """Wrap a schwab-py client in the sampler's MarketData: three closures, each one read call behind ``limiter``.
    Only these three functions are handed to the package."""

    def _json(resp, what: str):
        if resp.status_code != 200:
            raise RuntimeError(f"{what}: HTTP {resp.status_code}")
        return resp.json()

    def daily(symbol: str, start: dt.datetime, end: dt.datetime) -> list:
        limiter.wait()
        r = client.get_price_history_every_day(symbol, start_datetime=start, end_datetime=end,
                                               need_extended_hours_data=False)
        return _json(r, f"daily {symbol}").get("candles", [])

    def minute(symbol: str, start: dt.datetime, end: dt.datetime) -> list:
        limiter.wait()
        r = client.get_price_history_every_minute(symbol, start_datetime=start, end_datetime=end,
                                                  need_extended_hours_data=False)
        return _json(r, f"minute {symbol}").get("candles", [])

    def quotes(symbols: list[str]) -> dict:
        limiter.wait()
        return _json(client.get_quotes(symbols), "quotes")

    return SB.MarketData(daily, minute, quotes)


def schwab_market_data(limiter: Optional[SB.SharedRateLimiter] = None) -> SB.MarketData:
    """Build the token-backed client here, outside the package, and return only its read-only wrapper. Called once
    per pull: the client lives only as long as that pull."""
    from config import build_client, load_settings      # deferred: importing this runner needs no token

    client = build_client(load_settings())
    return read_only_market_data(client, limiter if limiter is not None else SB.SharedRateLimiter(SB.LOCK_PATH))


def token_hours_left() -> tuple[Optional[float], Optional[str]]:
    """(hours of refresh-token life left, expiry time ISO) from the token file's creation time, read the way the
    token monitor reads it; (None, None) when it cannot be read. Never prints the token."""
    try:
        import loop_common as lc                        # deferred: importing this runner reads nothing
        age = lc.token_age_days(lc.resolve_token_path())
        left = (lc.REFRESH_TOKEN_LIFETIME_DAYS - age) * 24.0
        # hours of life are elapsed time: add them in UTC, then show New York time (right across a DST change)
        return left, SB.iso(SB.now_et().astimezone(dt.timezone.utc) + dt.timedelta(hours=left))
    except Exception:                                     # noqa: BLE001
        return None, None


def macos_notify(title: str, message: str) -> None:
    """A macOS notification through loop_common (which never raises)."""
    try:
        import loop_common as lc                        # deferred
        lc.notify(title, message)
    except Exception:                                     # noqa: BLE001
        pass


class PowerAssertion:
    """``awake(on)`` for sample_bars.main: while on, ``/usr/bin/caffeinate -i -w <pid>`` holds macOS's idle-sleep
    assertion for this process (all its std streams to /dev/null). Idempotent both ways; ``release`` also runs at
    exit, and caffeinate's -w ends the assertion by itself if this process dies."""

    def __init__(self, popen: Callable = subprocess.Popen, pid: Optional[int] = None) -> None:
        self.popen, self.pid, self.proc = popen, os.getpid() if pid is None else pid, None

    def __call__(self, on: bool) -> None:
        if not on:
            self.release()
        elif self.proc is None or self.proc.poll() is not None:
            self.proc = self.popen([CAFFEINATE, "-i", "-w", str(self.pid)], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def release(self) -> None:
        proc, self.proc = self.proc, None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:                                 # noqa: BLE001
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:                             # noqa: BLE001
                pass


def main(argv: Optional[list[str]] = None, factory: Callable[[], SB.MarketData] = schwab_market_data, *,
         token_hours: Callable[[], tuple] = token_hours_left, notify: Optional[Callable[[str, str], None]] = macos_notify,
         awake: Optional[Callable[[bool], None]] = None) -> int:
    """sample_bars.main with the runner's four callables (spec 2). Every one is replaceable for tests only; with
    ``awake`` left None the runner holds the real power assertion, released in a finally and at exit."""
    power = None
    if awake is None:
        power = PowerAssertion()
        atexit.register(power.release)
        awake = power
    try:
        return SB.main(argv, market_data=factory, token_hours=token_hours, notify=notify, awake=awake)
    finally:
        if power is not None:
            power.release()


if __name__ == "__main__":
    sys.exit(main())
