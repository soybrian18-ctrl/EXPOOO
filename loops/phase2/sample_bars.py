#!/usr/bin/env python3
"""Phase 2 flip measurement, part 1 of 2: sample each session's daily bars as the EVENING scan sees them
(provisional), then again overnight once they are FINAL. ``compare_bars.py`` (part 2) measures the flips.

Owner's instruction (2026-11-11): "Before relying on it, measure how often provisional bars flip a signal
across the nights you sample." This file only stores what that measurement needs.

READ-ONLY. Network use, and nothing else:
  * the Nasdaq Trader symbol directory (two public text files, the only URLs fetch_directory_http accepts),
    archived per session;
  * three Schwab market-data reads -- daily candles, 1-minute candles, quotes -- through ``MarketData``:
    three closures over the runner's client: the client is not an attribute of the wrapper, and the contract
    tests forbid reaching it through the closures. Every read waits on ``SharedRateLimiter``, a
    cross-process limit of ``params.request_limit_per_min`` requests a minute (spec 2, bars.py row).
  Spec 2: phase2 code sees only a wrapped client. This module builds no client, imports nothing that can
  (review D7), and reads neither the token nor the settings (safety S5). The runner outside the package,
  loops/phase2_sample.py, passes ``main`` four callables: a factory for the ``MarketData`` wrapper, the
  token's hours left, a notifier, and the idle-sleep assertion (``main``'s docstring). ``main`` calls the
  factory once PER PULL, each time after that pull's own token check, and refuses anything that is not a
  ``MarketData``: a client built for one pull never outlives it, so a re-authentication between pulls is
  picked up and never reverted (schwab-py writes the creation time it loaded back into the token file at
  every access-token refresh). A network mode started without the factory or the token reader is FAILED at
  once. When bars.py's wrapped client exists, the runner should build that instead. Nothing here calls,
  names or wraps an account or order endpoint.
  Every pull first checks the token: it fails closed under ``params.token_min_hours`` (spec 4 step 1), and an
  unreadable token fails closed too.
  Notifications, through the runner's notifier: FAILED (a run of failed token checks notifies once; a check that
  passes re-arms it); INCOMPLETE (in a night pass only on the last evening attempt and the last overnight pull;
  an evening that ends INCOMPLETE because its later retries were not made, so no attempt could notify it, sends
  "evening <session>: INCOMPLETE, and its retries were not made"); LATE; MISSED-NIGHT, from a final pull without
  its evening sample and from the missed-night detection (one notification listing every session found missed);
  a token that expires less than params.token_min_hours after the night's last overnight pull (a warning, once
  per pass, sent when the pass's first evening attempt whose token check passed has finished, so no pull is
  running then; the night still samples); a process that has made its 7 passes and exits (it names the next
  session, which is not sampled unless the job is started again); a crash; a calendar that has run out.
  Exit codes: 0 done or skipped, 1 failed or crashed, 2 a refused --session, 3 MISSED-NIGHT, 4 incomplete.
  ``evening`` returns its run's code and ``final`` its last target's; ``night`` returns the night's OUTCOME:
  the worst, ranked 1 > 3 > 4 > 0, of each pass's catch-up pulls, its last evening attempt and its last
  overnight pull. An attempt a later retry replaced and an overnight pull a later one replaced (the expected
  INCOMPLETE 00:30 pull, say, or the pulls of a pass that left its session to the next pass's catch-up) do not
  count; each is in runs.jsonl and was notified as the rules above say.

Session keying (review, measurement major 5: misfiled, diluted or silently lost nights)
  Every run is keyed to the last COMPLETED NYSE session at the moment it runs, from the small calendar
  below (holidays and 13:00 closes, 2026-11..2027-03), never to the wall-clock date.
  * evening -- samples that session. It is LATE when it starts after 19:30 ET (params.watchdog_evening_et,
    the scan's missed-window time) or on a later day, or when any candidate's candle for the session is
    already final. It is refused (SKIPPED) after 04:00 ET on the next calendar day, when the candles are
    final anyway, and when the session already has a DONE evening sample (a holiday run cannot overwrite the
    previous session's sample). An INCOMPLETE or FAILED evening may be re-run: it reuses candidates.json
    and re-pulls only the names without a usable bar. DONE needs SPY's bar, no failed quote chunk, and a bar
    for at least ceil(params.completeness_min x candidates) of the candidates.
  * final -- requires that session's evening sample: its candidates.json and at least one usable evening row
    (``has_evening_sample``, the one rule the missed-night detection and the catch-up use too). Without one it
    writes MISSED-NIGHT (once per session, whatever mode flagged it first) and pulls nothing: it never pairs a
    final pull with another session's evening sample.
  * night -- one process per launch, in passes. Each pass keys itself (``night_session``) and records
    MISSED-NIGHT for every session since the earliest folder with a status file (the last 10 sessions at
    most) that has no evening sample. A session whose night is already complete (an evening sample, and a
    final pull DONE or INCOMPLETE that started at or after its last overnight target: a weekday-holiday launch or a
    weekend login keys to it again) gets nothing more: 'nothing left', no attempt, no pull, no assertion.
    Otherwise the pass makes one catch-up final pull for each of those recent sessions that has an evening
    sample but whose overnight pulls never completed (no final pull DONE, and every INCOMPLETE one started
    before that session's last target: the process died, slept or failed its token checks after it), takes
    the evening sample (retried at params.evening_retry_et while FAILED or INCOMPLETE; no attempt is made
    once a later session has completed, checked again once its wrapper is built, and no retry once the
    evening window has passed at 04:00 the next day), then the overnight pulls. A daytime start makes the
    catch-up pulls first, while it waits; a start at or after the hold time (10 minutes before the evening
    sample: the 17:20 launch itself, a late start or a roll-over) takes the evening sample first and the
    catch-up pulls after it, so a catch-up never makes an on-time evening LATE. A pass whose last pull ends
    after the next session's evening start minus 10 minutes rolls over into that session's night (at most 7
    passes): launchd keeps one process per label, so the launch it delivered meanwhile was dropped. A pass
    that wakes with pulls still due after that time, on the next session's day, makes none of them: it
    leaves its session to the next pass's catch-up, which runs after that pass's evening sample (the 7th
    pass, which has no next pass, makes them).

Responses (review, measurement major 6; operations finding 1; instruction-fidelity F5)
  Every daily-candle response is classified from its candles:
    evening:  PROVISIONAL | ALREADY_FINAL          final:  FINAL | NOT_FINAL
    both:     TRUNCATED (candles but none before the session: the 19 responses of 01:49:51..01:50:33 on
              2026-11-12), EMPTY (no candles), NO_BAR (history but no candle for the session), ERROR.
  TRUNCATED, EMPTY, NO_BAR and ERROR are retried up to 3 times, with a pause before each round; every
  attempt is its own row. NOT_FINAL is not retried within a run: later ``--at`` pulls re-pull only the
  symbols that have no FINAL row yet, so the night's folder shows when each name became final. A full pull
  (``final --full``, or the night's ``--full-at`` target, 06:30) re-pulls every symbol, so each FINAL row can
  be compared with a later one (compare_bars: "final candle revised between pulls").

Universe stand-in (review, measurement major 3; spec 3.1 until universe.py exists at B4)
  Directory rules: Test Issue = N; ETF = N; the NASDAQ-symbol suffix rules (- + = ^ # $ * % ~); dotted
  class shares kept and mapped to Schwab's form (BF.B is requested as BF/B and BF.B; the form that
  returns a quote is used and recorded); word-boundary name rules (warrants?, rights?, units?, notes,
  debentures, coupons, preferred / preference / Pfd / cumulative, ETNs); depositary shares KEPT (ADRs)
  unless the name marks a preferred or fractional interest; MLPs excluded by name (L.P., LP, limited
  partnership) whatever the subtype says; royalty and statutory (commodity, crypto) trusts excluded; a
  fund sponsor's "Trust" excluded unless the name says realty, REIT, properties or mortgage (FBRT, Franklin
  BSP Realty Trust, is a mortgage REIT's common stock: review D4); any other "Trust" kept (banks, REITs);
  SPACs excluded: "Acquisition Corp" and kin, and "Acquisition <numeral> Corp/Co" ("Acquisition II Corp",
  "Acquisition 6 Corp", "Acquisition1 Corp": review D3), a bare "Acquisition <numeral>" ("Acquisition I",
  "Acquisition 1") and a glued "<Word>acquisition Corp" (FJDI, FTRA, KRAQ: integration check, gap B); funds excluded; Nasdaq's " - Closed End Fund" label
  is judged on the issuer's own name, so BDCs under it are KEPT on both directory files alike. These are
  the stand-in's name rules: BDCs are in the universe by the owner's ruling of 2026-11-12 (spec 3.1), known by their SEC 814- file number at B3/B4, not by name. A BDC whose own name says "Fund" (MSIF, MSC Income Fund; BXSL, MSDL and
  FSSL, from general knowledge, to be confirmed at B3/B4) is left excluded here by the stand-in's fund rule,
  and its exclusion record says so (FUND_NAMED_BDCS), so B3/B4 can see it (review D4).
  Quote stage: assetSubType ETF, ETN, CEF, PRF, WAR, RGT, UIT dropped; then the sampling margins
  (not spec rules): price $4-110 and avg10 or avg1y volume >= 300k (avg10 alone lost 11 in-band names
  on night 1). Every exclusion is logged with its stage and reason in exclusions.jsonl.
  SPY is always sampled (quote, candles, 1-minute bars) as a reference symbol outside the universe.

Files under <root>/<session>/ (root defaults to logs/phase2/bar_samples; stamps are YYYYMMDD_HHMM)
  directory/                  the two directory files, as downloaded for this session
  exclusions.jsonl            every excluded directory row or quote, with stage and reason
  candidates.json             the sampled universe (Schwab symbols), reference symbols, symbol map
  quotes_<stamp>.jsonl        evening quotes (regular.regularMarketLastPrice is the official close)
  evening_<stamp>.jsonl       evening daily candles, last 5 kept (t-4..t: the basis check reads t-1..t-4)
  final_<stamp>.jsonl         overnight daily candles, last 130 kept (compute_levels reads 120)
  minute_<stamp>.jsonl        regular-session 1-minute bars for SPY, every name whose final open differs
                              from its evening open, and every M2-like name (quote proxy: |open / prior
                              close - 1| >= 2% and volume >= 2 x avg10), so each open's print can be checked
  status_<mode>_<stamp>.json  the run's heartbeat: STARTED -> RUNNING -> DONE | INCOMPLETE | FAILED |
                              MISSED-NIGHT | SKIPPED, with counts, times, LATE flags and token expiry; the
                              missed-night detection writes its MISSED-NIGHT as mode 'evening'
  ../runs.jsonl               one append-only line per finished run (for the missed-window watchdog)

Usage (Eastern times; the Mac runs on New York time). The network modes run through the runner
loops/phase2_sample.py, which takes the same arguments; ``plan`` needs no network and no token, and also
runs from this file:
  phase2_sample.py plan [--now ISO]            session keying and the night's schedule for now, no network
  phase2_sample.py evening [--at HH:MM]        one evening sample (the scan's own time is 17:30)
  phase2_sample.py final [--session DATE] [--at HH:MM[,HH:MM...]] [--full] [--no-minute]
                                               --session must be a carried-calendar session after
                                               2026-10-30 and not later than the last completed one
  phase2_sample.py night [--evening-at 17:30] [--final-at 00:30,01:00,01:30,04:30,06:30,07:30]
                         [--full-at 06:30] [--no-minute]
                                               the flip-measurement sampler's night job (launchd: weekdays
                                               17:20 and RunAtLoad, one label, no caffeinate): missed-night
                                               detection first; evening sample with retries at 18:15 and
                                               19:00; the overnight pulls (full at 06:30); the catch-up
                                               pulls before the evening on a daytime start, after it on a
                                               later start; roll-over when the Mac slept; the runner holds
                                               the idle-sleep assertion from 10 minutes before the evening
                                               sample to the last overnight pull
  common: [--root DIR]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import time
import zoneinfo
from fractions import Fraction
from pathlib import Path
from typing import Callable, Iterable, Optional

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]                                  # the project root
LOOPS = HERE.parents[1]
if str(LOOPS) not in sys.path:                          # run as a script: make `phase2` importable
    sys.path.insert(0, str(LOOPS))

from phase2.params import PARAMS, params_hash  # noqa: E402

NY, CH = zoneinfo.ZoneInfo("America/New_York"), zoneinfo.ZoneInfo("America/Chicago")
OUT = ROOT / "logs" / "phase2" / "bar_samples"
LOCK_PATH = ROOT / "logs" / "phase2" / ".schwab_requests.lock"
DIRECTORY = {"nasdaqlisted.txt": "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt",
             "otherlisted.txt": "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"}
REFERENCE = ("SPY",)

# --- sampling margins (not spec rules: the spec's $5-100 and 500k ADV30 are applied by compare_bars) ----
PRICE_BAND = (4.0, 110.0)
MIN_AVG_VOLUME = 300_000
DROP_SUBTYPES = frozenset({"ETF", "ETN", "CEF", "PRF", "WAR", "RGT", "UIT"})     # spec 3.1
# The review's M2-like stratum, on quote fields. Like FINAL_AT_DEFAULT, FULL_AT_DEFAULT, AWAKE_LEAD and
# CALENDAR_LAST below, these are the sampler's own constants: they belong to the night schedule ruled
# 2026-11-12 (spec 4, step 4), enter no backtest number, and are frozen with the code hash, not with params.py.
M2_LIKE_GAP, M2_LIKE_VOLUME = 0.02, 2.0

# --- pulls -----------------------------------------------------------------------------------------------
HISTORY_DAYS = {"evening": 10, "final": 200}     # calendar days requested
KEEP_LAST = {"evening": 5, "final": 130}         # candles kept per row
QUOTE_CHUNK = 400                                # Schwab allows 500 symbols per quotes call
RETRY_ROUNDS = 3
RETRY_PAUSE_S = 60.0                             # the 2026-11-12 truncated block lasted 42 s
PROGRESS_EVERY = 100

# --- lateness --------------------------------------------------------------------------------------------
LATE_AFTER = dt.time.fromisoformat(PARAMS.watchdog_evening_et)   # 19:30, the scan's missed-window time: an
                                                                 # evening sample started after it is LATE
EVENING_REFUSE_AFTER = dt.time(4, 0)             # ... and after this on the next day it is refused

# --- the night job ---------------------------------------------------------------------------------------
# FINAL_AT_DEFAULT, FULL_AT_DEFAULT and AWAKE_LEAD belong to the schedule ruled 2026-11-12 (spec 4, step 4): the
# sampler's own constants, entering no backtest number, frozen with the code hash (not params.py).
FINAL_AT_DEFAULT = "00:30,01:00,01:30,04:30,06:30,07:30"   # overnight pulls (00:30 and 01:00 test the recheck's
                                                           # 01:00 start)
FULL_AT_DEFAULT = "06:30"                        # ... of which this one re-pulls every symbol (FINAL vs FINAL)
AWAKE_LEAD = dt.timedelta(minutes=10)            # the idle-sleep assertion starts this long before the evening
                                                 # sample; a pass ending after the next evening's start minus
                                                 # this rolls over (the plist launches at 17:20)
MAX_PASSES = 7                                   # night passes per process
MISSED_LOOKBACK = 10                             # sessions the missed-night detection and the catch-up look back
SAMPLE_AFTER = dt.date.fromisoformat(PARAMS.oos_end)   # a final --session must be after the sealed window (3.7)
TITLE = "Phase 2 bar sample"                     # every notification's title


# =========================================================================================================
# NYSE calendar, 2026-11..2027-03 (a stand-in: params.py gets the full 2021-2027 calendar at B3)
# =========================================================================================================

# CALENDAR_LAST belongs to the schedule ruled 2026-11-12 (spec 4, step 4): a sampler constant that enters no backtest
# number and is frozen with the code hash. Past it every network mode fails with a notification (main).
CALENDAR_FIRST, CALENDAR_LAST = dt.date(2026, 11, 1), dt.date(2027, 3, 31)
HOLIDAYS = {
    dt.date(2026, 11, 26): "Thanksgiving Day",
    dt.date(2026, 12, 25): "Christmas Day",
    dt.date(2027, 1, 1): "New Year's Day",
    dt.date(2027, 1, 18): "Martin Luther King Jr. Day",
    dt.date(2027, 2, 15): "Washington's Birthday",
    dt.date(2027, 3, 26): "Good Friday",          # Easter 2027 is March 28
}
EARLY_CLOSES = {dt.date(2026, 11, 27): dt.time(13, 0), dt.date(2026, 12, 24): dt.time(13, 0)}
REGULAR_OPEN, REGULAR_CLOSE = dt.time(9, 30), dt.time(16, 0)


class CalendarError(ValueError):
    """A date outside the calendar this module carries: it refuses to guess."""


def _covered(d: dt.date) -> None:
    if not (CALENDAR_FIRST <= d <= CALENDAR_LAST):
        raise CalendarError(f"{d} is outside the NYSE calendar carried here ({CALENDAR_FIRST}..{CALENDAR_LAST})")


def is_session(d: dt.date) -> bool:
    _covered(d)
    return d.weekday() < 5 and d not in HOLIDAYS


def session_close(d: dt.date) -> dt.time:
    if not is_session(d):
        raise CalendarError(f"{d} is not an NYSE session")
    return EARLY_CLOSES.get(d, REGULAR_CLOSE)


def previous_session(d: dt.date) -> dt.date:
    x = d - dt.timedelta(days=1)
    while not is_session(x):
        x -= dt.timedelta(days=1)
    return x


def next_session(d: dt.date) -> dt.date:
    x = d + dt.timedelta(days=1)
    while not is_session(x):
        x += dt.timedelta(days=1)
    return x


def sessions_between(first: dt.date, last: dt.date) -> list[dt.date]:
    """Every session from first to last, inclusive."""
    out, d = [], first
    while d <= last:
        if is_session(d):
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def last_completed_session(now: dt.datetime) -> dt.date:
    """The latest session whose close (16:00, or 13:00 on a half day) is at or before ``now`` (ET)."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    et = now.astimezone(NY)
    d = et.date()
    if is_session(d) and et.time() >= session_close(d):
        return d
    return previous_session(d)


def third_friday(year: int, month: int) -> dt.date:
    d = dt.date(year, month, 15)
    return d + dt.timedelta(days=(4 - d.weekday()) % 7)


def session_tags(d: dt.date) -> list[str]:
    """Special-session labels for the per-night table (the review asks for expirations and half days)."""
    tags = [d.strftime("%a")]
    try:
        if d in EARLY_CLOSES:
            tags.append("half day 13:00")
        if d == third_friday(d.year, d.month):
            tags.append("quarterly expiration" if d.month in (3, 6, 9, 12) else "monthly expiration")
        back = d - dt.timedelta(days=1)
        while back.weekday() >= 5:
            back -= dt.timedelta(days=1)
        if back in HOLIDAYS:
            tags.append(f"after {HOLIDAYS[back]}")
        fwd = d + dt.timedelta(days=1)
        while fwd.weekday() >= 5:
            fwd += dt.timedelta(days=1)
        if fwd in HOLIDAYS:
            tags.append(f"before {HOLIDAYS[fwd]}")
        if not is_session(d):
            tags.append("NOT A SESSION")
    except CalendarError:
        tags.append("outside calendar")
    return tags


def evening_timing(now: dt.datetime, session: dt.date) -> tuple[str, list[str]]:
    """("ON_TIME" | "LATE" | "TOO_LATE", reasons) for an evening sample of ``session`` started at ``now``."""
    et = now.astimezone(NY)
    if et.date() == session:
        if et.time() > LATE_AFTER:
            return "LATE", [f"started {et:%H:%M} ET, after the {LATE_AFTER:%H:%M} cutoff"]
        return "ON_TIME", []
    if et.date() == session + dt.timedelta(days=1) and et.time() < EVENING_REFUSE_AFTER:
        return "LATE", [f"started {et:%Y-%m-%d %H:%M} ET, the day after the session"]
    return "TOO_LATE", [f"started {et:%Y-%m-%d %H:%M} ET: the evening window for {session} has passed"]


# =========================================================================================================
# Candles and response classes (pure)
# =========================================================================================================

PROVISIONAL, ALREADY_FINAL = "PROVISIONAL", "ALREADY_FINAL"      # evening
FINAL, NOT_FINAL = "FINAL", "NOT_FINAL"                           # final
TRUNCATED, EMPTY, NO_BAR, ERROR = "TRUNCATED", "EMPTY", "NO_BAR", "ERROR"
RETRY_CLASSES = frozenset({TRUNCATED, EMPTY, NO_BAR, ERROR})
CLASS_RANK = {FINAL: 6, PROVISIONAL: 6, NOT_FINAL: 5, ALREADY_FINAL: 5, NO_BAR: 3, TRUNCATED: 2, EMPTY: 1,
              ERROR: 0}


def stamp_kind(ms: int) -> str:
    """'final' (stamped midnight America/Chicago), 'provisional' (midnight America/New_York), or other."""
    u = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)
    if u.astimezone(CH).time() == dt.time(0, 0):
        return "final"
    if u.astimezone(NY).time() == dt.time(0, 0):
        return "provisional"
    return f"other:{u:%H:%M}Z"


def candle_from_raw(k: dict) -> dict:
    """A Schwab daily candle keyed by its New York date (spec 2, bars.py row)."""
    ms = int(k["datetime"])
    return dict(d=dt.datetime.fromtimestamp(ms / 1000, NY).date().isoformat(), kind=stamp_kind(ms), ms=ms,
                o=k["open"], h=k["high"], l=k["low"], c=k["close"], v=k["volume"])


def response_class(candles: Optional[list], session: str, mode: str) -> str:
    """Classify one daily-candle response for ``session`` (ISO date). ``mode`` is 'evening' or 'final'."""
    if candles is None:
        return ERROR
    if not candles:
        return EMPTY
    if not any(c["d"] < session for c in candles):
        return TRUNCATED
    kinds = {c["kind"] for c in candles if c["d"] == session}
    if not kinds:
        return NO_BAR
    if mode == "evening":
        return ALREADY_FINAL if "final" in kinds else PROVISIONAL
    return FINAL if "final" in kinds else NOT_FINAL


def better_class(a: Optional[str], b: str) -> str:
    return b if a is None or CLASS_RANK[b] > CLASS_RANK[a] else a


# =========================================================================================================
# Universe stand-in (pure)
# =========================================================================================================

SUFFIX_CHARS = "-+=^#$*%~"
_I = re.IGNORECASE
COMMON_PHRASE = re.compile(r"\bcommon\s+(stock|shares?)\b|\bordinary\s+shares?\b", _I)
CEF_SPONSORS = (r"blackrock|eaton\s+vance|nuveen|pimco|calamos|abrdn|aberdeen|cohen\s+&\s+steers|western\s+asset|"
                r"invesco|mfs|virtus|allspring|franklin|templeton|john\s+hancock|gabelli|gamco|neuberger|doubleline|"
                r"kayne\s+anderson|tortoise|duff\s+&\s+phelps|flaherty|royce|guggenheim|bny\s+mellon|morgan\s+stanley|"
                r"pioneer|putnam|clough|saba|highland|liberty\s+all-star|first\s+trust|dws|angel\s+oak|xai")
NAME_RULES = (   # (reason, pattern, skipped when the name says common/ordinary shares), first match wins
    ("SPAC", re.compile(r"acquisitions?\s*(?:(?:[ivx]+|\d+)\.?\s+)?(corp(oration)?|company|co|inc|ltd|limited|holdings?|group)\b|"
                        r"\bacquisitions?\s*(?:[ivx]+|\d+)\b|"
                        r"\bblank[- ]check\b|\bmerger\s+corp(oration)?\b|\bspac\b", _I), False),
    ("MLP", re.compile(r"\blimited\s+partner(ship)?s?\b|(?<![A-Za-z0-9])L\.\s?P\.?(?![A-Za-z0-9])|\bLP\b", _I), False),
    ("royalty trust", re.compile(r"\broyalt(y|ies)\b.*\btrust\b|\b(oil|gas|petroleum|energy|marcellus|permian|"
                                 r"mississippian|granite\s+wash|prudhoe\s+bay|mesabi|hugoton)\b.*\btrust\b", _I), False),
    ("statutory trust", re.compile(r"\b(bitcoin|ether(eum)?|crypto(currency)?|digital\s+assets?|gold|silver|"
                                   r"platinum|palladium|physical|commodit(y|ies)|currenc(y|ies))\b.*\btrust\b|"
                                   r"\b(grantor|statutory)\s+trust\b", _I), False),
    ("closed-end fund (sponsor and Trust)",
     re.compile(r"^(the\s+)?(" + CEF_SPONSORS + r")\b(?!.*\b(realty|reit|properties|mortgage)\b).*\btrust\b", _I), False),
    ("closed-end fund (municipal, term or floating-rate Trust)",
     re.compile(r"\b(municipal|term|floating\s+rate)\b.*\btrust\b", _I), False),
    ("structured product", re.compile(r"\bSTRATS\b|\bsynthetic\s+fixed-income\b|\btrust\s+securities\b|"
                                      r"\bcapital\s+trust\b", _I), False),
    ("ETN", re.compile(r"\bETNs?\b|\bexchange[- ]traded\s+notes?\b", _I), False),
    ("preferred", re.compile(r"\bpreferred\b|\bpreference\b|\bpfd\b|\bperp(etual)?\b|\b(non-?)?cumulative\b", _I), True),
    ("fractional interest", re.compile(r"\binterest\s+in\s+a\s+share\b|\bownership\s+interest\b|\bfractional\b|"
                                       r"\b1/[\d,]+\s*(st|nd|rd|th)?\s+(interest|ownership)\b", _I), False),
    ("debt or coupon", re.compile(r"\bnotes?\b|\bdebentures?\b|\bsubordinated\b|%|"
                                  r"\bfixed[- ]to[- ]floating\b|\bcapital\s+securities\b", _I), False),
    ("warrant", re.compile(r"\bwarrants?\b", _I), False),
    ("right", re.compile(r"\brights?\b(?!\s+to\s+receive)", _I), False),     # ADRs say "the right to receive"
    ("unit", re.compile(r"\bunits?\b", _I), False),
)
CEF_LABEL = re.compile(r"\s*-\s*closed[- ]end\s+fund\s*$", _I)
FUND = re.compile(r"\bfunds?\b", _I)
# BDCs whose own name says "Fund" (review D4). The stand-in's generic fund rule excludes them and they are LEFT
# excluded here; BDCs are in the universe by the owner's ruling of 2026-11-12 (spec 3.1), known by SEC 814- file
# number at B3/B4, and the exclusion record carries the reason so B3/B4 can see them. MSIF is the review's case. BXSL, MSDL and FSSL are listed as BDCs from
# general knowledge, not from the directory files: confirm each against its SEC 814- (Investment Company Act)
# file number at B3/B4, and drop any that is not a BDC.
BDC_RULING = ("BDCs are in the universe by the owner's ruling of 2026-11-12 (spec 3.1), known by their SEC 814- "
              "file number at B3/B4, not by name")
_BDC_REASON = ("{} is a BDC: excluded by the generic fund name rule and left so in this stand-in; "
               + BDC_RULING + " (review D4)")
FUND_NAMED_BDCS = {
    "MSIF": _BDC_REASON.format("MSC Income Fund, Inc."),
    "BXSL": _BDC_REASON.format("Blackstone Secured Lending Fund"),
    "MSDL": _BDC_REASON.format("Morgan Stanley Direct Lending Fund"),
    "FSSL": _BDC_REASON.format("FS Specialty Lending Fund"),
}
CEF_NAME = re.compile(r"\b(funds?|trust|income|portfolio|opportunit(y|ies))\b", _I)
CLASS_SHARE = re.compile(r"^([A-Z]{1,5})\.([A-Z]{1,2})$")
NON_CLASS_SUFFIX = frozenset({"U", "W", "WS", "R", "RT"})        # units, warrants, rights


def parse_directory(text: str, source: str) -> list[dict]:
    """Rows of a Nasdaq Trader directory file, columns by header name; the footer line is skipped."""
    lines = text.splitlines()
    if not lines:
        return []
    header = lines[0].split("|")
    rows = []
    for line in lines[1:]:
        parts = line.split("|")
        if len(parts) != len(header) or line.startswith("File Creation Time"):
            continue
        rec = dict(zip(header, parts))
        sym = (rec.get("Symbol") or rec.get("ACT Symbol") or "").strip()
        nasdaq_sym = (rec.get("NASDAQ Symbol") or rec.get("Symbol") or "").strip()
        rows.append(dict(symbol=sym, nasdaq_symbol=nasdaq_sym, name=rec.get("Security Name", "").strip(),
                         etf=rec.get("ETF", "").strip(), test=rec.get("Test Issue", "").strip(), source=source,
                         exchange=rec.get("Exchange", "Q" if source.startswith("nasdaq") else "").strip(),
                         financial_status=rec.get("Financial Status", "").strip()))
    return rows


def schwab_forms(symbol: str) -> list[str]:
    """Schwab symbol forms to request for a directory symbol; a class share gets 'BF/B' then 'BF.B'."""
    m = CLASS_SHARE.match(symbol)
    if m:
        return [f"{m.group(1)}/{m.group(2)}", symbol]
    return [symbol]


def directory_decision(row: dict) -> tuple[bool, str, str]:
    """(keep, reason or note, matched text). A kept row's note says why a borderline name stayed in."""
    sym, name = row["symbol"], row["name"]
    if row["test"] != "N":
        return False, f"test issue (Test Issue={row['test'] or 'blank'})", ""
    if row["etf"] != "N":
        return False, f"ETF flag (ETF={row['etf'] or 'blank'})", ""
    for s in (sym, row.get("nasdaq_symbol", "")):
        hit = next((ch for ch in s if ch in SUFFIX_CHARS), None)
        if hit:
            return False, f"symbol suffix '{hit}' ({s})", hit
    m = CLASS_SHARE.match(sym)
    if m and m.group(2) in NON_CLASS_SUFFIX:
        return False, f"symbol suffix '.{m.group(2)}' (unit, warrant or right)", sym
    if not m and not sym.isalpha():
        return False, f"symbol format ({sym})", sym
    common = bool(COMMON_PHRASE.search(name))
    for reason, pat, common_overrides in NAME_RULES:
        hit = pat.search(name)
        if hit and not (common_overrides and common):
            return False, reason, hit.group(0)
    issuer = CEF_LABEL.sub("", name)
    if issuer != name:                                    # Nasdaq's " - Closed End Fund" label
        hit = CEF_NAME.search(issuer)
        if hit:
            return False, "closed-end fund (Nasdaq label, fund-type issuer name)", hit.group(0)
        return True, ("BDC-type issuer under Nasdaq's 'Closed End Fund' label: kept; " + BDC_RULING), ""
    hit = FUND.search(name)
    if hit:
        why = FUND_NAMED_BDCS.get(sym)
        return False, "fund" + (f" ({why})" if why else ""), hit.group(0)
    notes = []
    if m:
        notes.append("class share, requested as " + " and ".join(schwab_forms(sym)))
    if re.search(r"\bdepositary\b", name, _I):
        notes.append("depositary shares kept as an ADR")
    if re.search(r"\btrust\b", name, _I):
        notes.append("'Trust' in the name: not a royalty or statutory trust")
    return True, "; ".join(notes), ""


def universe_stand_in(rows: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    """(kept, excluded). Kept rows carry 'forms' (Schwab symbols to request); excluded rows carry a reason."""
    kept, excluded, seen = [], [], set()
    for r in rows:
        keep, why, hit = directory_decision(r)
        if not keep:
            excluded.append(dict(stage="directory", symbol=r["symbol"], name=r["name"], source=r["source"],
                                 reason=why, matched=hit))
            continue
        if r["symbol"] in seen:
            excluded.append(dict(stage="directory", symbol=r["symbol"], name=r["name"], source=r["source"],
                                 reason="duplicate symbol", matched=""))
            continue
        seen.add(r["symbol"])
        kept.append(dict(r, forms=schwab_forms(r["symbol"]), note=why))
    return kept, excluded


def quote_record(sym: str, entry: dict, pulled: str) -> dict:
    """The fields kept from one Schwab quote entry."""
    qq, rg, fd = entry.get("quote", {}), entry.get("regular", {}), entry.get("fundamental", {})
    return dict(symbol=sym, pulled=pulled, sub=entry.get("assetSubType"), main=entry.get("assetMainType"),
                open=qq.get("openPrice"), high=qq.get("highPrice"), low=qq.get("lowPrice"), last=qq.get("lastPrice"),
                prev_close=qq.get("closePrice"), total_volume=qq.get("totalVolume"),
                regular_last=rg.get("regularMarketLastPrice"), regular_time=rg.get("regularMarketTradeTime"),
                avg10=fd.get("avg10DaysVolume"), avg1y=fd.get("avg1YearVolume"),
                ex_div=fd.get("divExDate"), last_earnings=fd.get("lastEarningsDate"))


def quote_decision(rec: dict) -> tuple[bool, str]:
    """Quote-stage filter: the spec's subtype rule, then the sampling margins."""
    sub = rec.get("sub")
    if sub in DROP_SUBTYPES:
        return False, f"assetSubType {sub}"
    px = rec.get("regular_last") or rec.get("last")
    if not px:
        return False, "no price in the quote"
    if not PRICE_BAND[0] <= px <= PRICE_BAND[1]:
        return False, f"price {px} outside the sampling band {PRICE_BAND[0]:g}-{PRICE_BAND[1]:g}"
    vol = max(rec.get("avg10") or 0, rec.get("avg1y") or 0)
    if vol < MIN_AVG_VOLUME:
        return False, f"avg10 and avg1y volume below the sampling margin {MIN_AVG_VOLUME:,}"
    return True, ""


def m2_like_quote(rec: Optional[dict]) -> bool:
    """The review's M2-like stratum on quote fields alone (no bar look-back)."""
    if not rec:
        return False
    o, pc, tv, a10 = rec.get("open"), rec.get("prev_close"), rec.get("total_volume"), rec.get("avg10")
    if not (o and pc and tv and a10):
        return False
    return abs(o / pc - 1.0) >= M2_LIKE_GAP and tv >= M2_LIKE_VOLUME * a10


# =========================================================================================================
# Small I/O helpers
# =========================================================================================================

def now_et() -> dt.datetime:
    return dt.datetime.now(NY)


def log_line(msg: str) -> None:
    """One timestamped line on stdout (launchd's StandardOutPath, a file on the same disk). A line that cannot be
    written (a full disk) is dropped, never raised: an alert path that logs first must still notify."""
    try:
        print(f"[{now_et():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)
    except OSError:
        pass


def iso(t: dt.datetime) -> str:
    return t.astimezone(NY).isoformat(timespec="seconds")


def _say(notify: Optional[Callable[[str, str], None]], message: str,
         log: Optional[Callable[[str], None]] = None) -> None:
    """One notification. A notifier that fails is logged, never raised: an alert path must still finish."""
    if not notify:
        return
    try:
        notify(TITLE, message)
    except Exception as e:                                # noqa: BLE001
        (log or log_line)(f"notification failed ({type(e).__name__}: {e}): {message}")


def stamp(t: dt.datetime, seconds: bool = False) -> str:
    return t.astimezone(NY).strftime("%Y%m%d_%H%M%S" if seconds else "%Y%m%d_%H%M")


def atomic_write_json(path: Path, obj: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=1, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:          # a line cut by a crash is skipped, never fatal
                continue
    return rows


class RunStatus:
    """The per-run heartbeat file, rewritten atomically at each step, plus one runs.jsonl line at the end."""

    def __init__(self, root: Path, session: dt.date, mode: str, started: dt.datetime, **fields) -> None:
        self.root, self.day = Path(root), Path(root) / session.isoformat()
        self.day.mkdir(parents=True, exist_ok=True)
        self.path = self.day / f"status_{mode}_{stamp(started, seconds=True)}.json"
        self.data = dict(mode=mode, session=session.isoformat(), state="STARTED", started=iso(started),
                         updated=iso(started), params_hash=params_hash(), **fields)
        atomic_write_json(self.path, self.data)

    def update(self, now: dt.datetime, **fields) -> None:
        self.data.update(fields, updated=iso(now))
        if self.data["state"] == "STARTED":
            self.data["state"] = "RUNNING"
        atomic_write_json(self.path, self.data)

    def finish(self, now: dt.datetime, state: str, **fields) -> dict:
        self.data.update(fields, state=state, updated=iso(now), finished=iso(now))
        atomic_write_json(self.path, self.data)
        with open(self.root / "runs.jsonl", "a") as fh:
            fh.write(json.dumps(dict(self.data, status_file=str(self.path.relative_to(self.root)))) + "\n")
        return self.data


def statuses(day: Path, mode: Optional[str] = None) -> list[dict]:
    out = []
    for p in sorted(day.glob("status_*.json")):
        try:
            with open(p) as fh:
                s = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if mode is None or s.get("mode") == mode:
            out.append(s)
    return out


def _write_status(root: Path, session: dt.date, mode: str, now: dt.datetime, state: str, *,
                  log: Optional[Callable[[str], None]] = None, token_expires: Optional[str] = None,
                  **fields) -> bool:
    """A one-step status (FAILED, MISSED-NIGHT) with its runs.jsonl line. Its callers notify first; a write that
    fails (a full disk) is logged, never raised, so the alert path always finishes."""
    try:
        RunStatus(root, session, mode, now, token_expires=token_expires).finish(now, state, **fields)
        return True
    except Exception as e:                                # noqa: BLE001
        (log or log_line)(f"{mode} {session}: the {state} status could not be written ({type(e).__name__}: {e})")
        return False


class SessionBusy(RuntimeError):
    """Another run of the same mode holds this session's lock."""


class SessionLock:
    """A non-blocking per-session, per-mode lock: a duplicate launch is SKIPPED, never run twice at once."""

    def __init__(self, day: Path, mode: str) -> None:
        self.path, self.fh = Path(day) / f".{mode}.lock", None

    def __enter__(self) -> "SessionLock":
        import fcntl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a")
        try:
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.fh.close()
            raise SessionBusy(str(self.path))
        return self

    def __exit__(self, *exc) -> None:
        import fcntl
        fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        self.fh.close()


# =========================================================================================================
# Shared request limiter and the read-only market-data wrapper
# =========================================================================================================

class SharedRateLimiter:
    """At most ``per_minute`` requests in any 60 s, across every process that uses the same lock file,
    and at least ``spacing`` seconds between two requests. The timestamps live in the lock file itself.
    (bars.py should adopt this lock path so the nightly and the sampler share one budget, spec 2.)"""

    def __init__(self, path: Path, per_minute: int = PARAMS.request_limit_per_min, spacing: float = 0.6,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep) -> None:
        self.path, self.per_minute, self.spacing, self.clock, self.sleep = Path(path), per_minute, spacing, clock, sleep

    def wait(self) -> None:
        import fcntl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a+") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                fh.seek(0)
                try:
                    stamps = [float(x) for x in fh.read().split()]
                except ValueError:
                    stamps = []
                now = self.clock()
                stamps = [s for s in stamps if now - s < 60.0]
                if len(stamps) >= self.per_minute:
                    self.sleep(60.0 - (now - stamps[-self.per_minute]))
                    now = self.clock()
                if stamps and now - stamps[-1] < self.spacing:
                    self.sleep(self.spacing - (now - stamps[-1]))
                    now = self.clock()
                stamps = [s for s in stamps if now - s < 60.0] + [now]
                fh.seek(0)
                fh.truncate()
                fh.write("\n".join(f"{s:.3f}" for s in stamps[-self.per_minute:]))
                fh.flush()
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class MarketData:
    """The sampler's only view of Schwab: three closures over the runner's client: the client is not an
    attribute of the wrapper, and the contract tests forbid reaching it through the closures. It is built
    outside this package (loops/phase2_sample.py), once per pull, and handed in; this package never builds a
    client (spec 2, review D7).

    daily(symbol, start, end)  -> list of raw daily candles
    minute(symbol, start, end) -> list of raw 1-minute candles (regular session)
    quotes(symbols)            -> {symbol: quote entry}
    """

    __slots__ = ("daily", "minute", "quotes")

    def __init__(self, daily: Callable, minute: Callable, quotes: Callable) -> None:
        self.daily, self.minute, self.quotes = daily, minute, quotes


def require_market_data(md) -> MarketData:
    """``md`` if it is a MarketData of three callables; anything else, a client object above all, is refused."""
    if not isinstance(md, MarketData) or not all(callable(getattr(md, n, None)) for n in MarketData.__slots__):
        raise TypeError(f"the sampler takes only a MarketData wrapper of three read functions, not "
                        f"{type(md).__name__} (spec 2: phase2 code sees only a wrapped client)")
    return md


def fetch_directory_http(url: str) -> bytes:
    """One of the two public Nasdaq Trader symbol-directory files (DIRECTORY). Any other URL is refused before httpx
    is imported: httpx is allowlisted in the package for this one GET (the contract tests pin its uses)."""
    if url not in DIRECTORY.values():
        raise ValueError(f"not a symbol-directory URL: {url!r} (only {', '.join(DIRECTORY.values())})")
    import httpx                                          # certifi CA bundle; verification stays on
    r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0 (symbol-directory reader)"}, timeout=60,
                  follow_redirects=True)
    r.raise_for_status()
    return r.content


# =========================================================================================================
# Pulls
# =========================================================================================================

def pull_daily(md: MarketData, symbols: list[str], session: dt.date, path: Path, mode: str, *,
               clock: Callable[[], dt.datetime], sleep: Callable[[float], None],
               retry_rounds: int = RETRY_ROUNDS, retry_pause: float = RETRY_PAUSE_S,
               heartbeat: Optional[Callable[[int, int], None]] = None) -> dict[str, str]:
    """One row per attempt. TRUNCATED, EMPTY, NO_BAR and ERROR responses are re-pulled in up to
    ``retry_rounds`` further rounds, each after ``retry_pause`` seconds. Returns each symbol's best class."""
    best: dict[str, str] = {}
    todo, s_iso = list(symbols), session.isoformat()
    done = 0
    with open(path, "a") as fh:
        for attempt in range(1, retry_rounds + 2):
            retry = []
            for sym in todo:
                t = clock()
                row = dict(symbol=sym, pulled=iso(t), attempt=attempt, mode=mode, session=s_iso)
                try:
                    raw = md.daily(sym, t - dt.timedelta(days=HISTORY_DAYS[mode]), t)
                    candles = [candle_from_raw(k) for k in raw]
                    cls = response_class(candles, s_iso, mode)
                    row.update(cls=cls, n=len(candles), candles=candles[-KEEP_LAST[mode]:])
                except Exception as e:                    # one bad symbol never stops the sample
                    cls = ERROR
                    row.update(cls=cls, error=f"{type(e).__name__}: {e}"[:200])
                fh.write(json.dumps(row) + "\n")
                fh.flush()
                best[sym] = better_class(best.get(sym), cls)
                if cls in RETRY_CLASSES:
                    retry.append(sym)
                done += 1
                if heartbeat and done % PROGRESS_EVERY == 0:
                    heartbeat(done, attempt)
            if not retry or attempt == retry_rounds + 1:
                break
            sleep(retry_pause)
            todo = retry
    return best


def pull_quotes(md: MarketData, symbols: list[str], path: Path, *, clock, sleep, log,
                chunk: int = QUOTE_CHUNK) -> tuple[dict[str, dict], int]:
    """Quotes in chunks, each chunk tried up to 3 times. Returns ({symbol: record}, failed chunks)."""
    out, failed = {}, 0
    with open(path, "a") as fh:
        for i in range(0, len(symbols), chunk):
            part = symbols[i:i + chunk]
            for attempt in range(1, RETRY_ROUNDS + 1):
                try:
                    q = md.quotes(part)
                    break
                except Exception as e:
                    log(f"quotes chunk {i // chunk + 1} attempt {attempt} failed: {type(e).__name__}: {e}")
                    q = None
                    if attempt < RETRY_ROUNDS:
                        sleep(10.0)
            if q is None:
                failed += 1
                continue
            pulled = iso(clock())
            norm = {s.replace(".", "/"): s for s in part}
            for key, entry in q.items():
                sym = key if key in part else norm.get(key.replace(".", "/"))
                if sym is None or sym in out or not (isinstance(entry, dict) and "quote" in entry):
                    continue
                rec = quote_record(sym, entry, pulled)
                if key != sym:
                    rec["returned_key"] = key
                out[sym] = rec
                fh.write(json.dumps(rec) + "\n")
            fh.flush()
    return out, failed


def pull_minutes(md: MarketData, symbols: list[str], session: dt.date, path: Path, *, clock) -> int:
    """Regular-session 1-minute bars for ``session``; one row per symbol. Returns the number of errors."""
    start = dt.datetime.combine(session, REGULAR_OPEN, NY)
    end = dt.datetime.combine(session, session_close(session), NY)
    errors = 0
    with open(path, "a") as fh:
        for sym in symbols:
            row = dict(symbol=sym, pulled=iso(clock()), session=session.isoformat())
            try:
                raw = md.minute(sym, start, end)
                row["candles"] = [dict(t=dt.datetime.fromtimestamp(k["datetime"] / 1000, NY).strftime("%H:%M"),
                                       o=k["open"], h=k["high"], l=k["low"], c=k["close"], v=k["volume"])
                                  for k in raw]
            except Exception as e:
                errors += 1
                row["error"] = f"{type(e).__name__}: {e}"[:200]
            fh.write(json.dumps(row) + "\n")
            fh.flush()
    return errors


# =========================================================================================================
# The evening sample
# =========================================================================================================

def load_directory(day: Path, root: Path, session: dt.date, fetch: Callable[[str], bytes], log) -> tuple[list[dict], str]:
    """Parse this session's directory files, downloading them if absent. If a download fails, the most
    recent earlier session's archived files are read instead (the provisional candles cannot be fetched
    later, so a directory outage must not cost the night); the source is recorded."""
    folder = day / "directory"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        for name, url in DIRECTORY.items():
            p = folder / name
            if not p.exists():
                data = fetch(url)
                if not (data.startswith(b"Symbol|") or data.startswith(b"ACT Symbol|")):
                    raise ValueError(f"{name}: unexpected content (no directory header)")
                with open(p, "wb") as fh:
                    fh.write(data)
                log(f"directory: {name} {len(data):,} bytes")
        source = f"{session.isoformat()}/directory"
        base = folder
    except Exception as e:
        log(f"directory download failed ({type(e).__name__}: {e}); looking for an earlier archive")
        earlier = sorted(p for p in root.glob("????-??-??") if p.name < session.isoformat()
                         and all((p / "directory" / n).exists() for n in DIRECTORY))
        if not earlier:
            raise
        base = earlier[-1] / "directory"
        source = f"FALLBACK {earlier[-1].name}/directory (download failed: {type(e).__name__})"
    rows = []
    for name in DIRECTORY:
        with open(base / name, encoding="utf-8", errors="replace") as fh:
            rows += parse_directory(fh.read(), name)
    return rows, source


def rows_by_symbol(paths: Iterable[Path]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in paths:
        for r in read_jsonl(p):
            if "symbol" in r:
                out.setdefault(r["symbol"], []).append(r)
    return out


def row_class(r: dict, session: str, mode: str) -> str:
    """A stored row's class, recomputed from its candles (stamps re-read), never trusted from the file."""
    if "error" in r:
        return ERROR
    cs = r.get("candles")
    if cs is None:
        return ERROR
    for c in cs:
        if "ms" in c:
            c["kind"] = stamp_kind(c["ms"])
    return response_class(cs, session, mode)


def best_classes(by_symbol: dict[str, list[dict]], session: str, mode: str) -> dict[str, str]:
    """Each symbol's best class over all its stored rows."""
    out: dict[str, str] = {}
    for sym, rows in by_symbol.items():
        for r in rows:
            out[sym] = better_class(out.get(sym), row_class(r, session, mode))
    return out


def pulled_at(r: dict) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(r["pulled"])
    except (KeyError, ValueError):
        return dt.datetime.max.replace(tzinfo=dt.timezone.utc)


def first_open(rows: list[dict], session: str, kind: str) -> Optional[float]:
    for r in sorted(rows, key=pulled_at):
        for c in r.get("candles") or []:
            if c.get("d") == session and (stamp_kind(c["ms"]) if "ms" in c else c.get("kind")) == kind:
                return c.get("o")
    return None


def evening_rows_exist(day: Path) -> bool:
    """True when the session has at least one usable evening row (legacy rows carry no class field)."""
    s_iso = day.name
    rows = rows_by_symbol(sorted(day.glob("evening_*.jsonl")))
    return any(c in (PROVISIONAL, ALREADY_FINAL) for c in best_classes(rows, s_iso, "evening").values())


def has_evening_sample(day: Path) -> bool:
    """The session has an evening sample a final pull can be paired with: its candidates.json and at least one usable
    evening row. run_final, the missed-night detection and the catch-up all use this one rule, so a session they
    count as sampled is one a final pull can pair (an evening status alone, DONE or INCOMPLETE, is not a sample)."""
    return (day / "candidates.json").exists() and evening_rows_exist(day)


def completeness_needed(n: int) -> int:
    """Candidates that need a bar for a DONE evening: ceil(params.completeness_min x n), in exact arithmetic."""
    return math.ceil(Fraction(repr(PARAMS.completeness_min)) * n)


def run_evening(md: MarketData, *, root: Path = OUT, clock: Callable[[], dt.datetime] = now_et,
                sleep: Callable[[float], None] = time.sleep, fetch: Callable[[str], bytes] = fetch_directory_http,
                notify: Optional[Callable[[str, str], None]] = None, log: Callable[[str], None] = log_line,
                token_expires: Optional[str] = None, notify_incomplete: bool = True) -> int:
    """The evening sample of the last completed session. Exit code: 0 done or skipped, 4 incomplete, 1 failed.

    DONE needs SPY's bar, no quote chunk failed after its retries, and a usable bar for at least
    ``completeness_needed(candidates)`` candidates; otherwise INCOMPLETE, with the names lacking a bar listed
    (first 200) and counted either way. Only a DONE sample blocks a re-run: an INCOMPLETE or FAILED one is
    re-run on the same candidates.json, pulling only the names without a usable bar. ``notify_incomplete``
    False (a night pass's evening attempt that has a retry left) keeps an INCOMPLETE quiet; FAILED and LATE
    always notify. On a failure the notification goes first, then the FAILED status, whose own failure (a
    full disk) is logged, never raised."""
    root = Path(root)
    now = clock()
    session = last_completed_session(now)
    s_iso = session.isoformat()
    day = root / s_iso
    timing, late = evening_timing(now, session)
    done_before = [s for s in statuses(day, "evening") if s.get("state") == "DONE"]
    if timing == "TOO_LATE" or done_before:
        why = late[0] if timing == "TOO_LATE" else (f"{s_iso} already has an evening sample "
                                                    f"({done_before[0]['state']}, started {done_before[0]['started']})")
        RunStatus(root, session, "evening", now, token_expires=token_expires).finish(now, "SKIPPED", reason=why)
        log(f"evening {s_iso}: SKIPPED ({why})")
        return 0
    try:
        lock = SessionLock(day, "evening").__enter__()
    except SessionBusy:
        RunStatus(root, session, "evening", now).finish(now, "SKIPPED", reason="another evening run holds the lock")
        log(f"evening {s_iso}: SKIPPED (another evening run is in progress)")
        return 0
    status: Optional[RunStatus] = None
    try:
        status = RunStatus(root, session, "evening", now, late=bool(late), late_reasons=late,
                           token_expires=token_expires, tags=session_tags(session))
        log(f"evening sample for session {s_iso} ({', '.join(session_tags(session))})" + (f"; LATE: {late}" if late else ""))
        cand_path = day / "candidates.json"
        if cand_path.exists():                             # a re-run after a failure keeps the same universe
            with open(cand_path) as fh:
                cand = json.load(fh)
            symbols, reference = list(cand["symbols"]), list(cand.get("reference", []))
            counts = dict(cand.get("counts", {}))
            log(f"candidates: reusing {len(symbols)} symbols from {cand_path.name}")
            quotes, failed_chunks = pull_quotes(md, symbols + reference, day / f"quotes_{stamp(now)}.jsonl",
                                                clock=clock, sleep=sleep, log=log)
        else:
            rows, dir_source = load_directory(day, root, session, fetch, log)
            kept, excluded = universe_stand_in(rows)
            request = [f for r in kept for f in r["forms"]]
            request += [s for s in REFERENCE if s not in request]
            quotes, failed_chunks = pull_quotes(md, request, day / f"quotes_{stamp(now)}.jsonl",
                                                clock=clock, sleep=sleep, log=log)
            symbols, symbol_map = [], {}
            for r in kept:
                form = next((f for f in r["forms"] if f in quotes), None)
                if form is None:
                    excluded.append(dict(stage="quote", symbol=r["symbol"], name=r["name"], source=r["source"],
                                         reason="no quote returned (requested " + ", ".join(r["forms"]) + ")",
                                         matched=""))
                    continue
                keep, why = quote_decision(quotes[form])
                if not keep:
                    excluded.append(dict(stage="quote", symbol=form, name=r["name"], source=r["source"],
                                         reason=why, matched=""))
                    continue
                symbols.append(form)
                if form != r["symbol"]:
                    symbol_map[form] = r["symbol"]
            reference = list(REFERENCE)                     # always sampled, even if its quote failed
            with open(day / "exclusions.jsonl", "w") as fh:
                for e in excluded:
                    fh.write(json.dumps(e) + "\n")
            by_reason: dict[str, int] = {}
            for e in excluded:
                key = f"{e['stage']}: {e['reason'].split(' (')[0]}"
                by_reason[key] = by_reason.get(key, 0) + 1
            counts = dict(directory_rows=len(rows), directory_kept=len(kept), excluded=len(excluded),
                          excluded_by_reason=by_reason, quoted=len(quotes), candidates=len(symbols),
                          failed_quote_chunks=failed_chunks,
                          kept_notes={n: sum(1 for r in kept if r["note"] == n) for n in sorted({r["note"] for r in kept}) if n})
            cand = dict(session=s_iso, built=iso(now), params_hash=params_hash(), symbols=symbols,
                        reference=reference, directory_symbol=symbol_map, directory_source=dir_source,
                        universe_rules="spec 3.1 stand-in (sample_bars.py docstring)", counts=counts)
            atomic_write_json(cand_path, cand)
            log(f"universe stand-in: {len(rows)} directory rows, {len(kept)} kept by the directory rules, "
                f"{len(symbols)} candidates after the quote stage; reference {reference}")
        if failed_chunks:
            log(f"WARNING: {failed_chunks} quote chunk(s) failed after retries")
        status.update(clock(), counts=counts)
        usable = {s for s, c in best_classes(rows_by_symbol(sorted(day.glob("evening_*.jsonl"))), s_iso, "evening").items()
                  if c in (PROVISIONAL, ALREADY_FINAL)}
        todo = [s for s in symbols + reference if s not in usable]
        pull_daily(md, todo, session, day / f"evening_{stamp(now)}.jsonl", "evening", clock=clock, sleep=sleep,
                   heartbeat=lambda n, a: status.update(clock(), progress=f"{n} responses, round {a}"))
        best = best_classes(rows_by_symbol(sorted(day.glob("evening_*.jsonl"))), s_iso, "evening")
        tally = {c: sum(1 for s in symbols if best.get(s) == c) for c in sorted({best.get(s, ERROR) for s in symbols})}
        already = tally.get(ALREADY_FINAL, 0)
        if already:
            late = late + [f"{already} candidate(s) already had a final candle"]
        missing_ref = [s for s in REFERENCE if best.get(s) not in (PROVISIONAL, ALREADY_FINAL)]
        incomplete = [s for s in symbols if best.get(s) not in (PROVISIONAL, ALREADY_FINAL)]
        with_bar, needed = len(symbols) - len(incomplete), completeness_needed(len(symbols))
        why = ([f"reference {', '.join(missing_ref)} has no bar"] if missing_ref else []) + \
              ([f"{failed_chunks} quote chunk(s) failed after retries"] if failed_chunks else []) + \
              (["no candidates"] if not symbols else []) + \
              ([f"{with_bar} of {len(symbols)} candidates have a bar, fewer than {needed} (params.completeness_min "
                f"{PARAMS.completeness_min:g})"] if with_bar < needed else [])
        state = "INCOMPLETE" if why else "DONE"
        status.finish(clock(), state, late=bool(late), late_reasons=late, classes=tally, requested=len(todo),
                      reference_missing=missing_ref, incomplete_symbols=incomplete[:200],
                      incomplete_count=len(incomplete), incomplete_reasons=why,
                      completeness=dict(with_bar=with_bar, candidates=len(symbols), needed=needed))
        log(f"evening {s_iso}: {state}{' LATE' if late else ''}; classes {tally}; reference missing {missing_ref}"
            + (f"; {'; '.join(why)}" if why else ""))
        if (state == "INCOMPLETE" and notify_incomplete) or late:
            detail = (f"{len(incomplete)} incomplete" + (f"; {', '.join(missing_ref)} has no bar" if missing_ref else "")
                      + (f"; {failed_chunks} quote chunk(s) failed" if failed_chunks else ""))
            _say(notify, f"evening {s_iso}: {state}{' LATE' if late else ''} ({detail})", log)
        return 4 if state == "INCOMPLETE" else 0
    except Exception as e:
        log(f"evening {s_iso}: FAILED {type(e).__name__}: {e}")
        _say(notify, f"evening {s_iso} FAILED: {type(e).__name__}", log)        # first: a full disk must not silence it
        if status is not None:
            try:
                status.finish(clock(), "FAILED", error=f"{type(e).__name__}: {e}"[:300])
            except Exception as e2:                       # noqa: BLE001
                log(f"evening {s_iso}: the FAILED status could not be written ({type(e2).__name__}: {e2})")
        return 1
    finally:
        lock.__exit__(None, None, None)


# =========================================================================================================
# The overnight (final) pulls
# =========================================================================================================

def run_final(md: MarketData, *, root: Path = OUT, session: Optional[dt.date] = None,
              clock: Callable[[], dt.datetime] = now_et, sleep: Callable[[float], None] = time.sleep,
              notify: Optional[Callable[[str, str], None]] = None, log: Callable[[str], None] = log_line,
              full: bool = False, minute_bars: bool = True, token_expires: Optional[str] = None,
              notify_incomplete: bool = True) -> int:
    """An overnight pull for ``session`` (default: the last completed one). The first pull of a session
    takes every symbol; later ones only the symbols without a FINAL row yet (``full`` takes all again).
    ``notify_incomplete`` False (a night pass's pull before its last target) keeps an INCOMPLETE quiet;
    FAILED and MISSED-NIGHT always notify, MISSED-NIGHT once per session whichever mode flagged it first.
    On a failure the notification goes first, then the FAILED status (its own failure is logged, never raised).
    Exit code: 0 done, 4 incomplete, 3 MISSED-NIGHT, 1 failed."""
    root = Path(root)
    now = clock()
    session = session or last_completed_session(now)
    s_iso = session.isoformat()
    day = root / s_iso
    if not has_evening_sample(day):
        why = f"no evening sample for {s_iso}: the final bars are not paired with any other session's sample"
        if not any(s.get("state") == "MISSED-NIGHT" for s in statuses(day)):      # any mode: notified once
            _say(notify, f"MISSED-NIGHT {s_iso}: no evening sample", log)
            _write_status(root, session, "final", now, "MISSED-NIGHT", log=log, token_expires=token_expires,
                          reason=why)
        log(f"final {s_iso}: MISSED-NIGHT ({why})")
        return 3
    try:
        lock = SessionLock(day, "final").__enter__()
    except SessionBusy:
        RunStatus(root, session, "final", now).finish(now, "SKIPPED", reason="another final run holds the lock")
        log(f"final {s_iso}: SKIPPED (another final run is in progress)")
        return 0
    status: Optional[RunStatus] = None
    try:
        status = RunStatus(root, session, "final", now, token_expires=token_expires, tags=session_tags(session))
        with open(day / "candidates.json") as fh:
            cand = json.load(fh)
        symbols, reference = list(cand["symbols"]), list(cand.get("reference", []))
        earlier = rows_by_symbol(sorted(day.glob("final_*.jsonl")))
        have_final = {s for s, c in best_classes(earlier, s_iso, "final").items() if c == FINAL}
        todo = [s for s in symbols + reference if full or s not in have_final]
        scope = "full" if full or not earlier else "symbols without a FINAL row yet"
        log(f"final pull for {s_iso}: {len(todo)} symbols ({scope}; {len(have_final)} already final)")
        status.update(clock(), scope=scope, requested=len(todo))
        best = pull_daily(md, todo, session, day / f"final_{stamp(now)}.jsonl", "final", clock=clock, sleep=sleep,
                          heartbeat=lambda n, a: status.update(clock(), progress=f"{n} responses, round {a}"))
        tally = {c: sum(1 for s in todo if best.get(s) == c) for c in sorted(set(best.values()))}
        finals = rows_by_symbol(sorted(day.glob("final_*.jsonl")))
        final_now = {s for s, c in best_classes(finals, s_iso, "final").items() if c == FINAL}
        evening = rows_by_symbol(sorted(day.glob("evening_*.jsonl")))
        ev_cls = best_classes(evening, s_iso, "evening")
        with_bar = [s for s in symbols if ev_cls.get(s) in (PROVISIONAL, ALREADY_FINAL)]
        unfinished = [s for s in with_bar if s not in final_now]
        minute_errors, wanted = 0, []
        if minute_bars:
            done_minutes = {sym for sym, rows in rows_by_symbol(sorted(day.glob("minute_*.jsonl"))).items()
                            if any(r.get("candles") for r in rows)}
            quotes: dict[str, dict] = {}
            for p in sorted(day.glob("quotes_*.jsonl")):
                for r in read_jsonl(p):
                    quotes.setdefault(r.get("symbol"), r)
            for s in reference + symbols:
                if s in done_minutes or s not in final_now:
                    continue
                ev_open = first_open(evening.get(s, []), s_iso, "provisional")
                fin_open = first_open(finals.get(s, []), s_iso, "final")
                if s in reference or m2_like_quote(quotes.get(s)) or (
                        ev_open is not None and fin_open is not None and abs(ev_open - fin_open) > 1e-9):
                    wanted.append(s)
            if wanted:
                log(f"1-minute bars: {len(wanted)} symbols (reference, open differences, M2-like)")
                minute_errors = pull_minutes(md, wanted, session, day / f"minute_{stamp(now)}.jsonl", clock=clock)
        ref_missing = [s for s in reference if s not in final_now]
        state = "INCOMPLETE" if unfinished or ref_missing else "DONE"
        coverage = (len(with_bar) - len(unfinished)) / len(with_bar) if with_bar else 0.0
        status.finish(clock(), state, classes=tally, final_coverage=round(coverage, 6), unfinished=len(unfinished),
                      unfinished_symbols=unfinished[:200], minute_symbols=len(wanted), minute_errors=minute_errors,
                      reference_final=[s for s in reference if s in final_now])
        log(f"final {s_iso}: {state}; this pull {tally}; FINAL coverage {coverage:.2%} ({len(unfinished)} unfinished)")
        if state != "DONE" and notify_incomplete:
            _say(notify, f"final {s_iso}: {state}, {len(unfinished)} names not final"
                         + (f", {', '.join(ref_missing)} not final" if ref_missing else ""), log)
        return 4 if state == "INCOMPLETE" else 0
    except Exception as e:
        log(f"final {s_iso}: FAILED {type(e).__name__}: {e}")
        _say(notify, f"final {s_iso} FAILED: {type(e).__name__}", log)          # first: a full disk must not silence it
        if status is not None:
            try:
                status.finish(clock(), "FAILED", error=f"{type(e).__name__}: {e}"[:300])
            except Exception as e2:                       # noqa: BLE001
                log(f"final {s_iso}: the FAILED status could not be written ({type(e2).__name__}: {e2})")
        return 1
    finally:
        lock.__exit__(None, None, None)


# =========================================================================================================
# Scheduling, the missed-night detection and the command line
# =========================================================================================================

def parse_times(spec: Optional[str]) -> list[dt.time]:
    """'HH:MM[,HH:MM...]' as times; blank parts are skipped (an empty ``--full-at`` means no full pull)."""
    out = []
    for part in (spec or "").split(","):
        if part.strip():
            h, m = (int(x) for x in part.strip().split(":"))
            out.append(dt.time(h, m))
    return out


def final_targets(session: dt.date, times: list[dt.time]) -> list[dt.datetime]:
    """Times at or after 16:00 fall on the session day; earlier times on the next calendar day (sorted, once each)."""
    out = set()
    for t in times:
        day = session if t >= dt.time(16, 0) else session + dt.timedelta(days=1)
        out.add(dt.datetime.combine(day, t, NY))
    return sorted(out)


def wait_due(targets: list[dt.datetime], clock: Callable[[], dt.datetime], sleep: Callable[[float], None],
             log: Callable[[str], None] = log_line, stop: Optional[Callable[[dt.datetime], bool]] = None):
    """Yield, once per wake, the list of targets now due. Targets that passed while the Mac slept (or before a
    late start) are collapsed into one list: one pull. The wait reads the wall clock in short naps, so a
    sleeping Mac does not stretch it. ``stop(now)``, when given, is asked each time targets are due, before
    anything is yielded: True ends the wait there (the night pass that leaves its pulls to the next pass)."""
    i = 0
    while i < len(targets):
        now = clock()
        if targets[i] <= now:
            if stop is not None and stop(now):
                return
            due = [t for t in targets[i:] if t <= now]
            if len(due) > 1:
                log("targets " + ", ".join(f"{t:%H:%M}" for t in due) + " have passed (the Mac slept, or the job "
                    "started late): one pull now")
            i += len(due)
            yield due
        else:
            sleep(min(15.0, max(1.0, (targets[i] - now).total_seconds())))


def wait_until(targets: list[dt.datetime], clock: Callable[[], dt.datetime], sleep: Callable[[float], None],
               log: Callable[[str], None] = log_line):
    """``wait_due``, yielding the last due target of each wake."""
    for due in wait_due(targets, clock, sleep, log):
        yield due[-1]


def _token_gate(root: Path, mode: str, notify, token_hours: Callable[[], tuple],
                session: Optional[dt.date] = None) -> tuple[bool, Optional[str], Optional[float]]:
    """(passed, expiry, hours left). Fail closed unless the token has params.token_min_hours of life left (spec 4,
    step 1). ``token_hours`` is the runner's reader, () -> (hours left or None, expiry ISO or None): None, an error
    or a malformed answer means the token is unreadable, and that fails closed too. On a failure the notification
    goes first, then the FAILED status."""
    try:
        left, expires = token_hours()
        left = None if left is None else float(left)
        expires = None if expires is None else str(expires)
    except Exception:                                     # noqa: BLE001
        left, expires = None, None
    if left is not None and left >= PARAMS.token_min_hours:
        return True, expires, left
    now = now_et()
    why = "token unreadable" if left is None else f"token has {left:.1f} h left (< {PARAMS.token_min_hours:g} h)"
    log_line(f"{mode}: FAILED ({why}); re-authenticate with setup_auth.py")
    _say(notify, f"{mode} FAILED: {why}; re-authenticate with setup_auth.py")
    _write_status(root, session or last_completed_session(now), mode, now, "FAILED", token_expires=expires,
                  error=why)
    return False, expires, left


def night_session(start: dt.datetime) -> dt.date:
    """The session a ``night`` pass started at ``start`` samples. Key the night to a session at launch, never to
    the calendar date: a job launchd runs late, on wake after midnight, belongs to the previous session (LATE
    until 04:00). A launch on a session day after 04:00 keys to that day's session and waits for its evening;
    the session it skipped gets no sample, and the missed-night detection at the start of every pass records
    it as MISSED-NIGHT with a notification (review D1; IF-11)."""
    session = last_completed_session(start)
    if evening_timing(start, session)[0] == "TOO_LATE" and is_session(start.date()):
        session = start.date()
    return session


def _failed(root: Path, mode: str, notify, session: Optional[dt.date], why: str) -> int:
    """A run that cannot start (no runner, no wrapper): a notification first, then a FAILED status (logged if it
    cannot be written), never a silent loss."""
    now = now_et()
    session = session or last_completed_session(now)
    log_line(f"{mode}: FAILED ({why})")
    _say(notify, f"{mode} FAILED: {why[:120]}")
    _write_status(root, session, mode, now, "FAILED", error=why[:300])
    return 1


def _evening_usable(day: Path) -> bool:
    """The session has a usable evening sample, by run_final's own rule (``has_evening_sample``: candidates.json and
    a usable evening row). An evening status alone is not one: an INCOMPLETE evening with no usable row is
    MISSED-NIGHT to run_final, so the catch-up never asks for its final pull."""
    return day.is_dir() and has_evening_sample(day)


def _started(st: dict) -> Optional[dt.datetime]:
    """A status's start time (timezone-aware), or None when it is missing or unreadable."""
    try:
        t = dt.datetime.fromisoformat(st["started"])
    except (KeyError, TypeError, ValueError):
        return None
    return t if t.tzinfo is not None else None


def _at_or_after(t: Optional[dt.datetime], target: dt.datetime) -> bool:
    """``t`` is at or after ``target``, compared as instants (UTC); an unreadable time counts as at or after."""
    return t is None or t.astimezone(dt.timezone.utc) >= target.astimezone(dt.timezone.utc)


def default_last_target(session: dt.date) -> dt.datetime:
    """The last overnight target of the default schedule (FINAL_AT_DEFAULT and FULL_AT_DEFAULT): 07:30 the next day."""
    return final_targets(session, parse_times(FINAL_AT_DEFAULT) + parse_times(FULL_AT_DEFAULT))[-1]


def night_complete(day: Path, last_target: dt.datetime) -> bool:
    """The session's night is complete as far as it goes: it has an evening sample, and a final pull that started
    at or after its last overnight target ended DONE or INCOMPLETE (the catch-up rule's 'completed'). A pass
    keyed to it again (a weekday-holiday launch, a weekend login) has nothing left to do for it."""
    if not has_evening_sample(day):
        return False
    return any(s.get("state") in ("DONE", "INCOMPLETE") and _started(s) is not None
               and _at_or_after(_started(s), last_target) for s in statuses(day, "final"))


def sampled_sessions(root: Path) -> list[dt.date]:
    """Sessions this sampler has written: folders named by an ISO date inside the carried calendar that is a
    session, holding at least one status file (legacy folders without one are ignored)."""
    out = []
    for p in sorted(Path(root).glob("????-??-??")):
        try:
            d = dt.date.fromisoformat(p.name)
        except ValueError:
            continue
        if p.is_dir() and CALENDAR_FIRST <= d <= CALENDAR_LAST and is_session(d) and any(p.glob("status_*.json")):
            out.append(d)
    return out


def recent_sessions(root: Path, upto: dt.date) -> list[dt.date]:
    """The sessions the missed-night detection and the catch-up look at: every session from the earliest folder
    this sampler wrote up to, but excluding, ``upto``; at most the last MISSED_LOOKBACK of them. None at all
    before this sampler has written a status file."""
    have = sampled_sessions(root)
    if not have or have[0] >= upto:
        return []
    return sessions_between(have[0], upto - dt.timedelta(days=1))[-MISSED_LOOKBACK:]


def record_missed(root: Path, upto: dt.date, now: dt.datetime, notify,
                  log: Callable[[str], None] = log_line) -> list[dt.date]:
    """The missed-night detection (IF-11; the owner: alert me if a nightly run misses its window), run first by
    every network run. Each session in ``recent_sessions(root, upto)`` with no usable evening sample and no
    MISSED-NIGHT status yet, in any mode, gets a MISSED-NIGHT status (mode 'evening', naming the session and the
    detection time) with its runs.jsonl line. A usable evening sample is run_final's rule (``has_evening_sample``:
    candidates.json and a usable evening row); an evening status alone, DONE or INCOMPLETE, is not one. ONE
    notification lists them all, sent before the statuses are written. Returns the sessions newly flagged."""
    root = Path(root)
    missed = [s for s in recent_sessions(root, upto)
              if not _evening_usable(root / s.isoformat())
              and not any(st.get("state") == "MISSED-NIGHT" for st in statuses(root / s.isoformat()))]
    if not missed:
        return []
    names = ", ".join(f"{s:%a} {s.isoformat()}" for s in missed)
    log(f"missed-night detection at {iso(now)} (run for {upto}): no evening sample for {names}")
    _say(notify, f"MISSED-NIGHT {names}: no evening sample (detected {now.astimezone(NY):%a %m-%d %H:%M})", log)
    for s in missed:
        _write_status(root, s, "evening", now, "MISSED-NIGHT", log=log,
                      reason=f"no evening sample for {s}: detected {iso(now)} by the run for {upto}")
    return missed


def catch_up_sessions(root: Path, upto: dt.date,
                      last_target: Optional[Callable[[dt.date], Optional[dt.datetime]]] = None) -> list[dt.date]:
    """Sessions in ``recent_sessions(root, upto)`` that have an evening sample but whose overnight pulls never
    completed: no final pull ended DONE, and every final pull that ended INCOMPLETE started before the session's
    last overnight target (a night whose process died, slept through its pulls, or failed its token checks after
    an INCOMPLETE pull). FAILED, SKIPPED and MISSED-NIGHT final statuses do not count either way. An INCOMPLETE pull
    that started at or after the last target completed the night as far as it went. Each session found gets one
    catch-up final pull, which re-pulls only the names without a FINAL row (run_final's default scope).
    ``last_target(session)`` is that target: night_pass passes its own schedule's; the default is the default
    schedule's (07:30 the next day); None (no overnight schedule) lets any INCOMPLETE pull complete the night.
    Sessions without an evening sample are never pulled (they are MISSED-NIGHT)."""
    root = Path(root)
    last_target = last_target or default_last_target
    out = []
    for s in recent_sessions(root, upto):
        day = root / s.isoformat()
        if not _evening_usable(day):
            continue
        finals = statuses(day, "final")
        if any(st.get("state") == "DONE" for st in finals):
            continue
        incomplete = [_started(st) for st in finals if st.get("state") == "INCOMPLETE"]
        end = last_target(s) if incomplete else None
        if incomplete and (end is None or any(_at_or_after(t, end) for t in incomplete)):
            continue                                      # completed as far as it went
        out.append(s)
    return out


def _session_arg(text: str) -> tuple[Optional[dt.date], str]:
    """``final --session``: (the date, '') or (None, why it is refused). Only a session inside the carried calendar,
    after the sealed window and not later than the last completed session is accepted (safety S9)."""
    try:
        d = dt.date.fromisoformat(text)
    except ValueError:
        return None, "not an ISO date (YYYY-MM-DD)"
    if not CALENDAR_FIRST <= d <= CALENDAR_LAST:
        return None, f"outside the NYSE calendar carried here ({CALENDAR_FIRST}..{CALENDAR_LAST})"
    if d <= SAMPLE_AFTER:
        return None, f"not after {SAMPLE_AFTER}, the end of the sealed window (spec 3.7)"
    if not is_session(d):
        return None, "not an NYSE session"
    last = last_completed_session(now_et())
    if d > last:
        return None, f"later than the last completed session, {last}"
    return d, ""


def _plan(a: argparse.Namespace) -> int:
    """Session keying and the night's schedule for ``--now`` (default: now). No network, no token, no file."""
    now = dt.datetime.fromisoformat(a.now).astimezone(NY) if a.now else now_et()
    s = last_completed_session(now)
    timing, why = evening_timing(now, s)
    print(f"now {iso(now)} -> last completed session {s} ({', '.join(session_tags(s))})")
    print(f"an evening sample now would be {timing}{(': ' + '; '.join(why)) if why else ''}")
    ns, ev_t = night_session(now), parse_times(a.evening_at)[0]
    ev = dt.datetime.combine(ns, ev_t, NY)
    print(f"a night job started now samples session {ns} ({', '.join(session_tags(ns))}):")
    print(f"  idle-sleep assertion from {ev - AWAKE_LEAD:%a %m-%d %H:%M}; evening sample {ev:%a %m-%d %H:%M}, retried "
          f"at {', '.join(PARAMS.evening_retry_et)} while FAILED or INCOMPLETE; LATE after {LATE_AFTER:%H:%M}")
    full = set(final_targets(ns, parse_times(a.full_at)))
    targets = final_targets(ns, parse_times(a.final_at) + parse_times(a.full_at))
    print("  overnight pulls: " + ", ".join(f"{t:%a %m-%d %H:%M}" + (" (full)" if t in full else "") for t in targets))
    try:
        nxt = next_session(ns)
        print(f"  a pass whose last pull ends after {dt.datetime.combine(nxt, ev_t, NY) - AWAKE_LEAD:%a %m-%d %H:%M} "
              f"rolls over into {nxt}'s night (at most {MAX_PASSES} passes per process)")
    except CalendarError as e:
        print(f"  roll-over: {e}")
    return 0


_RANK = {0: 0, 4: 1, 3: 2, 1: 3}


def worse(a: int, b: int) -> int:
    """The worse of two run codes: 1 FAILED > 3 MISSED-NIGHT > 4 INCOMPLETE > 0 (an unknown code counts as 1)."""
    return a if _RANK.get(a, 3) >= _RANK.get(b, 3) else b


def _when(expires: Optional[str]) -> str:
    try:
        return dt.datetime.fromisoformat(expires).astimezone(NY).strftime("%a %m-%d %H:%M")
    except (TypeError, ValueError):
        return str(expires)


class _Job:
    """One process's network work. Every pull runs its own token check, then asks the runner's factory for a
    fresh wrapper: a client never outlives its pull, so a re-authentication between pulls is never reverted."""

    def __init__(self, a: argparse.Namespace, root: Path, market_data: Callable[[], MarketData],
                 token_hours: Callable[[], tuple], notify, awake) -> None:
        self.a, self.root = a, root
        self.market_data, self.token_hours, self.notify, self.awake = market_data, token_hours, notify, awake
        self.token_alerted = False                        # a run of failed token checks notifies once
        self.warned = False                               # the token warning, once per night pass

    # --- one pull ----------------------------------------------------------------------------------------------
    def gate(self, mode: str, session: Optional[dt.date]) -> tuple[bool, Optional[str], Optional[float]]:
        """The pull's token check. A run of failed checks notifies once; a check that passes re-arms the
        notification, so a later failure is notified again."""
        ok, expires, left = _token_gate(self.root, mode, None if self.token_alerted else self.notify,
                                        self.token_hours, session)
        self.token_alerted = not ok
        return ok, expires, left

    def wrapper(self, mode: str, session: Optional[dt.date]) -> tuple[Optional[MarketData], int]:
        try:
            return require_market_data(self.market_data()), 0
        except Exception as e:                            # the runner's factory failed, or returned a non-wrapper
            return None, _failed(self.root, mode, self.notify, session,
                                 f"the market-data wrapper could not be built: {type(e).__name__}: {e}")

    def evening(self, session: Optional[dt.date] = None, *, notify_incomplete: bool = True,
                warn_until: Optional[dt.datetime] = None) -> Optional[int]:
        """One evening sample: the token check, a fresh wrapper, run_evening. In a night pass (``session`` given) the
        attempt is not made (None, nothing written) when, once the wrapper is built, ``session`` is no longer the
        last completed session: run_evening keys itself again, and a wake just before the next close would file an
        evening for the next session at its close. ``warn_until`` (the pass's last overnight pull): the pass's
        first attempt whose token check passed sends the token warning once its pull has finished."""
        checked = now_et()
        ok, expires, left = self.gate("evening", session)
        if not ok:
            return 1
        md, rc = self.wrapper("evening", session)
        if md is not None:
            now = now_et()
            if session is not None and last_completed_session(now) != session:
                log_line(f"evening {session}: no attempt at {now:%a %m-%d %H:%M:%S}: {last_completed_session(now)} "
                         f"completed while the wrapper was built; nothing written")
                return None
            rc = run_evening(md, root=self.root, clock=now_et, sleep=time.sleep, fetch=fetch_directory_http,
                             notify=self.notify, log=log_line, token_expires=expires,
                             notify_incomplete=notify_incomplete)
        if warn_until is not None and not self.warned:
            self.warned = True
            self.token_warning(left, expires, warn_until, checked)
        return rc

    def final(self, session: dt.date, *, full: bool, notify_incomplete: bool = True) -> int:
        ok, expires, _ = self.gate("final", session)
        if not ok:
            return 1
        md, rc = self.wrapper("final", session)
        if md is None:
            return rc
        return run_final(md, root=self.root, session=session, clock=now_et, sleep=time.sleep, notify=self.notify,
                         log=log_line, full=full, minute_bars=not self.a.no_minute, token_expires=expires,
                         notify_incomplete=notify_incomplete)

    def token_warning(self, left: Optional[float], expires: Optional[str], last_pull: dt.datetime,
                      checked: dt.datetime) -> None:
        """Once per pass, after its first evening attempt whose token check passed (at ``checked``, with ``left`` hours
        of life): a token that expires less than params.token_min_hours after the pass's last overnight pull would
        fail that pull's check, so warn, and sample anyway. It is sent when that attempt's pull has finished, so no
        pull runs until a retry or the first overnight target, and re-authenticating on it never meets a running
        pull. Hours are counted between instants (UTC), so a DST change does not move them."""
        if left is None:
            return
        utc = dt.timezone.utc
        need = (last_pull.astimezone(utc) - checked.astimezone(utc)).total_seconds() / 3600.0 + PARAMS.token_min_hours
        if left < need:
            log_line(f"token: {left:.1f} h left at {checked:%H:%M}, {need:.1f} h needed (to {last_pull:%a %H:%M} plus "
                     f"{PARAMS.token_min_hours:g} h): warning sent, sampling anyway")
            when = _when(expires) if expires else \
                f"{(checked.astimezone(utc) + dt.timedelta(hours=left)).astimezone(NY):%a %m-%d %H:%M}"
            _say(self.notify, f"the token expires at {when}, less than {PARAMS.token_min_hours:g} h after tonight's "
                              f"last overnight pull ({last_pull.astimezone(NY):%a %m-%d %H:%M}); re-authenticate "
                              f"before then")

    def hold(self, on: bool) -> None:
        """The runner's idle-sleep assertion on or off (its awake callable is idempotent); a failure is logged."""
        if self.awake is None:
            return
        try:
            self.awake(on)
        except Exception as e:                            # noqa: BLE001
            log_line(f"idle-sleep assertion {'on' if on else 'off'} failed: {type(e).__name__}: {e}")

    # --- the modes ---------------------------------------------------------------------------------------------
    def evening_mode(self) -> int:
        if self.a.at:
            for _ in wait_until([dt.datetime.combine(now_et().date(), parse_times(self.a.at)[0], NY)], now_et,
                                time.sleep, log_line):
                pass
        now = now_et()
        record_missed(self.root, last_completed_session(now), now, self.notify, log_line)
        return self.evening()

    def final_mode(self, session: dt.date) -> int:
        record_missed(self.root, session, now_et(), self.notify, log_line)
        times = parse_times(self.a.at)
        targets = final_targets(session, times) if times else [now_et()]
        rc = 0
        for due in wait_due(targets, now_et, time.sleep, log_line):
            rc = self.final(session, full=self.a.full, notify_incomplete=due[-1] == targets[-1])
            if rc == 3:                                   # MISSED-NIGHT: later targets cannot fix it
                break
        return rc

    def night(self) -> int:
        """Passes, at most MAX_PASSES: a pass that ends after the next session's evening start minus AWAKE_LEAD rolls
        over into that session's night, since launchd dropped the launch it delivered while this process ran (one
        process per label). The last pass allowed exits instead, with a notification naming the session that is
        then not sampled. Returns the worst of the passes' outcomes; releases the assertion on exit."""
        a = self.a
        ev_t = parse_times(a.evening_at)[0]
        retry_ts = [dt.time.fromisoformat(t) for t in PARAMS.evening_retry_et]
        pulls, fulls = parse_times(a.final_at), parse_times(a.full_at)
        worst = 0
        try:
            for n in range(1, MAX_PASSES + 1):
                session = night_session(now_et())
                worst = worse(worst, self.night_pass(session, ev_t, retry_ts, pulls, fulls,
                                                     may_defer=n < MAX_PASSES))
                nxt = next_session(session)
                roll_at = dt.datetime.combine(nxt, ev_t, NY) - AWAKE_LEAD
                now = now_et()
                if now < roll_at:
                    break
                if n == MAX_PASSES:
                    log_line(f"night {session}: this pass ended {now:%a %m-%d %H:%M}, after {roll_at:%a %m-%d %H:%M}, "
                             f"but this process has made {MAX_PASSES} passes: exiting")
                    _say(self.notify, f"night: this process has made {MAX_PASSES} passes and exits; {nxt:%a} {nxt}'s "
                                      f"evening will not be sampled unless the job is started again")
                    break
                log_line(f"night {session}: this pass ended {now:%a %m-%d %H:%M}, after {nxt}'s evening start minus "
                         f"{int(AWAKE_LEAD.total_seconds() // 60)} min ({roll_at:%a %m-%d %H:%M}); launchd dropped that "
                         f"launch while this process ran, so it rolls over into pass {n + 1} (at most {MAX_PASSES})")
            return worst
        finally:
            self.hold(False)

    def night_pass(self, session: dt.date, ev_t: dt.time, retry_ts: list[dt.time], pulls: list[dt.time],
                   fulls: list[dt.time], *, may_defer: bool = True) -> int:
        """One session's night. The missed-night detection first. A session whose night is already complete
        (``night_complete``: a weekday-holiday launch, a weekend login) gets nothing more: no attempt, no pull, no
        assertion. Otherwise the catch-up pulls, the evening sample with its retries, then the overnight pulls (full
        where a --full-at target is among those due). A daytime start makes the catch-up pulls while it waits for
        the evening, without the assertion; a start at or after the hold time (a late start or a roll-over) holds
        the Mac awake at once and takes the evening sample before the catch-up pulls, so they never make it LATE.
        With ``may_defer`` (another pass may follow in this process), a wake that finds the next session's evening
        due (``_next_evening_due``) makes none of the pulls still due: they are left to the next pass's catch-up,
        which runs after that pass's evening sample. Returns the pass's outcome: the worst of its catch-up pulls, its
        last evening attempt and its last overnight pull (none, 0, when its pulls were left to the next pass)."""
        start = now_et()
        self.warned = False
        hold_at = dt.datetime.combine(session, ev_t, NY) - AWAKE_LEAD
        targets = final_targets(session, pulls + fulls)
        full = set(final_targets(session, fulls))
        last_pull = targets[-1] if targets else None
        log_line(f"night pass for session {session} ({', '.join(session_tags(session))}), started {iso(start)}")
        record_missed(self.root, session, start, self.notify, log_line)
        if last_pull is not None and night_complete(self.root / session.isoformat(), last_pull):
            log_line(f"night {session}: nothing left for {session} (an evening sample, and a final pull DONE or INCOMPLETE that "
                     f"started at or after its last target, {last_pull:%a %m-%d %H:%M}): no attempt, no pull")
            return 0
        if start >= hold_at:                              # a late start or a roll-over: hold the Mac awake at once,
            self.hold(True)                               # and sample the evening before any catch-up pull
            worst = self.evening_attempts(session, ev_t, retry_ts, last_pull)
            worst = worse(worst, self.catch_ups(session, pulls + fulls))
        else:                                             # a daytime start: the catch-up pulls while it waits,
            worst = self.catch_ups(session, pulls + fulls)    # without the assertion
            for _ in wait_until([hold_at], now_et, time.sleep, log_line):
                pass
            self.hold(True)
            worst = worse(worst, self.evening_attempts(session, ev_t, retry_ts, last_pull))
        last, left = 0, []                                # only the last overnight pull counts in the outcome

        def defer(now: dt.datetime) -> bool:
            nxt = self._next_evening_due(session, ev_t, now) if may_defer else None
            if nxt is not None:
                left.append((now, nxt))
            return nxt is not None
        for due in wait_due(targets, now_et, time.sleep, log_line, stop=defer):
            last = self.final(session, full=any(t in full for t in due), notify_incomplete=due[-1] == targets[-1])
            if last == 3:                                 # MISSED-NIGHT: later targets cannot fix it
                break
        if left:
            now, nxt = left[0]
            log_line(f"night {session}: woke {now:%a %m-%d %H:%M} with pulls still due, and {nxt}'s evening is due: "
                     f"they are left to {nxt}'s pass, whose catch-up pulls {session} after its evening sample")
            last = 0
        self.hold(False)
        return worse(worst, last)

    @staticmethod
    def _next_evening_due(session: dt.date, ev_t: dt.time, now: dt.datetime) -> Optional[dt.date]:
        """The next session when its evening is due: ``now`` is at or after its evening start minus AWAKE_LEAD and it
        is the last completed session. None otherwise, and None when the calendar ends (night() reports that after
        the pass, so the session's own pulls are still made)."""
        try:
            nxt = next_session(session)
            if now >= dt.datetime.combine(nxt, ev_t, NY) - AWAKE_LEAD and last_completed_session(now) == nxt:
                return nxt
        except CalendarError:
            pass
        return None

    def catch_ups(self, session: dt.date, times: list[dt.time]) -> int:
        """One catch-up final pull for each session ``catch_up_sessions`` finds (each session's last target from this
        night's schedule, ``times``). Returns the worst of their codes."""
        worst = 0
        for s in catch_up_sessions(self.root, session, last_target=lambda x: (final_targets(x, times) or [None])[-1]):
            log_line(f"night {session}: catch-up final pull for {s} (evening sample present; no final pull DONE, and "
                     f"none INCOMPLETE that started at or after its last target)")
            worst = worse(worst, self.final(s, full=False, notify_incomplete=True))
        return worst

    def evening_attempts(self, session: dt.date, ev_t: dt.time, retry_ts: list[dt.time],
                         last_pull: Optional[dt.datetime]) -> int:
        """The evening sample at --evening-at, retried at params.evening_retry_et on the session day (a time
        already past runs at once, collapsed) while it returns FAILED (1) or INCOMPLETE (4); it stops at the first
        0. Only the last attempt notifies an INCOMPLETE; when the attempts end INCOMPLETE and no attempt made could
        notify it (the later retries were not made), one notification says so: "evening <session>: INCOMPLETE, and
        its retries were not made". Returns the last attempt's code: a retry that is not made (``attempt``) leaves
        the code before it, and a first attempt that is not made gives 0 (the overnight pull then finds no evening
        sample: MISSED-NIGHT). Every attempt carries the pass's last overnight pull for the token warning."""
        retries = sorted(dt.datetime.combine(session, t, NY) for t in retry_ts)
        for _ in wait_until([dt.datetime.combine(session, ev_t, NY)], now_et, time.sleep, log_line):
            pass
        rc = self.attempt(session, notify_incomplete=not retries, warn_until=last_pull)
        if rc is None:
            return 0
        loud = not retries                                # an attempt made could notify an INCOMPLETE itself
        if rc in (1, 4):
            for due in wait_due(retries, now_et, time.sleep, log_line):
                log_line(f"evening {session}: retry at {due[-1]:%H:%M} after {'FAILED' if rc == 1 else 'INCOMPLETE'}")
                last = due[-1] == retries[-1]
                retry = self.attempt(session, retry=True, notify_incomplete=last, warn_until=last_pull)
                if retry is None:                         # not made: the code before it stands
                    break
                rc, loud = retry, loud or last
                if rc not in (1, 4):
                    break
        if rc == 4 and not loud:
            _say(self.notify, f"evening {session}: INCOMPLETE, and its retries were not made")
        return rc

    def attempt(self, session: dt.date, *, retry: bool = False, **kw) -> Optional[int]:
        """One evening attempt for this pass's ``session``, made only while it is still the last completed session:
        after a long sleep a pass never samples a later session's evening (that session's own pass does). A retry is
        not made either once the evening window has passed (evening_timing TOO_LATE: 04:00 the next calendar day),
        so a SKIPPED status never replaces the INCOMPLETE or FAILED code before it. None when the attempt is not
        made."""
        now = now_et()
        last = last_completed_session(now)
        if last != session:
            log_line(f"evening {session}: no attempt at {now:%a %m-%d %H:%M}: {last} has completed since")
            return None
        if retry and evening_timing(now, session)[0] == "TOO_LATE":
            log_line(f"evening {session}: no retry at {now:%a %m-%d %H:%M}: its evening window has passed")
            return None
        return self.evening(session, **kw)


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Phase 2 flip measurement: provisional and final bar samples",
                                 epilog="See the module docstring for files, classes and states.")
    ap.add_argument("mode", choices=("plan", "evening", "final", "night"))
    ap.add_argument("--root", default=str(OUT))
    ap.add_argument("--at", help="evening: HH:MM today; final: HH:MM[,HH:MM...] (times before 16:00 = next day)")
    ap.add_argument("--session", help="final: the session date (default: the last completed session); only a "
                                      "carried-calendar session after 2026-10-30, not later than the last completed one")
    ap.add_argument("--full", action="store_true", help="final: re-pull every symbol, not only unfinished ones")
    ap.add_argument("--no-minute", action="store_true", help="final and night: skip the 1-minute bars")
    ap.add_argument("--evening-at", default=PARAMS.evening_scan_et,
                    help="night: the evening sample time (retried at params.evening_retry_et)")
    ap.add_argument("--final-at", default=FINAL_AT_DEFAULT, help="night: the overnight pull times")
    ap.add_argument("--full-at", default=FULL_AT_DEFAULT,
                    help="night: overnight pulls that re-pull every symbol (added to --final-at; '' for none)")
    ap.add_argument("--now", help="plan: key this ISO time instead of now")
    return ap


def main(argv: Optional[list[str]] = None, *, market_data: Optional[Callable[[], MarketData]] = None,
         token_hours: Optional[Callable[[], tuple]] = None, notify: Optional[Callable[[str, str], None]] = None,
         awake: Optional[Callable[[bool], None]] = None) -> int:
    """The command line. loops/phase2_sample.py supplies four callables; this package builds no client and reads
    neither the token nor the settings (spec 2, review D7, safety S5):
      market_data()           -> the read-only MarketData wrapper; called once per pull, after that pull's token
                                 check (anything that is not a MarketData is refused)
      token_hours()           -> (hours of token life left or None, expiry ISO or None); None or an error means
                                 the token is unreadable: FAILED, fail closed
      notify(title, message)  -> one notification (or None for none)
      awake(on)               -> holds (True) or releases (False) the idle-sleep assertion (or None)
    ``plan`` needs none of them. A network mode started without market_data or token_hours is FAILED at once
    (status, log, notification), before any wait. Each network mode runs under a last-resort handler: an unexpected
    error is logged and notified ("<mode> crashed: <type>") and returns 1, and so does a calendar that does not
    cover the run ("the sampler's calendar ends ...: extend it before sampling")."""
    a = _parser().parse_args(argv)
    root = Path(a.root)
    if a.mode == "plan":                                   # no network, no token
        return _plan(a)
    try:
        session = None
        if a.mode == "final" and a.session:                # refused before anything is written (safety S9)
            session, why = _session_arg(a.session)
            if session is None:
                log_line(f"final: --session {a.session} refused: {why}; nothing written")
                return 2
        if market_data is None or token_hours is None:     # fail at once, before any wait: never a silent lost night
            missing = " or ".join(name for name, f in (("market-data wrapper", market_data),
                                                       ("token reader", token_hours)) if f is None)
            keyed = session if a.mode == "final" else night_session(now_et()) if a.mode == "night" else None
            return _failed(root, a.mode, notify, keyed,
                           f"no {missing} was supplied: this package builds no Schwab client and reads no token "
                           f"(spec 2, review D7); run the network modes through loops/phase2_sample.py")
        job = _Job(a, root, market_data, token_hours, notify, awake)
        if a.mode == "evening":
            return job.evening_mode()
        if a.mode == "final":
            return job.final_mode(session or last_completed_session(now_et()))
        return job.night()
    except CalendarError as e:
        log_line(f"{a.mode}: FAILED: {e}")
        _say(notify, f"{a.mode} FAILED: the sampler's calendar ends {CALENDAR_LAST}: extend it before sampling")
        return 1
    except Exception as e:                                 # noqa: BLE001  the last-resort handler
        log_line(f"{a.mode}: crashed: {type(e).__name__}: {e}")
        _say(notify, f"{a.mode} crashed: {type(e).__name__}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
