"""Tests for the Phase 2 flip-measurement tools: loops/phase2/sample_bars.py, loops/phase2/compare_bars.py and the
runner outside the package, loops/phase2_sample.py.

No network and no real bars. The sampler runs against a scripted market-data stand-in; every sample folder is
synthetic and built in a temporary directory. Synthetic sessions are post-go-live (2026-11-30 on), pre-go-live
after the sealed window (2026-11-18, 2026-11-20) or in-sample (2024); the fill model is only ever called with
sessions outside the sealed window 2025-01-02..2026-10-30, and the tests check that the comparison never
evaluates that window (spec 3.7).

compare_bars records go-live in its reviewed constant GO_LIVE_ACTUAL, unset until go-live (review D2), and the
owner's ruling of 2026-11-12 (spec 3.7: sealed bars may be read as look-back for any session after 2026-10-30)
in PRE_GO_LIVE_LOOKBACK_RULED, True. The synthetic nights here mostly stand for post-go-live nights, so this
module records go-live at the target date, 2026-11-23, for its tests (setUpModule), as the go-live edit will;
GoLiveFailsClosed tests the unset default, and the tests that show go-live deciding alone set the ruling False.

Run:  python -m unittest tests.test_phase2_flips
"""

from __future__ import annotations

import ast
import contextlib
import dataclasses
import datetime as dt
import errno
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "loops"))

import technicals  # noqa: E402
from phase2 import compare_bars as CB  # noqa: E402
from phase2 import fills as F  # noqa: E402
from phase2 import sample_bars as SB  # noqa: E402
from phase2.params import PARAMS  # noqa: E402
import phase2_sample as PR  # noqa: E402  (the runner outside the package)

try:
    from . import phase2_flip_helpers as H  # noqa: E402  (the spec-text oracles)
except ImportError:                          # run as a script from tests/
    import phase2_flip_helpers as H  # noqa: E402

NY, CH = SB.NY, SB.CH
D = dt.date
GO_LIVE_FOR_TESTS = D(2026, 11, 23)          # params.go_live_target; recorded here only, never in the source
_GO_LIVE = mock.patch.object(CB, "GO_LIVE_ACTUAL", GO_LIVE_FOR_TESTS)


def setUpModule():
    _GO_LIVE.start()


def tearDownModule():
    _GO_LIVE.stop()


# =========================================================================================================
# Synthetic candles, histories and night folders
# =========================================================================================================

def ms(d: dt.date, kind: str) -> int:
    return int(dt.datetime.combine(d, dt.time(0), CH if kind == "final" else NY).timestamp() * 1000)


def cdl(d: dt.date, kind: str, o, h, l, c, v) -> dict:
    return dict(d=d.isoformat(), kind=kind, ms=ms(d, kind), o=o, h=h, l=l, c=c, v=v)


def raw(d: dt.date, kind: str, o, h, l, c, v) -> dict:
    return dict(datetime=ms(d, kind), open=o, high=h, low=l, close=c, volume=v)


def at(y, mo, d, h, mi, s=0) -> dt.datetime:
    return dt.datetime(y, mo, d, h, mi, s, tzinfo=NY)


def sessions_before(t: dt.date, n: int) -> list[dt.date]:
    """n trading days before t, oldest first (the carried calendar inside its range, weekdays outside it)."""
    out, d = [], t
    while len(out) < n:
        d -= dt.timedelta(days=1)
        if d.weekday() >= 5:
            continue
        if SB.CALENDAR_FIRST <= d <= SB.CALENDAR_LAST and not SB.is_session(d):
            continue
        out.append(d)
    return out[::-1]


def flat_hist(t: dt.date, n: int = 130, c: float = 20.0, rng: float = 0.5, v: int = 1_000_000) -> list[dict]:
    """Close c, high c + rng, low c - rng every day: ATR(t-1) = 2 x rng, the 50-session average = c."""
    return [cdl(d, "final", c, c + rng, c - rng, c, v) for d in sessions_before(t, n)]


def shelf_hist(t: dt.date, n: int = 130) -> list[dict]:
    """A high of 30.6 inside the last 40 sessions, a decline, and a tested shelf at 20.00 15 and 20 sessions back.
    With day t's low at 20.15 it is an M1 signal (anchor 20.00, ATR(t) 0.8036, rr 10.09); at 20.30 the touch fails."""
    out = []
    for i, d in enumerate(sessions_before(t, n)):
        j = i - n
        if j <= -36:
            c, h, l = 30.0, 30.6, 29.4
        elif j <= -21:
            c = round(29.0 - (j + 35) * (8.0 / 14.0), 4)
            h, l = c + 0.5, c - 0.5
        elif j in (-20, -15):
            c, h, l = 20.6, 21.0, 20.0
        else:
            c, h, l = 21.0, 21.4, 20.6
        out.append(cdl(d, "final", c, h, l, c, 1_000_000))
    return out


class Night:
    """Writes one synthetic session folder in the sampler's layout."""

    def __init__(self, root: Path, session: dt.date, universe: list[str], reference=("SPY",)):
        self.root, self.session = Path(root), session
        self.day = self.root / session.isoformat()
        self.day.mkdir(parents=True, exist_ok=True)
        self.universe, self.reference = universe, list(reference)
        with open(self.day / "candidates.json", "w") as fh:
            json.dump(dict(session=session.isoformat(), symbols=universe, reference=self.reference), fh)

    def _append(self, name: str, row: dict) -> None:
        with open(self.day / name, "a") as fh:
            fh.write(json.dumps(row) + "\n")

    def quote(self, sym, close, pulled, **kw):
        self._append(f"quotes_{SB.stamp(pulled)}.jsonl", dict(symbol=sym, pulled=SB.iso(pulled), regular_last=close, **kw))

    def evening(self, sym, candles, pulled, file_stamp=None):
        self._append(f"evening_{file_stamp or SB.stamp(pulled)}.jsonl", dict(symbol=sym, pulled=SB.iso(pulled), candles=candles))

    def final(self, sym, candles, pulled, file_name=None, **extra):
        row = dict(symbol=sym, pulled=SB.iso(pulled), **extra)
        if candles is not None:
            row["candles"] = candles
        self._append(file_name or f"final_{SB.stamp(pulled)}.jsonl", row)


def bar(o, h, l, c, v) -> dict:
    return dict(o=o, h=h, l=l, c=c, v=v)


NIGHT_A = D(2026, 11, 30)          # Monday, post-go-live
EVENING_A = at(2026, 11, 30, 17, 35)
FINAL_A = at(2026, 12, 1, 1, 30)

# name: (history kind, evening provisional bar (close = the candle's own), quote close, final bar)
CASES_A = {
    "M2FLIP": ("flat", bar(21.10, 21.80, 20.90, 21.55, 5_000_000), 21.60, bar(20.95, 21.80, 20.90, 21.60, 5_000_000)),
    "M2BOTH": ("flat", bar(21.20, 21.90, 21.00, 21.70, 5_000_000), 21.70, bar(21.20, 21.90, 21.00, 21.70, 5_100_000)),
    "TRIG":   ("flat", bar(20.10, 20.60, 19.90, 20.40, 1_000_000), 20.40, bar(20.10, 20.64, 19.90, 20.40, 1_000_500)),
    "SUBC":   ("flat", bar(20.10, 20.511, 19.90, 20.30, 1_000_000), 20.30, bar(20.10, 20.514, 19.90, 20.30, 1_000_000)),
    "VOLX":   ("flat", bar(20.30, 20.80, 20.10, 20.60, 3_050_000), 20.60, bar(20.30, 20.80, 20.10, 20.60, 2_950_000)),
    "SMAX":   ("flat", bar(20.00, 20.30, 19.80, 20.05, 1_000_000), 20.05, bar(20.00, 20.30, 19.80, 19.95, 1_000_000)),
    "OPENX":  ("flat", bar(20.40, 20.90, 19.95, 20.50, 1_000_000), 20.50, bar(20.10, 20.90, 19.95, 20.50, 1_000_000)),
    "M1SIG":  ("shelf", bar(20.50, 20.80, 20.15, 20.70, 1_000_000), 20.70, bar(20.50, 20.80, 20.15, 20.70, 1_000_000)),
    "M1FLIP": ("shelf", bar(20.50, 20.80, 20.30, 20.70, 1_000_000), 20.70, bar(20.50, 20.80, 20.15, 20.70, 1_000_000)),
    "FLAT1":  ("flat", bar(19.00, 19.40, 18.90, 19.00, 1_000_000), 19.00, bar(19.00, 19.40, 18.90, 19.00, 1_000_000)),
    "FLAT2":  ("flat", bar(19.00, 19.40, 18.90, 19.00, 1_000_000), 19.00, bar(19.00, 19.40, 18.90, 19.00, 1_000_100)),
    "RETRY":  ("flat", bar(19.00, 19.40, 18.90, 19.00, 1_000_000), 19.00, bar(19.00, 19.40, 18.90, 19.00, 1_000_000)),
    "ERRL":   ("flat", bar(19.00, 19.40, 18.90, 19.00, 1_000_000), 19.00, bar(19.00, 19.40, 18.90, 19.00, 1_000_000)),
    "NOQ":    ("flat", bar(19.00, 19.40, 18.90, 19.00, 1_000_000), None, bar(19.00, 19.40, 18.90, 19.00, 1_000_000)),
    "TRUNC":  ("flat", bar(19.00, 19.40, 18.90, 19.00, 1_000_000), 19.00, None),
    "NOTFIN": ("flat", bar(19.00, 19.40, 18.90, 19.00, 1_000_000), 19.00, None),
}
SPY_PC = 600.0


def hist_for(kind: str, t: dt.date) -> list[dict]:
    return shelf_hist(t) if kind == "shelf" else flat_hist(t)


def build_night_a(root: Path) -> Night:
    n = Night(root, NIGHT_A, list(CASES_A))
    spy_h = flat_hist(NIGHT_A, c=SPY_PC, rng=3.0, v=50_000_000)
    n.quote("SPY", 607.0, EVENING_A, open=SPY_PC * 1.0105)
    n.evening("SPY", spy_h[-4:] + [cdl(NIGHT_A, "provisional", SPY_PC * 1.0105, 610.0, 604.0, 607.0, 40_000_000)], EVENING_A)
    n.final("SPY", spy_h + [cdl(NIGHT_A, "final", SPY_PC * 1.0095, 610.0, 604.0, 607.0, 41_000_000)], FINAL_A)
    for i, (sym, (kind, ev, qclose, fin)) in enumerate(CASES_A.items()):
        h = hist_for(kind, NIGHT_A)
        pulled = EVENING_A + dt.timedelta(seconds=i)
        n.quote(sym, qclose, pulled, open=ev["o"])
        n.evening(sym, h[-4:] + [cdl(NIGHT_A, "provisional", **ev)], pulled)
        fp = FINAL_A + dt.timedelta(seconds=i)
        main_file = f"final_{SB.stamp(FINAL_A)}.jsonl"
        if sym == "TRUNC":               # one provisional candle and no history: the 01:50 block
            n.final(sym, [cdl(NIGHT_A, "provisional", **ev)], at(2026, 12, 1, 1, 49, 51), file_name=main_file)
        elif sym == "NOTFIN":            # complete history, but the session's candle is still provisional
            n.final(sym, h + [cdl(NIGHT_A, "provisional", **ev)], fp)
        elif sym == "RETRY":             # truncated first, final on the retry two minutes later
            n.final(sym, [cdl(NIGHT_A, "provisional", **ev)], at(2026, 12, 1, 1, 49, 52), file_name=main_file, attempt=1)
            n.final(sym, h + [cdl(NIGHT_A, "final", **fin), cdl(NIGHT_A, "provisional", **ev)],
                    at(2026, 12, 1, 1, 51, 52), file_name=main_file, attempt=2)
        else:
            n.final(sym, h + [cdl(NIGHT_A, "final", **fin), cdl(NIGHT_A, "provisional", **ev)], fp)
        if sym == "ERRL":                # a later pull errors: it must not erase the good 01:30 record
            n.final(sym, None, at(2026, 12, 1, 6, 30), error="ReadTimeout: The read operation timed out")
    return n


def simple_night(root: Path, session: dt.date, evening_at: dt.datetime, final_at: dt.datetime,
                 names=("FLAT1", "FLAT2", "FLAT3"), already_final=(), open_moves=()) -> Night:
    """Quiet names (only the volume revises) plus SPY; optional evening candles already final or moved opens."""
    n = Night(root, session, list(names))
    spy_h = flat_hist(session, c=SPY_PC, rng=3.0, v=50_000_000)
    n.quote("SPY", 601.0, evening_at, open=600.5)
    n.evening("SPY", spy_h[-4:] + [cdl(session, "provisional", 600.5, 603.0, 598.0, 601.0, 40_000_000)], evening_at)
    n.final("SPY", spy_h + [cdl(session, "final", 600.5, 603.0, 598.0, 601.0, 41_000_000)], final_at)
    for i, sym in enumerate(names):
        h = flat_hist(session)
        o = 20.3 if sym in open_moves else 20.0
        kind = "final" if sym in already_final else "provisional"
        pulled = evening_at + dt.timedelta(seconds=i)
        n.quote(sym, 20.0, pulled, open=o)
        n.evening(sym, h[-4:] + [cdl(session, kind, o, 20.5, 19.6, 20.0, 1_000_000)], pulled)
        n.final(sym, h + [cdl(session, "final", 20.0, 20.5, 19.6, 20.0, 1_002_000)], final_at + dt.timedelta(seconds=i))
    return n


def load_json(path):
    with open(path) as fh:
        return json.load(fh)


def seed_evening(root: Path, s: dt.date, when: dt.datetime) -> None:
    """What a real evening run leaves for the night job: candidates.json and a usable evening row (SPY's provisional
    candle after a final one), so the session has an evening sample by run_final's own rule (has_evening_sample)."""
    day = Path(root) / s.isoformat()
    day.mkdir(parents=True, exist_ok=True)
    if not (day / "candidates.json").exists():
        with open(day / "candidates.json", "w") as fh:
            json.dump(dict(session=s.isoformat(), symbols=[], reference=["SPY"]), fh)
    prior = sessions_before(s, 1)[0]
    row = dict(symbol="SPY", pulled=SB.iso(when), candles=[cdl(prior, "final", 600.0, 603.0, 598.0, 601.0, 40_000_000),
                                                           cdl(s, "provisional", 600.0, 603.0, 598.0, 601.0, 40_000_000)])
    with open(day / f"evening_{SB.stamp(when)}.jsonl", "a") as fh:
        fh.write(json.dumps(row) + "\n")


class TempRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


# =========================================================================================================
# 1. The NYSE calendar and session keying
# =========================================================================================================

class Calendar(unittest.TestCase):
    def test_holidays_and_half_days(self):
        for d in (D(2026, 11, 26), D(2026, 12, 25), D(2027, 1, 1), D(2027, 1, 18), D(2027, 2, 15), D(2027, 3, 26)):
            self.assertFalse(SB.is_session(d), d)
        for d in (D(2026, 11, 27), D(2026, 12, 24)):
            self.assertTrue(SB.is_session(d))
            self.assertEqual(SB.session_close(d), dt.time(13, 0))
        self.assertEqual(SB.session_close(D(2026, 12, 31)), dt.time(16, 0))
        self.assertFalse(SB.is_session(D(2026, 11, 28)))                     # a Saturday

    def test_last_completed_session(self):
        cases = [
            (at(2026, 11, 11, 17, 35), D(2026, 11, 11)),     # the evening of the session
            (at(2026, 11, 11, 16, 0), D(2026, 11, 11)),      # the close itself completes it
            (at(2026, 11, 11, 15, 59), D(2026, 11, 10)),     # before the close
            (at(2026, 11, 19, 0, 40), D(2026, 11, 18)),      # a wake after midnight is filed under the prior session
            (at(2026, 11, 26, 17, 35), D(2026, 11, 25)),     # Thanksgiving: closed
            (at(2026, 11, 27, 12, 30), D(2026, 11, 25)),     # half day, before its 13:00 close
            (at(2026, 11, 27, 13, 5), D(2026, 11, 27)),      # half day, after the close
            (at(2026, 11, 28, 1, 30), D(2026, 11, 27)),      # the Saturday pull for the half day
            (at(2026, 12, 24, 13, 0), D(2026, 12, 24)),
            (at(2026, 12, 25, 17, 30), D(2026, 12, 24)),
            (at(2027, 1, 1, 1, 30), D(2026, 12, 31)),        # New Year's Day early morning
            (at(2027, 1, 18, 17, 35), D(2027, 1, 15)),       # MLK Day
            (at(2027, 2, 15, 17, 35), D(2027, 2, 12)),       # Washington's Birthday
            (at(2027, 3, 26, 17, 35), D(2027, 3, 25)),       # Good Friday
            (at(2027, 3, 29, 1, 30), D(2027, 3, 25)),        # Monday 01:30 after Good Friday
        ]
        for now, want in cases:
            self.assertEqual(SB.last_completed_session(now), want, now)
        # a UTC timestamp is converted, never read as local time
        self.assertEqual(SB.last_completed_session(dt.datetime(2026, 11, 12, 3, 0, tzinfo=dt.timezone.utc)), D(2026, 11, 11))

    def test_outside_the_calendar_is_refused(self):
        with self.assertRaises(SB.CalendarError):
            SB.last_completed_session(at(2027, 4, 5, 17, 0))
        with self.assertRaises(SB.CalendarError):
            SB.last_completed_session(at(2026, 11, 2, 10, 0))      # needs 2026-10-30
        with self.assertRaises(ValueError):
            SB.last_completed_session(dt.datetime(2026, 11, 11, 17, 0))   # naive

    def test_session_tags_mark_special_sessions(self):
        self.assertIn("monthly expiration", SB.session_tags(D(2026, 11, 20)))
        self.assertIn("half day 13:00", SB.session_tags(D(2026, 11, 27)))
        self.assertIn("after Thanksgiving Day", SB.session_tags(D(2026, 11, 27)))
        self.assertIn("before Thanksgiving Day", SB.session_tags(D(2026, 11, 25)))
        self.assertIn("quarterly expiration", SB.session_tags(D(2026, 12, 18)))
        self.assertEqual(SB.session_tags(D(2026, 11, 13))[0], "Fri")
        self.assertIn("outside calendar", SB.session_tags(D(2026, 10, 29)))

    def test_evening_timing(self):
        """The LATE cutoff is params.watchdog_evening_et (19:30, the scan's missed-window time; review SVC-07)."""
        s = D(2026, 11, 30)
        self.assertEqual(SB.LATE_AFTER, dt.time.fromisoformat(PARAMS.watchdog_evening_et))
        self.assertEqual(SB.LATE_AFTER, dt.time(19, 30))
        self.assertEqual(SB.evening_timing(at(2026, 11, 30, 17, 35), s)[0], "ON_TIME")
        self.assertEqual(SB.evening_timing(at(2026, 11, 30, 19, 29), s)[0], "ON_TIME")
        self.assertEqual(SB.evening_timing(at(2026, 11, 30, 19, 30), s)[0], "ON_TIME")
        timing, why = SB.evening_timing(at(2026, 11, 30, 19, 31), s)
        self.assertEqual((timing, why), ("LATE", ["started 19:31 ET, after the 19:30 cutoff"]))
        self.assertEqual(SB.evening_timing(at(2026, 11, 30, 21, 0), s)[0], "LATE")
        self.assertEqual(SB.evening_timing(at(2026, 12, 1, 0, 40), s)[0], "LATE")
        self.assertEqual(SB.evening_timing(at(2026, 12, 1, 4, 0), s)[0], "TOO_LATE")
        self.assertEqual(SB.evening_timing(at(2026, 11, 26, 17, 35), D(2026, 11, 25))[0], "TOO_LATE")

    def test_final_targets_fall_on_the_right_day(self):
        got = SB.final_targets(D(2026, 11, 27), SB.parse_times("01:30,22:00,04:30"))
        self.assertEqual(got, [at(2026, 11, 27, 22, 0), at(2026, 11, 28, 1, 30), at(2026, 11, 28, 4, 30)])
        self.assertEqual(SB.final_targets(D(2026, 11, 27), SB.parse_times("06:30,01:30,06:30")),
                         [at(2026, 11, 28, 1, 30), at(2026, 11, 28, 6, 30)])              # a time given twice: one target
        self.assertEqual(SB.parse_times(""), [])                                           # --full-at '': no full pull

    def test_plan_command_keys_without_network(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = SB.main(["plan", "--now", "2026-11-26T17:35:00-05:00"])
        self.assertEqual(rc, 0)
        self.assertIn("last completed session 2026-11-25", buf.getvalue())
        self.assertIn("TOO_LATE", buf.getvalue())

    def test_plan_prints_the_nights_schedule_with_the_full_pull_marked(self):
        """Review SVC-04: the evening at params.evening_scan_et with its retries, and pulls at and before the
        ruled 01:00 recheck start, the 06:30 one a full re-pull."""
        self.assertEqual((SB.FINAL_AT_DEFAULT, SB.FULL_AT_DEFAULT), ("00:30,01:00,01:30,04:30,06:30,07:30", "06:30"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = SB.main(["plan", "--now", "2026-11-30T10:00:00-05:00"])
        text = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("a night job started now samples session 2026-11-30", text)
        self.assertIn(f"evening sample Mon 11-30 {PARAMS.evening_scan_et}, retried at 18:15, 19:00", text)
        self.assertIn("idle-sleep assertion from Mon 11-30 17:20", text)
        self.assertIn("LATE after 19:30", text)
        self.assertIn("overnight pulls: Tue 12-01 00:30, Tue 12-01 01:00, Tue 12-01 01:30, Tue 12-01 04:30, "
                      "Tue 12-01 06:30 (full), Tue 12-01 07:30", text)
        self.assertIn("rolls over into 2026-12-01's night", text)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):                                  # a --full-at time not in --final-at is added
            SB.main(["plan", "--now", "2026-11-30T10:00:00-05:00", "--final-at", "01:30", "--full-at", "05:00"])
        self.assertIn("overnight pulls: Tue 12-01 01:30, Tue 12-01 05:00 (full)", buf.getvalue())


# =========================================================================================================
# 2. Candle stamps and response classes
# =========================================================================================================

class Responses(unittest.TestCase):
    def test_stamps(self):
        self.assertEqual(SB.stamp_kind(ms(D(2026, 11, 11), "final")), "final")
        self.assertEqual(SB.stamp_kind(ms(D(2026, 11, 11), "provisional")), "provisional")
        self.assertEqual(SB.stamp_kind(ms(D(2026, 7, 15), "final")), "final")          # summer time too
        self.assertTrue(SB.stamp_kind(ms(D(2026, 11, 11), "final") + 3_600_000).startswith("other:"))
        c = SB.candle_from_raw(raw(D(2026, 11, 11), "final", 1, 2, 0.5, 1.5, 10))
        self.assertEqual((c["d"], c["kind"]), ("2026-11-11", "final"))

    def test_classes(self):
        t = D(2026, 11, 30)
        h = flat_hist(t, n=3)
        prov, fin = cdl(t, "provisional", 20, 20.5, 19.5, 20, 1), cdl(t, "final", 20, 20.5, 19.5, 20, 1)
        s = t.isoformat()
        self.assertEqual(SB.response_class(None, s, "final"), SB.ERROR)
        self.assertEqual(SB.response_class([], s, "final"), SB.EMPTY)
        self.assertEqual(SB.response_class([prov], s, "final"), SB.TRUNCATED)
        self.assertEqual(SB.response_class([prov, fin], s, "final"), SB.TRUNCATED)       # no history at all
        self.assertEqual(SB.response_class(h, s, "final"), SB.NO_BAR)
        self.assertEqual(SB.response_class(h + [prov], s, "final"), SB.NOT_FINAL)
        self.assertEqual(SB.response_class(h + [fin, prov], s, "final"), SB.FINAL)       # both kinds: final wins
        self.assertEqual(SB.response_class(h + [prov], s, "evening"), SB.PROVISIONAL)
        self.assertEqual(SB.response_class(h + [fin], s, "evening"), SB.ALREADY_FINAL)
        self.assertEqual(SB.RETRY_CLASSES, {SB.TRUNCATED, SB.EMPTY, SB.NO_BAR, SB.ERROR})


# =========================================================================================================
# 3. The universe stand-in (spec 3.1)
# =========================================================================================================

NASDAQ_TXT = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAA|Alpha Corp - Common Stock|Q|N|N|100|N|N
JD|JD.com, Inc. - American Depositary Shares|Q|N|N|100|N|N
ARCC|Ares Capital Corporation - Closed End Fund|Q|N|N|100|N|N
CCD|Calamos Dynamic Convertible & Income Fund - Closed End Fund|Q|N|N|100|N|N
BHF|Brighthouse Financial, Inc. - Common Stock|Q|N|N|100|N|N
NTRS|Northern Trust Corporation - Common Stock|Q|N|N|100|N|N
AACIW|Armada Acquisition Corp. III - Warrant|Q|N|N|100|N|N
AACI|Armada Acquisition Corp. III - Class A Ordinary Share|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust, Series 1|G|N|N|100|Y|N
ZXZZT|NASDAQ TEST STOCK|Q|Y|N|100|N|N
TRN|Truncation Test Inc. - Common Stock|Q|N|N|100|N|N
TRX|Always Truncated Inc. - Common Stock|Q|N|N|100|N|N
PFBC|Preferred Bank - Common Stock|Q|N|N|100|N|N
OBAI|Our Bond, Inc. - Common Stock|Q|N|N|100|N|N
File Creation Time: 1130202617:01|||||||
"""
OTHER_TXT = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
BF.B|Brown Forman Inc Class B Common Stock|N|BF.B|N|100|N|BF.B
EPD|Enterprise Products Partners L.P. Common Stock|N|EPD|N|100|N|EPD
ET|Energy Transfer LP Common Units|N|ET|N|100|N|ET
PBT|Permian Basin Royalty Trust Common Stock|N|PBT|N|100|N|PBT
ABR$D|Arbor Realty Trust 6.375% Series D Cumulative Redeemable Preferred Stock|N|ABRpD|N|100|N|ABR-D
AAC.U|Ares Acquisition Corporation III Units, each consisting of one Class A ordinary share|N|AAC.U|N|100|N|AAC=
CW|Curtiss-Wright Corporation Common Stock|N|CW|N|100|N|CW
SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY
RLX|RLX Technology Inc. American Depositary Shares, each representing the right to receive one (1) Class A ordinary share|N|RLX|N|100|N|RLX
USB$H|U.S. Bancorp Depositary Shares repstg 1/1000th Pfd Ser B|N|USBpH|N|100|N|USB-H
STTX|State Street Depositary shares, each representing a 1/4,000th ownership interest in a share|N|STTX|N|100|N|STTX
BBN|BlackRock Taxable Municipal Bond Trust Common Shares of Beneficial Interest|N|BBN|N|100|N|BBN
DDT|Dillard's Capital Trust I|N|DDT|N|100|N|DDT
CHEAP|Cheap Co Common Stock|N|CHEAP|N|100|N|CHEAP
THIN|Thin Co Common Stock|N|THIN|N|100|N|THIN
CEFX|Some Closed End Holdings Common Stock|N|CEFX|N|100|N|CEFX
File Creation Time: 1130202617:01||||||
"""
EXPECTED_DIRECTORY = {   # symbol -> None (kept) or the expected reason prefix
    "AAA": None, "JD": None, "ARCC": None, "BHF": None, "NTRS": None, "TRN": None, "TRX": None, "PFBC": None,
    "OBAI": None, "BF.B": None, "CW": None, "RLX": None, "CHEAP": None, "THIN": None, "CEFX": None,
    "CCD": "closed-end fund", "AACIW": "SPAC", "AACI": "SPAC", "QQQ": "ETF flag", "ZXZZT": "test issue",
    "EPD": "MLP", "ET": "MLP", "PBT": "royalty trust", "ABR$D": "symbol suffix '$'", "AAC.U": "symbol suffix '='",
    "SPY": "ETF flag", "USB$H": "symbol suffix '$'", "STTX": "fractional interest",
    "BBN": "closed-end fund (sponsor and Trust)", "DDT": "structured product",
}


def directory_rows() -> list[dict]:
    return SB.parse_directory(NASDAQ_TXT, "nasdaqlisted.txt") + SB.parse_directory(OTHER_TXT, "otherlisted.txt")


class Universe(unittest.TestCase):
    def test_every_row_is_kept_or_excluded_with_its_reason(self):
        kept, excluded = SB.universe_stand_in(directory_rows())
        got = {r["symbol"]: None for r in kept}
        got.update({e["symbol"]: e["reason"] for e in excluded})
        self.assertEqual(set(got), set(EXPECTED_DIRECTORY))
        for sym, want in EXPECTED_DIRECTORY.items():
            if want is None:
                self.assertIsNone(got[sym], sym)
            else:
                self.assertTrue(got[sym] and got[sym].startswith(want), (sym, got[sym]))
        self.assertTrue(all(e["reason"] for e in excluded))
        self.assertEqual(len(kept) + len(excluded), len(directory_rows()))

    def test_review_examples(self):
        kept, _ = SB.universe_stand_in(directory_rows())
        by = {r["symbol"]: r for r in kept}
        self.assertEqual(by["BF.B"]["forms"], ["BF/B", "BF.B"])               # mapped to Schwab's form, dot kept as fallback
        self.assertIn("ADR", by["JD"]["note"])                                 # depositary shares kept
        self.assertIn("BDC", by["ARCC"]["note"])                               # BDCs are in (the owner's ruling, 2026-11-12)
        self.assertIn("not a royalty or statutory trust", by["NTRS"]["note"])
        for sym in ("BHF", "CW", "RLX", "PFBC", "OBAI"):                       # word boundaries: Bright-, -Wright, "right to receive"
            self.assertIn(sym, by)

    def test_quote_stage(self):
        ok = dict(sub="COE", regular_last=20.0, avg10=400_000, avg1y=100_000)
        self.assertEqual(SB.quote_decision(ok), (True, ""))
        self.assertTrue(SB.quote_decision(dict(ok, avg10=100_000, avg1y=350_000))[0])     # either average will do
        self.assertFalse(SB.quote_decision(dict(ok, avg10=100_000))[0])
        self.assertTrue(SB.quote_decision(dict(ok, sub=None))[0])                         # empty subtype is not a drop
        for sub in ("ETF", "ETN", "CEF", "PRF", "WAR", "RGT", "UIT"):
            self.assertEqual(SB.quote_decision(dict(ok, sub=sub)), (False, f"assetSubType {sub}"))
        self.assertFalse(SB.quote_decision(dict(ok, regular_last=3.5))[0])
        self.assertFalse(SB.quote_decision(dict(ok, regular_last=None, last=None))[0])

    def test_m2_like_quote_proxy(self):
        self.assertTrue(SB.m2_like_quote(dict(open=10.3, prev_close=10.0, total_volume=2_000_000, avg10=1_000_000)))
        self.assertFalse(SB.m2_like_quote(dict(open=10.1, prev_close=10.0, total_volume=2_000_000, avg10=1_000_000)))
        self.assertFalse(SB.m2_like_quote(dict(open=10.3, prev_close=10.0, total_volume=1_900_000, avg10=1_000_000)))
        self.assertFalse(SB.m2_like_quote(None))

    @staticmethod
    def decide(symbol: str, name: str) -> tuple:
        return SB.directory_decision(dict(symbol=symbol, nasdaq_symbol=symbol, name=name, etf="N", test="N",
                                          source="otherlisted.txt", exchange="N", financial_status=""))

    def test_spacs_with_a_numeral_before_corp_or_co_are_excluded(self):
        # review D3: names as night 1's directory files print them (8 of the 21 the first rule missed)
        for sym, name in (("AESP", "Aeon Acquisition I Corp. - Class A Ordinary Shares"),
                          ("APAC", "StoneBridge Acquisition II Corporation - Class A Ordinary Shares"),
                          ("BIII", "Black Spade Acquisition III Co Class A Ordinary Shares"),
                          ("IRHO", "Iron Horse Acquisitions II Corp. - Common Stock"),
                          ("JONE", "Jones Ventures INTL Acquisition1 Corp - Class A Ordinary Shares"),
                          ("MBVI", "M3-Brigade Acquisition VI Corp. - Class A Ordinary Shares"),
                          ("MCAH", "Mountain Crest Acquisition 6 Corp. - Ordinary Shares"),
                          ("TVIV", "Texas Ventures Acquisition IV Corp - Class A Ordinary Shares")):
            self.assertEqual(self.decide(sym, name)[:2], (False, "SPAC"), name)
        for sym, name in (("AAQ", "Armada Acquisition Corp. III - Class A Ordinary Share"),     # the first rule's form
                          ("AQAN", "Acquisition Analytics Inc. - Common Stock")):                # not a SPAC name
            self.assertEqual(self.decide(sym, name)[0], sym == "AQAN", name)

    def test_spacs_with_a_bare_numeral_or_a_glued_name_are_excluded(self):
        # integration check, gap B: the three names night 1's directory files still kept (as they print them)
        for sym, name in (("FJDI", "ARC Group Securities Acquisition I - Class A Ordinary Shares"),
                          ("FTRA", "FutureCorp Space Acquisition 1 Class A Ordinary Shares"),
                          ("KRAQ", "KRAKacquisition Corp - Class A Ordinary Shares")):
            self.assertEqual(self.decide(sym, name)[:2], (False, "SPAC"), name)
        for sym, name in (("AQAN", "Acquisition Analytics Inc. - Common Stock"),                # controls: a word that
                          ("AQIV", "Acquisition Investors Inc. - Common Stock"),                # starts with i, v or x
                          ("AQVX", "Acquisition Vexillum Holdings Inc. - Common Stock")):       # is not a numeral
            self.assertTrue(self.decide(sym, name)[0], name)

    def test_a_fund_sponsors_realty_trust_is_kept_and_its_funds_are_not(self):
        # review D4: FBRT (Franklin BSP Realty Trust, a mortgage REIT) is common stock; the sponsor's CEF trusts stay out
        keep, note, _ = self.decide("FBRT", "Franklin BSP Realty Trust, Inc. Common Stock")
        self.assertTrue(keep)
        self.assertIn("not a royalty or statutory trust", note)
        for name in ("Franklin Limited Duration Income Trust Common Shares of Beneficial Interest",
                     "BlackRock Income Trust, Inc. (The)", "Nuveen Real Asset Income and Growth Trust"):
            self.assertEqual(self.decide("CEFT", name)[:2], (False, "closed-end fund (sponsor and Trust)"), name)

    def test_a_bdc_named_fund_stays_excluded_with_its_reason_logged(self):
        # review D4: MSIF (MSC Income Fund, a BDC) is left excluded by the fund rule; the record says why
        keep, why, hit = self.decide("MSIF", "MSC Income Fund, Inc. Common Stock")
        self.assertEqual((keep, hit), (False, "Fund"))
        self.assertEqual(why.split(" (")[0], "fund")                           # the counts key is unchanged
        self.assertIn("MSC Income Fund, Inc. is a BDC", why)
        self.assertIn("BDCs are in the universe by the owner's ruling of 2026-11-12", why)
        self.assertEqual(self.decide("ADX", "Adams Diversified Equity Fund, Inc. Common Stock")[:2], (False, "fund"))
        # the three fund-named BDCs added from general knowledge (to confirm against SEC 814- numbers at B3/B4)
        for sym, name, issuer in (
                ("MSIF", "MSC Income Fund, Inc. Common Stock", "MSC Income Fund, Inc."),
                ("BXSL", "Blackstone Secured Lending Fund Common Shares of Beneficial Interest",
                 "Blackstone Secured Lending Fund"),
                ("MSDL", "Morgan Stanley Direct Lending Fund Common Stock", "Morgan Stanley Direct Lending Fund"),
                ("FSSL", "FS Specialty Lending Fund Common Shares of Beneficial Interest", "FS Specialty Lending Fund")):
            keep, why, hit = self.decide(sym, name)
            self.assertEqual((keep, why, hit), (False, f"fund ({SB.FUND_NAMED_BDCS[sym]})", "Fund"), sym)
            self.assertTrue(why.startswith(f"fund ({issuer} is a BDC: excluded by the generic fund name rule"), why)
            self.assertIn("BDCs are in the universe by the owner's ruling of 2026-11-12 (spec 3.1), known by their SEC 814-", why)
        self.assertEqual(sorted(SB.FUND_NAMED_BDCS), ["BXSL", "FSSL", "MSDL", "MSIF"])


# =========================================================================================================
# 4. The sampler against a scripted market-data stand-in
# =========================================================================================================

class FakeClock:
    def __init__(self, start: dt.datetime):
        self.t, self.sleeps = start, []

    def __call__(self) -> dt.datetime:
        self.t += dt.timedelta(seconds=1)
        return self.t

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += dt.timedelta(seconds=s)


class FakeSchwab:
    """Scripted daily / minute / quote responses. ``truncate`` maps a symbol to how many truncated responses it
    gets before a normal one (-1: always). ``final_ready`` False keeps the session's candle provisional.
    ``revise`` maps a symbol to extra volume on its final candle (a later pull that sees a revised final bar)."""

    def __init__(self, session: dt.date, truncate=None, final_ready=True, evening_final=(), slash_only=("BF/B",),
                 revise=None):
        self.session, self.truncate, self.final_ready = session, dict(truncate or {}), final_ready
        self.evening_final, self.slash_only, self.revise = set(evening_final), set(slash_only), dict(revise or {})
        self.calls = {"daily": [], "minute": [], "quotes": []}
        self.md = SB.MarketData(self.daily, self.minute, self.quotes)

    def _bar(self, sym):
        if sym == "SPY":
            return (600.0, 603.0, 598.0, 601.0, 40_000_000)
        return (20.0, 20.5, 19.6, 20.0, 1_000_000)

    def daily(self, sym, start, end):
        self.calls["daily"].append((sym, start, end))
        o, h, l, c, v = self._bar(sym)
        prov = raw(self.session, "provisional", o, h, l, c, v)
        left = self.truncate.get(sym, 0)
        if left:
            self.truncate[sym] = left - 1 if left > 0 else left
            return [prov]
        n = 130 if (end - start).days > 100 else 6
        hist = [raw(d, "final", o, h, l, c, v) for d in sessions_before(self.session, n)]
        if (end - start).days <= 100:                    # the evening request (10 days); final asks 200
            return hist + [raw(self.session, "final", o, h, l, c, v) if sym in self.evening_final else prov]
        if not self.final_ready:
            return hist + [prov]
        fo = o + 0.3 if sym == "AAA" else o            # AAA's final open differs: it gets 1-minute bars
        return hist + [raw(self.session, "final", fo, h, l, c, v + 1500 + self.revise.get(sym, 0)), prov]

    def minute(self, sym, start, end):
        self.calls["minute"].append((sym, start, end))
        return [dict(datetime=int(start.timestamp() * 1000), open=20.0, high=20.1, low=19.9, close=20.05, volume=1000)]

    def quotes(self, symbols):
        self.calls["quotes"].append(list(symbols))
        out = {}
        for s in symbols:
            if s == "BF.B" or (s == "BF/B" and s not in self.slash_only):
                continue
            px = dict(CHEAP=2.0).get(s, 601.0 if s == "SPY" else 20.0)
            vol = dict(THIN=100_000).get(s, 2_000_000)
            sub = dict(CEFX="CEF", SPY="ETF").get(s, "COE")
            op = 20.5 if s == "JD" else px                  # JD: an M2-like quote (gap +2.5%, volume 2.5x)
            out[s] = dict(assetMainType="EQUITY", assetSubType=sub,
                          quote=dict(openPrice=op, highPrice=px + 0.5, lowPrice=px - 0.4, lastPrice=px, closePrice=px,
                                     totalVolume=(2.5 * vol if s == "JD" else vol)),
                          regular=dict(regularMarketLastPrice=px),
                          fundamental=dict(avg10DaysVolume=vol, avg1YearVolume=vol))
        return out


def fetch_directory(url: str) -> bytes:
    return (NASDAQ_TXT if url.endswith("nasdaqlisted.txt") else OTHER_TXT).encode()


QUIET = dict(log=lambda m: None)


class ManyNames:
    """A universe of n synthetic names already in candidates.json (as a re-run finds it), with SPY as reference.
    Each name in ``empty`` gets EMPTY daily responses; ``quotes_fail`` makes every quotes call fail."""

    def __init__(self, root: Path, session: dt.date, n: int = 1000, empty=(), write: bool = True,
                 quotes_fail: bool = False):
        self.session, self.empty, self.quotes_fail, self.asked = session, set(empty), quotes_fail, []
        self.names = [f"N{i:04d}" for i in range(n)]
        day = Path(root) / session.isoformat()
        day.mkdir(parents=True, exist_ok=True)
        if write:
            with open(day / "candidates.json", "w") as fh:
                json.dump(dict(session=session.isoformat(), symbols=self.names, reference=["SPY"], counts={}), fh)
        self.md = SB.MarketData(self.daily, lambda *a: [], self.quotes)

    def daily(self, sym, start, end):
        self.asked.append(sym)
        if sym in self.empty:
            return []
        return [raw(d, "final", 20.0, 20.5, 19.5, 20.0, 1_000_000) for d in sessions_before(self.session, 5)] + \
            [raw(self.session, "provisional", 20.0, 20.5, 19.5, 20.0, 1_000_000)]

    def quotes(self, symbols):
        if self.quotes_fail:
            raise RuntimeError("HTTP 502")
        return {s: dict(quote=dict(openPrice=20.0, closePrice=20.0), regular=dict(regularMarketLastPrice=20.0),
                        fundamental={}) for s in symbols}


def full_disk(allow_first_status: bool = True):
    """builtins.open that refuses every write with ENOSPC (lock files aside), after letting the first status file
    through: the critic's 'truly full disk' (review_final/critic/scripts/write_failure.py, case 2)."""
    real_open, let = open, [allow_first_status]

    def opener(file, mode="r", *a, **k):
        name = str(file)
        if any(ch in mode for ch in "wax+") and not name.endswith(".lock"):
            if name.endswith(".json.tmp") and let[0]:
                let[0] = False
                return real_open(file, mode, *a, **k)
            raise OSError(errno.ENOSPC, "No space left on device", name)
        return real_open(file, mode, *a, **k)
    return mock.patch("builtins.open", opener)


class Sampler(TempRoot):
    def evening(self, now, fake, **kw):
        clock = FakeClock(now)
        rc = SB.run_evening(fake.md, root=self.root, clock=clock, sleep=clock.sleep, fetch=fetch_directory, **QUIET, **kw)
        return rc, clock

    def status(self, session, mode):
        sts = SB.statuses(self.root / session.isoformat(), mode)
        self.assertTrue(sts, f"no {mode} status for {session}")
        return sts[-1]

    def test_evening_sample_universe_retries_and_heartbeat(self):
        s = D(2026, 11, 30)
        fake = FakeSchwab(s, truncate={"TRN": 2, "TRX": -1})
        rc, clock = self.evening(at(2026, 11, 30, 17, 35), fake)
        self.assertEqual(rc, 4)                                                # TRX never recovers: INCOMPLETE
        day = self.root / "2026-11-30"
        cand = load_json(day / "candidates.json")
        self.assertEqual(sorted(cand["symbols"]), sorted(["AAA", "JD", "ARCC", "BHF", "NTRS", "TRN", "TRX", "PFBC",
                                                          "OBAI", "BF/B", "CW", "RLX"]))
        self.assertEqual(cand["reference"], ["SPY"])                            # SPY is always sampled
        self.assertEqual(cand["directory_symbol"], {"BF/B": "BF.B"})
        excl = {e["symbol"]: e for e in SB.read_jsonl(day / "exclusions.jsonl")}
        self.assertEqual(excl["CHEAP"]["stage"], "quote")
        self.assertTrue(excl["CHEAP"]["reason"].startswith("price 2.0 outside"))
        self.assertTrue(excl["THIN"]["reason"].startswith("avg10 and avg1y volume below"))
        self.assertEqual(excl["CEFX"]["reason"], "assetSubType CEF")
        self.assertEqual(excl["EPD"]["reason"], "MLP")
        self.assertEqual(len(excl), len(EXPECTED_DIRECTORY) - 12)               # every exclusion logged once
        rows = SB.rows_by_symbol(sorted(day.glob("evening_*.jsonl")))
        self.assertEqual([r["attempt"] for r in rows["TRN"]], [1, 2, 3])        # recovered on the second retry
        self.assertEqual([r["cls"] for r in rows["TRN"]], [SB.TRUNCATED, SB.TRUNCATED, SB.PROVISIONAL])
        self.assertEqual([r["attempt"] for r in rows["TRX"]], [1, 2, 3, 4])     # 1 + 3 retries, every attempt kept
        self.assertEqual(clock.sleeps.count(SB.RETRY_PAUSE_S), 3)              # a pause before each retry round
        self.assertIn("SPY", rows)
        st = self.status(s, "evening")
        self.assertEqual(st["state"], "INCOMPLETE")
        self.assertFalse(st["late"])
        self.assertEqual(st["classes"], {SB.PROVISIONAL: 11, SB.TRUNCATED: 1})
        self.assertEqual(st["incomplete_symbols"], ["TRX"])
        runs = SB.read_jsonl(self.root / "runs.jsonl")
        self.assertEqual([(r["mode"], r["state"]) for r in runs], [("evening", "INCOMPLETE")])

    def test_a_second_evening_run_and_a_holiday_run_are_skipped(self):
        s = D(2026, 11, 30)
        self.evening(at(2026, 11, 30, 17, 35), FakeSchwab(s))
        fake = FakeSchwab(s)
        rc, _ = self.evening(at(2026, 11, 30, 18, 10), fake)
        self.assertEqual(rc, 0)
        self.assertEqual(fake.calls["daily"], [])
        self.assertEqual(self.status(s, "evening")["state"], "SKIPPED")
        fake = FakeSchwab(D(2026, 11, 25))
        rc, _ = self.evening(at(2026, 11, 26, 17, 35), fake)                  # Thanksgiving
        self.assertEqual((rc, fake.calls["daily"], fake.calls["quotes"]), (0, [], []))
        st = self.status(D(2026, 11, 25), "evening")
        self.assertEqual(st["state"], "SKIPPED")
        self.assertIn("evening window for 2026-11-25 has passed", st["reason"])

    def test_late_evening_samples_are_marked_and_filed_under_their_session(self):
        rc, _ = self.evening(at(2026, 11, 30, 22, 30), FakeSchwab(D(2026, 11, 30)))
        st = self.status(D(2026, 11, 30), "evening")
        self.assertEqual((rc, st["state"], st["late"]), (0, "DONE", True))
        self.assertIn("after the 19:30 cutoff", st["late_reasons"][0])
        root2 = self.root / "other"
        clock = FakeClock(at(2026, 12, 1, 0, 40))                              # the Mac woke after midnight
        SB.run_evening(FakeSchwab(D(2026, 11, 30), evening_final=("AAA",)).md, root=root2, clock=clock,
                       sleep=clock.sleep, fetch=fetch_directory, **QUIET)
        self.assertTrue((root2 / "2026-11-30" / "candidates.json").exists())
        self.assertFalse((root2 / "2026-12-01").exists())
        st = SB.statuses(root2 / "2026-11-30", "evening")[-1]
        self.assertTrue(st["late"])
        self.assertTrue(any("the day after the session" in r for r in st["late_reasons"]))
        self.assertTrue(any("1 candidate(s) already had a final candle" in r for r in st["late_reasons"]))

    def test_final_pull_requires_the_evening_sample_else_missed_night(self):
        fake = FakeSchwab(D(2026, 12, 1))
        clock = FakeClock(at(2026, 12, 2, 1, 30))
        rc = SB.run_final(fake.md, root=self.root, clock=clock, sleep=clock.sleep, **QUIET)
        self.assertEqual(rc, 3)
        self.assertEqual(fake.calls["daily"], [])                              # nothing pulled, nothing paired
        st = self.status(D(2026, 12, 1), "final")
        self.assertEqual(st["state"], "MISSED-NIGHT")
        self.assertFalse((self.root / "2026-11-30").exists())                  # never another session's sample
        SB.run_final(fake.md, root=self.root, clock=FakeClock(at(2026, 12, 2, 4, 30)), sleep=lambda s: None, **QUIET)
        self.assertEqual(len(SB.statuses(self.root / "2026-12-01", "final")), 1)   # logged once

    def test_final_pulls_minute_bars_and_later_pulls_only_unfinished_names(self):
        s = D(2026, 11, 30)
        self.evening(at(2026, 11, 30, 17, 35), FakeSchwab(s))
        fake = FakeSchwab(s, truncate={"CW": 1, "TRX": -1})
        clock = FakeClock(at(2026, 12, 1, 1, 30))
        rc = SB.run_final(fake.md, root=self.root, clock=clock, sleep=clock.sleep, **QUIET)
        self.assertEqual(rc, 4)                                                # TRX stays unfinished
        st = self.status(s, "final")
        self.assertEqual(st["state"], "INCOMPLETE")
        self.assertEqual(st["classes"], {SB.FINAL: 12, SB.TRUNCATED: 1})       # CW recovered on its retry
        minute = {sym for sym, *_ in fake.calls["minute"]}
        self.assertEqual(minute, {"SPY", "AAA", "JD"})                         # reference, open difference, M2-like
        fake2 = FakeSchwab(s, truncate={"TRX": 1})
        SB.run_final(fake2.md, root=self.root, clock=FakeClock(at(2026, 12, 1, 4, 30)), sleep=lambda x: None, **QUIET)
        self.assertEqual({c[0] for c in fake2.calls["daily"]}, {"TRX"})        # only the unfinished name
        st = self.status(s, "final")
        self.assertEqual((st["state"], st["unfinished"], st["final_coverage"]), ("DONE", 0, 1.0))

    def test_not_final_yet_names_are_reported_not_retried_in_run(self):
        s = D(2026, 11, 30)
        self.evening(at(2026, 11, 30, 17, 35), FakeSchwab(s))
        fake = FakeSchwab(s, final_ready=False)
        clock = FakeClock(at(2026, 11, 30, 22, 0))
        SB.run_final(fake.md, root=self.root, session=s, clock=clock, sleep=clock.sleep, **QUIET)
        st = self.status(s, "final")
        self.assertEqual(st["classes"], {SB.NOT_FINAL: 13})
        self.assertEqual(clock.sleeps, [])
        self.assertEqual(st["unfinished"], 12)

    def test_a_held_session_lock_skips_a_duplicate_run(self):
        s = D(2026, 11, 30)
        with SB.SessionLock(self.root / s.isoformat(), "evening"):
            fake = FakeSchwab(s)
            rc, _ = self.evening(at(2026, 11, 30, 17, 35), fake)
        self.assertEqual((rc, fake.calls["daily"]), (0, []))
        self.assertIn("another evening run", self.status(s, "evening")["reason"])

    def test_directory_outage_falls_back_to_the_last_archive(self):
        self.evening(at(2026, 11, 27, 17, 35), FakeSchwab(D(2026, 11, 27)))

        def broken(url):
            raise OSError("no route")
        clock = FakeClock(at(2026, 11, 30, 17, 35))
        SB.run_evening(FakeSchwab(D(2026, 11, 30)).md, root=self.root, clock=clock, sleep=clock.sleep, fetch=broken, **QUIET)
        cand = load_json(self.root / "2026-11-30" / "candidates.json")
        self.assertTrue(cand["directory_source"].startswith("FALLBACK 2026-11-27/directory"))
        self.assertEqual(len(cand["symbols"]), 12)

    def test_shared_rate_limiter(self):
        t = [1000.0]
        slept = []

        def sleep(s):
            slept.append(round(s, 3))
            t[0] += s
        lim = SB.SharedRateLimiter(self.root / "lock", per_minute=3, spacing=0.0, clock=lambda: t[0], sleep=sleep)
        for _ in range(3):
            lim.wait()
            t[0] += 1.0
        lim.wait()                                                             # the 4th waits for the first to age out
        self.assertEqual(slept, [57.0])
        lim2 = SB.SharedRateLimiter(self.root / "lock", per_minute=100, spacing=0.6, clock=lambda: t[0], sleep=sleep)
        lim2.wait()                                                            # another process, the same budget file
        self.assertEqual(slept[-1], 0.6)

    # --- review SVC-06: the evening's completeness gate, and re-running an INCOMPLETE evening -------------------
    def test_three_empty_names_of_a_thousand_still_make_a_done_evening(self):
        """DONE needs SPY's bar, no failed quote chunk and a bar for ceil(0.99 x 1,000) = 990 names. The names
        without one are still listed and counted; a DONE evening notifies only when LATE."""
        s = D(2026, 11, 30)
        empty = ["N0007", "N0500", "N0999"]
        notes = []
        rc, _ = self.evening(at(2026, 11, 30, 17, 35), ManyNames(self.root, s, empty=empty),
                             notify=lambda t, m: notes.append(m))
        st = self.status(s, "evening")
        self.assertEqual((rc, st["state"], notes), (0, "DONE", []))
        self.assertEqual((st["incomplete_symbols"], st["incomplete_count"], st["incomplete_reasons"]), (empty, 3, []))
        self.assertEqual(st["completeness"], dict(with_bar=997, candidates=1000, needed=990))
        self.assertEqual((SB.completeness_needed(1000), SB.completeness_needed(12), SB.completeness_needed(1926)),
                         (990, 12, 1907))                                      # exact: ceil(99/100 x n)
        late_root = self.root / "late"
        clock = FakeClock(at(2026, 11, 30, 22, 30))
        rc = SB.run_evening(ManyNames(late_root, s, empty=empty).md, root=late_root, clock=clock, sleep=clock.sleep,
                            fetch=fetch_directory, notify=lambda t, m: notes.append(m), **QUIET)
        self.assertEqual((rc, notes), (0, ["evening 2026-11-30: DONE LATE (3 incomplete)"]))

    def test_twenty_empty_names_of_a_thousand_are_incomplete_and_a_rerun_pulls_only_them(self):
        s = D(2026, 11, 30)
        empty = [f"N{i:04d}" for i in range(0, 1000, 50)]
        notes = []
        rc, _ = self.evening(at(2026, 11, 30, 17, 35), ManyNames(self.root, s, empty=empty),
                             notify=lambda t, m: notes.append(m))
        st = self.status(s, "evening")
        self.assertEqual((rc, st["state"], st["incomplete_count"], st["incomplete_symbols"]), (4, "INCOMPLETE", 20, empty))
        self.assertEqual(st["incomplete_reasons"], ["980 of 1000 candidates have a bar, fewer than 990 "
                                                    "(params.completeness_min 0.99)"])
        self.assertEqual(notes, ["evening 2026-11-30: INCOMPLETE (20 incomplete)"])
        again = ManyNames(self.root, s, write=False)                           # the 20 answer now
        rc, _ = self.evening(at(2026, 11, 30, 18, 15), again)
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(again.asked), empty)                           # not SPY, not the 980 with a bar
        st = self.status(s, "evening")
        self.assertEqual((st["state"], st["incomplete_count"], st["requested"]), ("DONE", 0, 20))
        third = ManyNames(self.root, s, write=False)
        rc, _ = self.evening(at(2026, 11, 30, 19, 0), third)                   # only a DONE evening blocks a re-run
        self.assertEqual((rc, third.asked, self.status(s, "evening")["state"]), (0, [], "SKIPPED"))

    def test_a_missing_spy_bar_or_a_failed_quote_chunk_is_incomplete_whatever_the_count(self):
        s = D(2026, 11, 30)
        rc, _ = self.evening(at(2026, 11, 30, 17, 35), ManyNames(self.root, s, n=10, empty=("SPY",)))
        st = self.status(s, "evening")
        self.assertEqual((rc, st["state"], st["incomplete_reasons"]), (4, "INCOMPLETE", ["reference SPY has no bar"]))
        other = self.root / "q"
        clock = FakeClock(at(2026, 11, 30, 17, 35))
        rc = SB.run_evening(ManyNames(other, s, n=10, quotes_fail=True).md, root=other, clock=clock, sleep=clock.sleep,
                            fetch=fetch_directory, **QUIET)
        st = SB.statuses(other / s.isoformat(), "evening")[-1]
        self.assertEqual((rc, st["state"], st["incomplete_reasons"]),
                         (4, "INCOMPLETE", ["1 quote chunk(s) failed after retries"]))
        zero = self.root / "z"                                                 # ceil(0.99 x 0) = 0 must not pass
        clock = FakeClock(at(2026, 11, 30, 17, 35))
        rc = SB.run_evening(ManyNames(zero, s, n=0).md, root=zero, clock=clock, sleep=clock.sleep,
                            fetch=fetch_directory, **QUIET)
        st = SB.statuses(zero / s.isoformat(), "evening")[-1]
        self.assertEqual((rc, st["state"], st["incomplete_reasons"]), (4, "INCOMPLETE", ["no candidates"]))

    def test_the_directory_reader_fetches_only_the_two_directory_files(self):
        """Review safety F2: httpx is allowlisted in the package for the symbol directory only, so any other URL is
        refused before httpx is reached. A stand-in httpx: nothing is fetched."""
        calls = []

        def refuse(url, **kw):
            calls.append(url)
            raise AssertionError(f"httpx.get was called for {url}")
        fake = types.ModuleType("httpx")
        fake.get = refuse
        with mock.patch.dict(sys.modules, {"httpx": fake}):
            for url in ("https://example.com/nasdaqlisted.txt", "http://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt",
                        "https://www.nasdaqtrader.com/dynamic/symdir/", "", "nasdaqlisted.txt"):
                with self.assertRaises(ValueError, msg=url):
                    SB.fetch_directory_http(url)
        self.assertEqual(calls, [])
        ok = types.SimpleNamespace(content=b"Symbol|Security Name\n", raise_for_status=lambda: None)
        fake.get = lambda url, **kw: calls.append((url, kw["timeout"], kw["follow_redirects"])) or ok
        with mock.patch.dict(sys.modules, {"httpx": fake}):
            for url in SB.DIRECTORY.values():
                self.assertEqual(SB.fetch_directory_http(url), b"Symbol|Security Name\n")
        self.assertEqual(calls, [(url, 60, True) for url in SB.DIRECTORY.values()])

    # --- critic: on a full disk the run still notifies, and nothing escapes ----------------------------------------
    def test_a_full_disk_still_notifies_and_the_failed_status_write_is_logged_never_raised(self):
        s = D(2026, 11, 30)
        notes, logs = [], []
        clock = FakeClock(at(2026, 11, 30, 17, 35))
        with full_disk():
            rc = SB.run_evening(FakeSchwab(s).md, root=self.root, clock=clock, sleep=clock.sleep, fetch=fetch_directory,
                                notify=lambda t, m: notes.append(m), log=logs.append)
        self.assertEqual((rc, notes), (1, ["evening 2026-11-30 FAILED: OSError"]))
        self.assertTrue(any("evening 2026-11-30: the FAILED status could not be written (OSError" in m for m in logs), logs)
        self.assertEqual([st["state"] for st in SB.statuses(self.root / s.isoformat())], ["STARTED"])
        other = self.root / "f"
        self.evening_into(other, s)
        notes.clear()
        clock = FakeClock(at(2026, 12, 1, 1, 30))
        with full_disk():
            rc = SB.run_final(FakeSchwab(s).md, root=other, clock=clock, sleep=clock.sleep,
                              notify=lambda t, m: notes.append(m), log=logs.append)
        self.assertEqual((rc, notes), (1, ["final 2026-11-30 FAILED: OSError"]))
        self.assertTrue(any("final 2026-11-30: the FAILED status could not be written (OSError" in m for m in logs))

    def evening_into(self, root: Path, s: dt.date) -> None:
        clock = FakeClock(dt.datetime.combine(s, dt.time(17, 35), NY))
        self.assertEqual(SB.run_evening(FakeSchwab(s).md, root=root, clock=clock, sleep=clock.sleep,
                                        fetch=fetch_directory, **QUIET), 0)

    # --- R16: an INCOMPLETE final pull is quiet unless it is the last target -----------------------------------
    def test_an_incomplete_final_pull_notifies_only_when_asked_and_missed_night_once_in_any_mode(self):
        s = D(2026, 11, 30)
        self.evening_into(self.root, s)
        notes = []
        for quiet in (True, False):
            clock = FakeClock(at(2026, 12, 1, 1 if quiet else 4, 30))
            rc = SB.run_final(FakeSchwab(s, final_ready=False).md, root=self.root, clock=clock, sleep=clock.sleep,
                              notify=lambda t, m: notes.append(m), notify_incomplete=not quiet, **QUIET)
            self.assertEqual(rc, 4)
        self.assertEqual(notes, ["final 2026-11-30: INCOMPLETE, 12 names not final, SPY not final"])
        # a session already flagged MISSED-NIGHT (here by the missed-night detection, mode 'evening') is not again
        SB.RunStatus(self.root, D(2026, 12, 1), "evening", at(2026, 12, 2, 5, 0)).finish(
            at(2026, 12, 2, 5, 0), "MISSED-NIGHT", reason="no evening sample")
        notes.clear()
        rc = SB.run_final(FakeSchwab(D(2026, 12, 1)).md, root=self.root, session=D(2026, 12, 1),
                          clock=FakeClock(at(2026, 12, 2, 6, 0)), sleep=lambda x: None,
                          notify=lambda t, m: notes.append(m), **QUIET)
        self.assertEqual((rc, notes), (3, []))
        self.assertEqual([(st["mode"], st["state"]) for st in SB.statuses(self.root / "2026-12-01")],
                         [("evening", "MISSED-NIGHT")])


class FakeClient:
    """A schwab-py client stand-in with the three read calls the wrapper uses (and nothing else)."""

    def __init__(self, status: int = 200):
        self.status, self.calls = status, []

    def _resp(self, payload):
        return types.SimpleNamespace(status_code=self.status, json=lambda: payload)

    def get_price_history_every_day(self, symbol, **kw):
        self.calls.append(("daily", symbol, kw))
        return self._resp({"candles": [{"day": 1}]})

    def get_price_history_every_minute(self, symbol, **kw):
        self.calls.append(("minute", symbol, kw))
        return self._resp({"candles": [{"minute": 1}]})

    def get_quotes(self, symbols):
        self.calls.append(("quotes", list(symbols)))
        return self._resp({"SPY": {"quote": {}}})


class MovingClock:
    def __init__(self, start: dt.datetime):
        self.t = start

    def now(self) -> dt.datetime:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += dt.timedelta(seconds=s)


def _token_ok():
    """A token with 100 hours of life left."""
    return 100.0, "2026-12-04T21:35:00-05:00"


_UNSET = object()


class MainHarness:
    """sample_bars.main (or the runner's main) with the clock stubbed and run_evening / run_final replaced by
    recorders of the wrapper each is given. A mixin, so its users do not inherit each other's tests."""

    STUB = staticmethod(lambda: SB.MarketData(lambda *a: [], lambda *a: [], lambda *a: {}))

    def run_main(self, argv, clock=None, entry=None, token=_UNSET, notes=None, logs=None, awake=None, **kw):
        """A token with 100 h left (or ``token``; None for no reader), notifications into ``notes`` (or none), log
        lines into ``logs`` (or none), the power assertion into ``awake`` (or none)."""
        clock = clock or MovingClock(at(2026, 11, 30, 17, 35))
        seen = []
        token = _token_ok if token is _UNSET else token
        note = None if notes is None else (lambda t, m: notes.append(m))
        hold = (lambda on: None) if awake is None else (lambda on: awake.append((clock.now(), on)))
        with mock.patch.object(SB, "now_et", clock.now), mock.patch.object(SB.time, "sleep", clock.sleep), \
                mock.patch.object(SB, "log_line", (lambda m: None) if logs is None else logs.append), \
                mock.patch.object(SB, "run_evening", lambda md, **k: seen.append(("evening", md)) or 0), \
                mock.patch.object(SB, "run_final", lambda md, **k: seen.append(("final", md)) or 0):
            rc = (entry or SB.main)(argv, token_hours=token, notify=note, awake=hold, **kw)
        return rc, seen

    def failed(self, root: Path) -> list[dict]:
        return [s for d in sorted(root.iterdir()) if d.is_dir() for s in SB.statuses(d)]


class Runner(MainHarness, TempRoot):
    """Review D7 (spec 2: phase2 code sees only a wrapped client) and safety S5 and S8. loops/phase2_sample.py,
    outside the package, builds the client and wraps it, reads the token and holds the power assertion;
    sample_bars.main takes only callables, and calls the wrapper factory once per pull, after that pull's own
    token check."""

    def fake_config(self, client):
        built = []
        mod = types.ModuleType("config")
        mod.load_settings = lambda: "settings"

        def build_client(settings):
            built.append(settings)
            return client
        mod.build_client = build_client
        return mod, built

    def test_the_runner_builds_the_client_and_hands_out_three_read_closures(self):
        client = FakeClient()
        mod, built = self.fake_config(client)
        waits = []
        limiter = types.SimpleNamespace(wait=lambda: waits.append(1))
        with mock.patch.dict(sys.modules, {"config": mod}):
            md = PR.schwab_market_data(limiter)
        self.assertEqual(built, ["settings"])
        self.assertIs(SB.require_market_data(md), md)
        self.assertEqual(SB.MarketData.__slots__, ("daily", "minute", "quotes"))     # no room for a client object
        t0, t1 = at(2026, 11, 30, 9, 30), at(2026, 11, 30, 16, 0)
        self.assertEqual((md.daily("AAA", t0, t1), md.minute("AAA", t0, t1), md.quotes(["SPY"])),
                         ([{"day": 1}], [{"minute": 1}], {"SPY": {"quote": {}}}))
        self.assertEqual(len(waits), 3)                                        # every read waits on the shared limiter
        self.assertEqual([c[0] for c in client.calls], ["daily", "minute", "quotes"])
        self.assertEqual(client.calls[0][2], dict(start_datetime=t0, end_datetime=t1, need_extended_hours_data=False))
        with self.assertRaisesRegex(RuntimeError, "daily AAA: HTTP 500"):
            PR.read_only_market_data(FakeClient(status=500), limiter).daily("AAA", t0, t1)

    def test_importing_the_runner_reads_no_settings_and_builds_no_client(self):
        """Importing the runner imports neither config nor loop_common: config only inside the wrapper factory,
        loop_common only inside the token reader and the notifier (safety S5: the package imports neither)."""
        with open(PR.__file__, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        top = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                top.add((node.module or "").split(".")[0])
        self.assertLessEqual(top, {"__future__", "atexit", "datetime", "os", "subprocess", "sys", "pathlib", "typing",
                                   "phase2"})
        deferred: dict[str, list[str]] = {}
        for f in ast.walk(tree):
            if isinstance(f, ast.FunctionDef):
                for n in ast.walk(f):
                    names = [n.module] if isinstance(n, ast.ImportFrom) else \
                        [a.name for a in n.names] if isinstance(n, ast.Import) else []
                    for name in names:
                        deferred.setdefault(name, []).append(f.name)
        self.assertEqual(deferred, {"config": ["schwab_market_data"],              # the one place a client is built
                                    "loop_common": ["token_hours_left", "macos_notify"]})

    def test_every_pull_builds_its_own_wrapper_after_its_own_token_check(self):
        """Critic (major) and safety S8: one long-lived client writes the creation time it loaded back into the
        token file at its next refresh, reverting a re-authentication made between pulls. So the factory runs once
        per pull, each time after that pull's own token check, and each pull uses the wrapper its own call returned."""
        events = []

        def factory():
            md = self.STUB()
            events.append(("factory", md))
            return md

        def token():
            events.append(("token", None))
            return 100.0, "2026-12-04T21:35:00-05:00"
        clock = MovingClock(at(2026, 11, 30, 17, 35))
        with mock.patch.object(SB, "now_et", clock.now), mock.patch.object(SB.time, "sleep", clock.sleep), \
                mock.patch.object(SB, "log_line", lambda m: None), \
                mock.patch.object(SB, "run_evening", lambda md, **k: events.append(("evening", md)) or 0), \
                mock.patch.object(SB, "run_final", lambda md, **k: events.append(("final", md)) or 0):
            rc = PR.main(["night", "--root", str(self.root)], factory=factory, token_hours=token, notify=None,
                         awake=lambda on: None)
        self.assertEqual(rc, 0)
        self.assertEqual([k for k, _ in events], ["token", "factory", "evening"] + ["token", "factory", "final"] * 6)
        for i in range(0, len(events), 3):
            self.assertIs(events[i + 2][1], events[i + 1][1])                  # the pull uses its own call's wrapper
        self.assertEqual(len({id(m) for k, m in events if k == "factory"}), 7)  # a fresh wrapper for every pull
        events.clear()
        rc, seen = self.run_main(["final", "--root", str(self.root / "f"), "--session", "2026-11-30", "--at",
                                  "01:30,04:30"], clock=MovingClock(at(2026, 12, 1, 1, 0)), token=token,
                                 market_data=factory)
        self.assertEqual([k for k, _ in events], ["token", "factory"] * 2)
        self.assertEqual([m for _, m in seen], [m for k, m in events if k == "factory"])

    def test_a_failed_token_check_never_builds_the_wrapper(self):
        """Integration check, gap A: the factory runs only after the token check passes, so a token with too
        little life left never gets a client built. Every network mode: exit 1, no factory call, no pull, a FAILED
        status for every check (the night's evening, its two retries and six overnight pulls), and one notification
        per process (R18)."""
        calls = []

        def factory():
            calls.append(1)
            return self.STUB()
        for argv, clock, want in (
                (["evening"], None, ["evening"]),
                (["final", "--session", "2026-11-30", "--at", "01:30,04:30"], MovingClock(at(2026, 12, 1, 1, 0)),
                 ["final", "final"]),
                (["night"], None, ["evening"] * 3 + ["final"] * 6)):
            calls.clear()
            root, notes = self.root / argv[0], []
            rc, seen = self.run_main(argv + ["--root", str(root)], clock=clock, token=lambda: (1.0, "2026-11-30T18:35:00-05:00"),
                                     notes=notes, market_data=factory)
            self.assertEqual((rc, calls, seen), (1, [], []), argv[0])
            runs = SB.read_jsonl(root / "runs.jsonl")
            self.assertEqual([r["mode"] for r in runs], want, argv[0])
            self.assertEqual({(r["state"], r["error"]) for r in runs}, {("FAILED", "token has 1.0 h left (< 3 h)")})
            self.assertEqual(notes, [f"{want[0]} FAILED: token has 1.0 h left (< 3 h); re-authenticate with setup_auth.py"])
        for i, (bad, why) in enumerate(((lambda: (None, None), "token unreadable"), (lambda: 1 / 0, "token unreadable"),
                                        (lambda: "12.5", "token unreadable"),
                                        (lambda: ("abc", None), "token unreadable"),     # float() fails closed
                                        (lambda: (float("nan"), None), "token has nan h left (< 3 h)"))):
            root = self.root / f"bad{i}"
            rc, seen = self.run_main(["evening", "--root", str(root)], token=bad, market_data=factory)
            runs = SB.read_jsonl(root / "runs.jsonl")
            self.assertEqual((rc, seen, [(r["state"], r["error"]) for r in runs]), (1, [], [("FAILED", why)]))   # fail closed
        self.assertEqual(calls, [])

    def test_a_network_mode_without_the_runner_fails_at_once(self):
        """Without the wrapper factory, without the token reader, or without both, every network mode is FAILED at
        once, before any wait (a final with --at 01:30 at 17:35 does not wait), notified when a notifier is given."""
        cases = (({}, _UNSET, "no market-data wrapper was supplied"),
                 (dict(market_data=self.STUB), None, "no token reader was supplied"),
                 ({}, None, "no market-data wrapper or token reader was supplied"))
        for mode in ("evening", "final", "night"):
            for i, (kw, token, why) in enumerate(cases):
                root, notes, clock = self.root / f"{mode}{i}", [], MovingClock(at(2026, 11, 30, 17, 35))
                argv = [mode, "--root", str(root)] + (["--at", "01:30"] if mode == "final" else [])
                rc, seen = self.run_main(argv, clock=clock, token=token, notes=notes, **kw)
                self.assertEqual((rc, seen, clock.t), (1, [], at(2026, 11, 30, 17, 35)), (mode, why))
                sts = self.failed(root)
                self.assertEqual([(s["mode"], s["state"], s["session"]) for s in sts], [(mode, "FAILED", "2026-11-30")])
                self.assertIn(why, sts[0]["error"])
                self.assertIn("run the network modes through loops/phase2_sample.py", sts[0]["error"])
                self.assertEqual([n.split(":")[0] for n in notes], [f"{mode} FAILED"])
                self.assertTrue(notes[0].startswith(f"{mode} FAILED: {why}"), notes)
        with contextlib.redirect_stdout(io.StringIO()):
            rc, _ = self.run_main(["plan", "--now", "2026-11-30T17:35:00-05:00"], token=None)   # plan needs none of them
        self.assertEqual(rc, 0)

    def test_a_factory_that_fails_or_hands_over_a_client_is_failed_never_run(self):
        def broken():
            raise RuntimeError("no token file")
        for name, factory, why in (("client", FakeClient, "not FakeClient"),
                                   ("broken", broken, "RuntimeError: no token file")):
            root = self.root / name
            rc, seen = self.run_main(["evening", "--root", str(root)], market_data=factory)
            self.assertEqual((rc, seen), (1, []), name)
            sts = self.failed(root)
            self.assertEqual([s["state"] for s in sts], ["FAILED"])
            self.assertIn("the market-data wrapper could not be built", sts[0]["error"])
            self.assertIn(why, sts[0]["error"])
        tries = []

        def flaky():                                    # fails at 01:30, works at 04:30: each pull retries it
            tries.append(1)
            if len(tries) == 1:
                raise RuntimeError("token file busy")
            return self.STUB()
        rc, seen = self.run_main(["final", "--root", str(self.root / "f"), "--session", "2026-11-30", "--at",
                                  "01:30,04:30"], clock=MovingClock(at(2026, 12, 1, 1, 0)), market_data=flaky)
        self.assertEqual((rc, len(tries), [k for k, _ in seen]), (0, 2, ["final"]))
        self.assertEqual([s["state"] for s in self.failed(self.root / "f")], ["FAILED"])

    def test_the_package_reads_no_token_and_has_no_notifier_of_its_own(self):
        """Safety S5: the token reader and the notifier moved to the runner."""
        for name in ("token_hours_left", "_notifier"):
            self.assertFalse(hasattr(SB, name), name)
        self.assertTrue(callable(PR.token_hours_left) and callable(PR.macos_notify))

    def test_the_runner_reads_the_token_age_the_way_the_package_did(self):
        """loop_common.token_age_days(loop_common.resolve_token_path()) against REFRESH_TOKEN_LIFETIME_DAYS; a
        reader that fails gives (None, None). A stand-in loop_common: no token file is read."""
        fake, seen = types.ModuleType("loop_common"), []
        fake.REFRESH_TOKEN_LIFETIME_DAYS = 7.0
        fake.resolve_token_path = lambda: "TOKEN-PATH"
        fake.token_age_days = lambda p: seen.append(p) or 6.5
        with mock.patch.dict(sys.modules, {"loop_common": fake}), \
                mock.patch.object(SB, "now_et", lambda: at(2026, 11, 30, 17, 30)):
            self.assertEqual(PR.token_hours_left(), (12.0, "2026-12-01T05:30:00-05:00"))

            def missing(p):
                raise FileNotFoundError(p)
            fake.token_age_days = missing
            self.assertEqual(PR.token_hours_left(), (None, None))
        self.assertEqual(seen, ["TOKEN-PATH"])
        # 24 h of life across the 2027-03-14 spring-forward: elapsed hours, so 13:00 EDT, not 12:00 (F12)
        fake.token_age_days = lambda p: 6.0
        with mock.patch.dict(sys.modules, {"loop_common": fake}), \
                mock.patch.object(SB, "now_et", lambda: at(2027, 3, 13, 12, 0)):
            self.assertEqual(PR.token_hours_left(), (24.0, "2027-03-14T13:00:00-04:00"))

    def test_the_runner_notifies_through_loop_common_and_never_raises(self):
        fake, sent = types.ModuleType("loop_common"), []
        fake.notify = lambda title, message: sent.append((title, message))
        with mock.patch.dict(sys.modules, {"loop_common": fake}):
            PR.macos_notify("Phase 2 bar sample", "evening 2026-11-30: INCOMPLETE")

            def broken(title, message):
                raise OSError("no GUI session")
            fake.notify = broken
            PR.macos_notify("Phase 2 bar sample", "never raises")
        self.assertEqual(sent, [("Phase 2 bar sample", "evening 2026-11-30: INCOMPLETE")])

    def test_the_power_assertion_is_caffeinate_on_this_process_idempotent_both_ways(self):
        """R10: /usr/bin/caffeinate -i -w <pid>, all std streams to /dev/null; a stand-in Popen, never a real one."""
        spawned = []

        class FakeProc:
            def __init__(self, args, **kw):
                self.args, self.kw, self.code, self.events = args, kw, None, []
                spawned.append(self)

            def poll(self):
                return self.code

            def terminate(self):
                self.events.append("terminate")
                self.code = -15

            def wait(self, timeout=None):
                self.events.append("wait")
                return self.code

            def kill(self):
                self.events.append("kill")
        p = PR.PowerAssertion(popen=FakeProc, pid=4242)
        p(True)
        p(True)
        self.assertEqual(len(spawned), 1)
        self.assertEqual(spawned[0].args, ["/usr/bin/caffeinate", "-i", "-w", "4242"])
        self.assertEqual(spawned[0].kw, dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        p(False)
        p(False)
        p.release()
        self.assertEqual(spawned[0].events, ["terminate", "wait"])
        p(True)
        self.assertEqual(len(spawned), 2)                                      # on again: a new assertion
        spawned[1].code = 0                                                    # caffeinate ended by itself
        p(True)
        self.assertEqual(len(spawned), 3)
        p.release()
        self.assertEqual(spawned[1].events, [])                                # an ended process is not signalled
        self.assertEqual(PR.PowerAssertion().pid, os.getpid())

    def test_the_runner_hands_sample_bars_its_four_callables_and_releases_the_assertion(self):
        got, registered, powers = {}, [], []

        class FakePower:
            def __init__(self):
                self.state, self.released = None, 0
                powers.append(self)

            def __call__(self, on):
                self.state = on

            def release(self):
                self.released += 1

        def fake_main(argv, **kw):
            got.update(kw, argv=argv)
            kw["awake"](True)
            return 4
        with mock.patch.object(PR, "PowerAssertion", FakePower), mock.patch.object(PR.atexit, "register", registered.append), \
                mock.patch.object(PR.SB, "main", fake_main):
            self.assertEqual(PR.main(["night"]), 4)
        self.assertEqual(sorted(got), ["argv", "awake", "market_data", "notify", "token_hours"])
        self.assertIs(got["market_data"], PR.schwab_market_data)
        self.assertIs(got["token_hours"], PR.token_hours_left)
        self.assertIs(got["notify"], PR.macos_notify)
        self.assertIs(got["awake"], powers[0])
        self.assertEqual(registered, [powers[0].release])                     # released at exit ...
        self.assertEqual(powers[0].released, 1)                                # ... and in the runner's finally


# =========================================================================================================
# 4b. The night job: passes, roll-over, retries, missed nights, catch-up, the power assertion, the token
# =========================================================================================================

class SleepyClock:
    """The wall clock of a Mac that sleeps: in each (from, to) window of ``asleep`` the process is frozen, so a nap
    that starts or ends inside one returns at its end. Stand-in runs move the clock by their own durations."""

    def __init__(self, start: dt.datetime, asleep=()):
        self.t, self.asleep = start, list(asleep)

    def now(self) -> dt.datetime:
        return self.t

    def sleep(self, s: float) -> None:
        t = self.t + dt.timedelta(seconds=s)
        for a, b in self.asleep:
            if a <= self.t < b or a <= t < b:
                t = max(t, b)
        self.t = t


class Killed(BaseException):
    """The process dies at once (a power cut, a forced restart): not an Exception, so no handler of the sampler's
    catches it, and the statuses on disk are what the next process finds."""


class NightClock(SleepyClock):
    """A SleepyClock whose process is killed at ``kill``: the first nap that reaches it raises Killed."""

    def __init__(self, start: dt.datetime, asleep=(), kill=None):
        super().__init__(start, asleep)
        self.kill = kill

    def sleep(self, s: float) -> None:
        super().sleep(s)
        if self.kill is not None and self.t >= self.kill:
            raise Killed(self.t)


class NightSim:
    """main(['night']) on a scripted clock (the approach of review_final/critic/scripts/night_lifetime.py). The
    stand-ins for run_evening and run_final write the statuses a real run would (and a DONE evening its
    candidates.json and a usable row), so the missed-night detection and the catch-up see them, and take realistic
    time: 20 minutes for an evening and for a session's first overnight pull, 1 minute for later pulls. The token
    reader, the notifier and the power assertion are recorders (``noted`` keeps each notification's time). No
    network and no market data."""

    def __init__(self, root: Path, start: dt.datetime, asleep=()):
        self.root, self.clock = Path(root), SleepyClock(start, asleep)
        self.token = lambda: (150.0, "2026-12-31T12:00:00-05:00")
        self.events, self.notes, self.awake, self.logs, self.factory_calls = [], [], [], [], []
        self.noted: list[tuple] = []
        self.evening_codes: list[int] = []                 # codes for the first evening calls (1: FAILED); then 0

    def run_evening(self, md, *, root, **kw):
        start = self.clock.now()
        session = SB.last_completed_session(start)
        timing, _ = SB.evening_timing(start, session)
        if self.evening_codes and self.evening_codes.pop(0) == 1:
            self.clock.t += dt.timedelta(minutes=1)
            SB.RunStatus(root, session, "evening", start).finish(self.clock.now(), "FAILED", error="RuntimeError")
            self.events.append(("evening", session, start, "FAILED"))
            return 1
        if timing == "TOO_LATE" or any(s.get("state") == "DONE"
                                       for s in SB.statuses(Path(root) / session.isoformat(), "evening")):
            SB.RunStatus(root, session, "evening", start).finish(start, "SKIPPED")
            self.events.append(("evening", session, start, "SKIPPED"))
            return 0
        self.clock.t += dt.timedelta(minutes=20)
        seed_evening(root, session, start)
        SB.RunStatus(root, session, "evening", start, late=timing == "LATE").finish(self.clock.now(), "DONE")
        self.events.append(("evening", session, start, timing))
        return 0

    def run_final(self, md, *, root, session, full=False, notify_incomplete=True, **kw):
        start = self.clock.now()
        first = not any(e[0] == "final" and e[1] == session for e in self.events)
        self.clock.t += dt.timedelta(minutes=20 if first else 1)
        SB.RunStatus(root, session, "final", start).finish(self.clock.now(), "DONE")
        self.events.append(("final", session, start, full, notify_incomplete))
        return 0

    def factory(self):
        self.factory_calls.append(self.clock.now())
        return SB.MarketData(lambda *a: [], lambda *a: [], lambda *a: {})

    def run(self, *argv) -> int:
        with mock.patch.object(SB, "now_et", self.clock.now), mock.patch.object(SB.time, "sleep", self.clock.sleep), \
                mock.patch.object(SB, "log_line", self.logs.append), \
                mock.patch.object(SB, "run_evening", self.run_evening), mock.patch.object(SB, "run_final", self.run_final):
            return SB.main(["night", "--root", str(self.root), *argv], market_data=self.factory,
                           token_hours=lambda: self.token(), notify=self.note,
                           awake=lambda on: self.awake.append((self.clock.now(), on)))

    def note(self, title: str, message: str) -> None:
        self.notes.append(message)
        self.noted.append((self.clock.now(), message))

    def evenings(self) -> list[tuple]:
        return [(e[1], e[2], e[3]) for e in self.events if e[0] == "evening"]

    def finals(self, session: dt.date) -> list[tuple]:
        """(start, full, notify_incomplete) of each overnight pull for ``session``."""
        return [(e[2], e[3], e[4]) for e in self.events if e[0] == "final" and e[1] == session]


WED, THU, FRI, MON = D(2026, 11, 18), D(2026, 11, 19), D(2026, 11, 20), D(2026, 11, 23)


def overnight(session: dt.date) -> list[tuple]:
    """A normal night's overnight pulls for ``session``: (time, full, notify_incomplete), full at 06:30 only and an
    INCOMPLETE notified at 07:30 only (R16)."""
    nxt = session + dt.timedelta(days=1)
    return [(dt.datetime.combine(nxt, dt.time.fromisoformat(t), NY), t == "06:30", t == "07:30")
            for t in ("00:30", "01:00", "01:30", "04:30", "06:30", "07:30")]


class NightJob(TempRoot):
    """The critic's scripted-clock cases A-D (review_final/critic/out/night_lifetime.out), the pass limit, the
    power assertion and the token warning."""

    def test_A_lid_closed_until_the_next_evening_rolls_over_into_that_night(self):
        """Launched Wed 17:20; the Mac sleeps Wed 23:00 to Thu 19:00. On waking, Thu's evening is due (Thu has closed
        and it is after Thu 17:20), so the pass makes none of Wed's six pulls and the process (whose Thu 17:20 launch
        launchd dropped) rolls over at once: Thu's evening is sampled ON_TIME at 19:00, then Wed's catch-up pull
        (every symbol: Wed has no final row yet), then Thu's overnight pulls (F4)."""
        sim = NightSim(self.root, at(2026, 11, 18, 17, 20), asleep=[(at(2026, 11, 18, 23, 0), at(2026, 11, 19, 19, 0))])
        self.assertEqual(sim.run(), 0)
        self.assertEqual(sim.evenings(), [(WED, at(2026, 11, 18, 17, 30), "ON_TIME"),
                                          (THU, at(2026, 11, 19, 19, 0), "ON_TIME")])
        self.assertEqual(sim.finals(WED), [(at(2026, 11, 19, 19, 20), False, True)])     # the catch-up, after it
        self.assertEqual(sim.finals(THU), overnight(THU))
        self.assertEqual(sum("rolls over into pass 2" in m for m in sim.logs), 1)
        self.assertTrue(any("woke Thu 11-19 19:00 with pulls still due, and 2026-11-19's evening is due: they are left "
                            "to 2026-11-19's pass" in m for m in sim.logs), sim.logs)
        self.assertFalse([m for m in sim.logs if "have passed" in m])          # no collapsed pull was made
        self.assertEqual(sim.awake, [(at(2026, 11, 18, 17, 20), True), (at(2026, 11, 19, 19, 0), False),
                                     (at(2026, 11, 19, 19, 0), True), (at(2026, 11, 20, 7, 31), False),
                                     (at(2026, 11, 20, 7, 31), False)])
        self.assertEqual(sim.notes, [])

    def test_B_asleep_from_friday_night_to_monday_evening_rolls_over_into_mondays_night(self):
        sim = NightSim(self.root, at(2026, 11, 20, 17, 20), asleep=[(at(2026, 11, 20, 23, 0), at(2026, 11, 23, 19, 0))])
        self.assertEqual(sim.run(), 0)
        self.assertEqual(sim.evenings(), [(FRI, at(2026, 11, 20, 17, 30), "ON_TIME"),
                                          (MON, at(2026, 11, 23, 19, 0), "ON_TIME")])
        self.assertEqual(sim.finals(FRI), [(at(2026, 11, 23, 19, 20), False, True)])     # Mon's catch-up of Fri
        self.assertEqual(sim.finals(MON), overnight(MON))
        self.assertEqual(sim.notes, [])                                        # Friday was sampled: nothing missed

    def test_a_late_start_samples_the_evening_before_any_catch_up_pull(self):
        """F4: a catch-up pull, or a previous pass's collapsed pull, ran before the evening sample and could make an
        on-time evening LATE (a 19:15 start: 19:35). A start at or after the hold time now samples the evening first;
        a daytime start keeps the catch-up first (MissedNights)."""
        mon, tue = D(2026, 11, 30), D(2026, 12, 1)
        ev = at(2026, 11, 30, 17, 30)                                          # Monday sampled, then the power went
        SB.RunStatus(self.root, mon, "evening", ev).finish(at(2026, 11, 30, 17, 50), "DONE")
        seed_evening(self.root, mon, ev)
        sim = NightSim(self.root, at(2026, 12, 1, 19, 15))                     # started Tue 19:15 (RunAtLoad)
        self.assertEqual(sim.run(), 0)
        self.assertEqual(sim.evenings(), [(tue, at(2026, 12, 1, 19, 15), "ON_TIME")])
        self.assertEqual(sim.finals(mon), [(at(2026, 12, 1, 19, 35), False, True)])       # Monday's catch-up after it
        self.assertEqual(sim.finals(tue), overnight(tue))
        self.assertEqual(sim.awake[0], (at(2026, 12, 1, 19, 15), True))
        slept = NightSim(self.root / "slept", at(2026, 11, 18, 17, 20),
                         asleep=[(at(2026, 11, 18, 23, 0), at(2026, 11, 19, 19, 15))])
        self.assertEqual(slept.run(), 0)
        self.assertEqual(slept.evenings(), [(WED, at(2026, 11, 18, 17, 30), "ON_TIME"),
                                            (THU, at(2026, 11, 19, 19, 15), "ON_TIME")])
        self.assertEqual(slept.finals(WED), [(at(2026, 11, 19, 19, 35), False, True)])   # Wed's pull after it
        self.assertEqual(slept.finals(THU), overnight(THU))
        self.assertEqual((sim.notes, slept.notes), ([], []))
        # the last pass a process may make has no next pass to leave its pulls to: it makes them (pass cap test)

    def test_C_a_normal_night_is_one_pass_that_ends_after_the_0730_pull(self):
        sim = NightSim(self.root, at(2026, 11, 18, 17, 20))
        self.assertEqual(sim.run(), 0)
        self.assertEqual(sim.evenings(), [(WED, at(2026, 11, 18, 17, 30), "ON_TIME")])
        self.assertEqual(sim.finals(WED), overnight(WED))
        self.assertFalse([m for m in sim.logs if "rolls over" in m])
        self.assertEqual(sim.clock.now(), at(2026, 11, 19, 7, 31))
        self.assertEqual(sim.awake, [(at(2026, 11, 18, 17, 20), True), (at(2026, 11, 19, 7, 31), False),
                                     (at(2026, 11, 19, 7, 31), False)])
        self.assertEqual(len(sim.factory_calls), 7)                            # one wrapper per pull

    def test_D_a_morning_start_after_a_powered_off_evening_records_missed_night_and_waits(self):
        """Wed's 17:20 launch never happened (the Mac was off); a login at Thu 05:00 starts the job (RunAtLoad). It
        keys to Thu, records Wed as MISSED-NIGHT with one notification, and waits for Thu 17:30 without holding the
        Mac awake."""
        for mode, when in (("evening", at(2026, 11, 17, 17, 30)), ("final", at(2026, 11, 18, 1, 30))):
            SB.RunStatus(self.root, D(2026, 11, 17), mode, when).finish(when, "DONE")      # Tuesday: a sampled night
        seed_evening(self.root, D(2026, 11, 17), at(2026, 11, 17, 17, 30))
        sim = NightSim(self.root, at(2026, 11, 19, 5, 0))
        self.assertEqual(sim.run(), 0)
        self.assertEqual(sim.notes, ["MISSED-NIGHT Wed 2026-11-18: no evening sample (detected Thu 11-19 05:00)"])
        sts = SB.statuses(self.root / "2026-11-18")
        self.assertEqual([(s["mode"], s["state"]) for s in sts], [("evening", "MISSED-NIGHT")])
        self.assertIn("no evening sample for 2026-11-18: detected 2026-11-19T05:00:00-05:00", sts[0]["reason"])
        runs = [(r["session"], r["mode"], r["state"]) for r in SB.read_jsonl(self.root / "runs.jsonl")]
        self.assertEqual(runs[2], ("2026-11-18", "evening", "MISSED-NIGHT"))
        self.assertEqual(sim.awake[0], (at(2026, 11, 19, 17, 20), True))       # no assertion while it waited
        self.assertEqual(sim.factory_calls[0], at(2026, 11, 19, 17, 30))      # nothing pulled before the evening
        self.assertEqual(sim.evenings(), [(THU, at(2026, 11, 19, 17, 30), "ON_TIME")])
        self.assertEqual(sim.finals(THU), overnight(THU))
        self.assertEqual(sim.finals(WED), [])                                  # no evening sample: never pulled

    def test_a_full_at_time_not_in_final_at_is_added_and_an_empty_one_means_no_full_pull(self):
        sim = NightSim(self.root, at(2026, 11, 30, 17, 20))
        sim.run("--final-at", "01:30", "--full-at", "05:00")
        self.assertEqual(sim.finals(D(2026, 11, 30)), [(at(2026, 12, 1, 1, 30), False, False),
                                                      (at(2026, 12, 1, 5, 0), True, True)])
        plain = NightSim(self.root / "plain", at(2026, 11, 30, 17, 20))
        plain.run("--full-at", "")
        self.assertEqual([full for _, full, _ in plain.finals(D(2026, 11, 30))], [False] * 6)

    def test_a_retry_after_a_long_sleep_never_samples_a_later_session(self):
        """The 17:30 attempt FAILED, then the Mac slept until Tue 17:00. The collapsed retry would key to Tuesday,
        a session that has completed since, so it is not made; Tuesday's own pass (a roll-over here) samples it at
        17:30, not at 17:00."""
        sim = NightSim(self.root, at(2026, 11, 30, 17, 20), asleep=[(at(2026, 11, 30, 17, 55), at(2026, 12, 1, 17, 0))])
        sim.evening_codes = [1]
        self.assertEqual(sim.run(), 1)                                         # the retry was not made: FAILED stands
        self.assertEqual(sim.evenings(), [(D(2026, 11, 30), at(2026, 11, 30, 17, 30), "FAILED"),
                                          (D(2026, 12, 1), at(2026, 12, 1, 17, 30), "ON_TIME")])
        self.assertTrue(any("evening 2026-11-30: no attempt at Tue 12-01 17:00: 2026-12-01 has completed since" in m
                            for m in sim.logs), sim.logs)
        self.assertEqual(sim.finals(D(2026, 11, 30)), [(at(2026, 12, 1, 17, 0), True, True)])

    def test_a_daytime_start_waits_without_the_power_assertion(self):
        sim = NightSim(self.root, at(2026, 11, 30, 10, 0))
        sim.run()
        self.assertEqual(sim.awake, [(at(2026, 11, 30, 17, 20), True), (at(2026, 12, 1, 7, 31), False),
                                     (at(2026, 12, 1, 7, 31), False)])
        self.assertEqual(sim.evenings(), [(D(2026, 11, 30), at(2026, 11, 30, 17, 30), "ON_TIME")])

    def test_a_process_makes_at_most_seven_passes(self):
        days = [D(2026, 11, 30), D(2026, 12, 1), D(2026, 12, 2), D(2026, 12, 3), D(2026, 12, 4), D(2026, 12, 7),
                D(2026, 12, 8), D(2026, 12, 9)]
        asleep = [(dt.datetime.combine(a, dt.time(23, 0), NY), dt.datetime.combine(b, dt.time(19, 0), NY))
                  for a, b in zip(days, days[1:])]
        sim = NightSim(self.root, at(2026, 11, 30, 17, 20), asleep=asleep)
        self.assertEqual(sim.run(), 0)
        self.assertEqual([e[0] for e in sim.evenings()], days[:7])
        self.assertEqual(sum("rolls over into pass" in m for m in sim.logs), 6)
        self.assertEqual(sum("has made 7 passes: exiting" in m for m in sim.logs), 1)
        self.assertEqual(sim.finals(days[6]), [(dt.datetime.combine(days[7], dt.time(19, 0), NY), True, True)])
        self.assertEqual(sim.awake[-1], (dt.datetime.combine(days[7], dt.time(19, 20), NY), False))
        for a, b in zip(days[:6], days[1:7]):                                  # each earlier session: the next pass's
            self.assertEqual(sim.finals(a), [(dt.datetime.combine(b, dt.time(19, 20), NY), False, True)])  # catch-up
        # F5: the 7th pass exits with Wed 12-09's evening ahead, and says so once
        self.assertEqual(sim.notes, ["night: this process has made 7 passes and exits; Wed 2026-12-09's evening will "
                                     "not be sampled unless the job is started again"])

    def token_until(self, sim: "NightSim", expiry: dt.datetime, unreadable=()) -> None:
        """The token reader of ``sim``: the hours left to ``expiry`` on its clock, or unreadable in those windows."""
        def read():
            now = sim.clock.now()
            if any(a <= now < b for a, b in unreadable):
                return None, None
            return (expiry - now).total_seconds() / 3600.0, SB.iso(expiry)
        sim.token = read

    def test_a_token_that_will_not_outlast_the_night_is_warned_once_and_the_night_still_samples(self):
        """R17: at 17:30 the token has 10 h left, fewer than the 14 h to the 07:30 pull plus 3 h: one warning, and the
        evening is sampled. The warning goes out when the evening sample has finished, so no pull is running (F10).
        The pulls whose check fails each write their FAILED status, notified once (R18)."""
        sim = NightSim(self.root, at(2026, 11, 30, 17, 20))
        self.token_until(sim, at(2026, 12, 1, 3, 30))
        self.assertEqual(sim.run(), 1)
        self.assertEqual(sim.notes, ["the token expires at Tue 12-01 03:30, less than 3 h after tonight's last overnight "
                                     "pull (Tue 12-01 07:30); re-authenticate before then",
                                     "final FAILED: token has 2.5 h left (< 3 h); re-authenticate with setup_auth.py"])
        self.assertEqual(sim.evenings(), [(D(2026, 11, 30), at(2026, 11, 30, 17, 30), "ON_TIME")])
        evening = SB.statuses(self.root / "2026-11-30", "evening")[-1]
        self.assertEqual((evening["state"], evening["finished"]), ("DONE", "2026-11-30T17:50:00-05:00"))
        self.assertEqual(sim.noted[0][0], at(2026, 11, 30, 17, 50))            # after the evening status finished
        self.assertEqual([t for t, *_ in sim.finals(D(2026, 11, 30))], [at(2026, 12, 1, 0, 30)])   # 3.0 h left then
        failed = [(r["mode"], r["started"][11:16]) for r in SB.read_jsonl(self.root / "runs.jsonl") if r["state"] == "FAILED"]
        self.assertEqual(failed, [("final", t) for t in ("01:00", "01:30", "04:30", "06:30", "07:30")])
        calm = NightSim(self.root / "calm", at(2026, 11, 30, 17, 20))
        calm.token = lambda: (20.0, "2026-12-01T13:30:00-05:00")              # 20 h: outlasts 07:30 plus 3 h
        self.assertEqual((calm.run(), calm.notes), (0, []))
        # SF-10 and m50: a token that outlives the 07:30 pull but not by params.token_min_hours (15 and 15.5 h at
        # 17:30, 17 h needed) is warned, and the text says why
        for expiry in (at(2026, 12, 1, 8, 30), at(2026, 12, 1, 9, 0)):
            band = NightSim(self.root / f"band{expiry:%H%M}", at(2026, 11, 30, 17, 20))
            self.token_until(band, expiry)
            band.run()
            self.assertEqual(band.notes[0], f"the token expires at Tue 12-01 {expiry:%H:%M}, less than 3 h after "
                                            f"tonight's last overnight pull (Tue 12-01 07:30); re-authenticate before then")
        self.assertEqual(f"{PARAMS.token_min_hours:g}", "3")

    def test_a_token_unreadable_at_the_first_attempt_is_still_warned_and_a_later_failure_notified(self):
        """F9: the warning came only from the first evening attempt, so a token unreadable at 17:30 was never warned
        about. It now comes from the pass's first attempt whose check passes (the 18:15 retry), once that attempt's
        evening has finished; and a check that passes re-arms the FAILED notification, so 01:00's is sent."""
        sim = NightSim(self.root, at(2026, 11, 30, 17, 20))
        self.token_until(sim, at(2026, 12, 1, 3, 30), unreadable=[(at(2026, 11, 30, 17, 29), at(2026, 11, 30, 17, 31))])
        self.assertEqual(sim.run(), 1)
        self.assertEqual(sim.evenings(), [(D(2026, 11, 30), at(2026, 11, 30, 18, 15), "ON_TIME")])
        self.assertEqual(sim.noted, [
            (at(2026, 11, 30, 17, 30), "evening FAILED: token unreadable; re-authenticate with setup_auth.py"),
            (at(2026, 11, 30, 18, 35), "the token expires at Tue 12-01 03:30, less than 3 h after tonight's last "
                                       "overnight pull (Tue 12-01 07:30); re-authenticate before then"),
            (at(2026, 12, 1, 1, 0), "final FAILED: token has 2.5 h left (< 3 h); re-authenticate with setup_auth.py")])

    def test_a_pass_keyed_to_a_complete_night_makes_no_attempt_no_pull_and_no_assertion(self):
        """F6: a weekday-holiday launch (Thanksgiving Thu 17:20) or a weekend login (Sat 10:00) keys to the previous
        session, whose night is complete: 'nothing left', no factory call, no assertion, no new status. Before, it
        made a SKIPPED evening attempt and a collapsed full re-pull of every name."""
        for first, again in ((at(2026, 11, 25, 17, 20), at(2026, 11, 26, 17, 20)),
                             (at(2026, 11, 20, 17, 20), at(2026, 11, 21, 10, 0))):
            root, s = self.root / f"{first:%m%d}", first.date()
            self.assertEqual(NightSim(root, first).run(), 0)
            before = sorted(str(p.relative_to(root)) for p in root.rglob("status_*.json"))
            self.assertEqual(len(before), 7)                                   # an evening and six overnight pulls
            sim = NightSim(root, again)
            self.assertEqual(sim.run(), 0)
            self.assertEqual((sim.factory_calls, sim.events, sim.notes), ([], [], []), again)
            self.assertFalse([on for _, on in sim.awake if on], again)         # the assertion was never taken
            self.assertEqual(sorted(str(p.relative_to(root)) for p in root.rglob("status_*.json")), before)
            self.assertTrue(any(f"nothing left for {s}" in m for m in sim.logs), sim.logs)

    def test_an_evening_is_never_filed_under_a_session_that_closed_while_the_wrapper_was_built(self):
        """F11: the pass keyed to Monday wakes at Tue 15:59:59, before Tuesday's close, and builds the wrapper (2 s).
        run_evening keys itself again, so it would file an ON_TIME evening for Tuesday at its 16:00 close; the
        attempt re-checks the session once the wrapper is built and is not made. (A FAILED 17:30 attempt whose
        retry wakes at Tue 15:59:59 is past its evening window: no retry at all, F2.)"""
        sim = NightSim(self.root, at(2026, 11, 30, 17, 20), asleep=[(at(2026, 11, 30, 17, 25), at(2026, 12, 1, 15, 59, 59))])

        def slow_factory():
            sim.factory_calls.append(sim.clock.now())
            sim.clock.t += dt.timedelta(seconds=2)
            return SB.MarketData(lambda *a: [], lambda *a: [], lambda *a: {})
        sim.factory = slow_factory
        self.assertEqual(sim.run(), 0)
        self.assertEqual(sim.evenings(), [])                                   # nothing filed under 2026-12-01
        self.assertFalse((self.root / "2026-12-01").exists())
        self.assertTrue(any("evening 2026-11-30: no attempt at Tue 12-01 16:00:01: 2026-12-01 completed while the "
                            "wrapper was built; nothing written" in m for m in sim.logs), sim.logs)
        retry = NightSim(self.root / "retry", at(2026, 11, 30, 17, 20),
                         asleep=[(at(2026, 11, 30, 17, 55), at(2026, 12, 1, 15, 59, 59))])
        retry.evening_codes = [1]
        self.assertEqual(retry.run(), 1)
        self.assertEqual(retry.evenings(), [(D(2026, 11, 30), at(2026, 11, 30, 17, 30), "FAILED")])
        self.assertTrue(any("evening 2026-11-30: no retry at Tue 12-01 15:59: its evening window has passed" in m
                            for m in retry.logs), retry.logs)


class RealNight:
    """main() with the REAL run_evening and run_final on scripted market data (FakeSchwab), a moving clock (a Mac
    asleep in each ``asleep`` window, its process killed at ``kill``: Killed) and the tests' directory text;
    ``fakes`` are handed out one per factory call (an exception instance is raised instead). The notifier and the
    factory calls are recorded; there is no power assertion. No network."""

    def __init__(self, root: Path, start: dt.datetime, fakes, asleep=(), kill=None):
        self.root, self.fakes, self.made, self.notes = Path(root), list(fakes), [], []
        self.clock = NightClock(start, asleep, kill)

    def factory(self):
        self.made.append(self.clock.now())
        f = self.fakes.pop(0)
        if isinstance(f, Exception):
            raise f
        return f.md

    def run(self, *argv) -> int:
        with mock.patch.object(SB, "now_et", self.clock.now), mock.patch.object(SB.time, "sleep", self.clock.sleep), \
                mock.patch.object(SB, "log_line", lambda m: None), \
                mock.patch.object(SB, "fetch_directory_http", fetch_directory):
            return SB.main([*argv, "--root", str(self.root)], market_data=self.factory,
                           token_hours=lambda: (150.0, "2026-12-31T12:00:00-05:00"),
                           notify=lambda t, m: self.notes.append(m))

    def runs(self) -> list[tuple]:
        return [(r["mode"], r["state"], r["started"][11:16]) for r in SB.read_jsonl(self.root / "runs.jsonl")]


class NightRetries(TempRoot):
    """R5 (critic: night mode made one evening attempt) and R16, on the real runs: the evening is retried at 18:15
    and 19:00 while FAILED or INCOMPLETE and stops at the first DONE; only the last attempt and the last overnight
    pull notify an INCOMPLETE; night mode returns the night's outcome (the last evening attempt and the last
    overnight pull), not the worst of every run."""

    S = D(2026, 11, 30)

    def test_a_failed_evening_is_retried_at_1815_and_the_night_returns_its_outcome(self):
        fs = [FakeSchwab(self.S) for _ in range(7)]
        night = RealNight(self.root, at(2026, 11, 30, 17, 20), [RuntimeError("HTTP 503 from the token endpoint")] + fs)
        self.assertEqual(night.run("night"), 0)                                # the 18:15 retry replaced the failure
        self.assertEqual(night.runs(), [("evening", "FAILED", "17:30"), ("evening", "DONE", "18:15")] +
                         [("final", "DONE", t) for t in ("00:30", "01:00", "01:30", "04:30", "06:30", "07:30")])
        self.assertEqual([f"{t:%H:%M}" for t in night.made],
                         ["17:30", "18:15", "00:30", "01:00", "01:30", "04:30", "06:30", "07:30"])
        self.assertEqual(len(night.notes), 1)
        self.assertTrue(night.notes[0].startswith("evening FAILED: the market-data wrapper could not be built: "
                                                  "RuntimeError: HTTP 503"), night.notes)
        self.assertEqual([len(f.calls["daily"]) for f in fs[1:]], [13, 0, 0, 0, 13, 0])   # 06:30 re-pulls every symbol

    def test_an_incomplete_evening_is_retried_quietly_and_stops_at_the_first_done(self):
        fs = [FakeSchwab(self.S, truncate={"SPY": 4})] + [FakeSchwab(self.S) for _ in range(7)]
        night = RealNight(self.root, at(2026, 11, 30, 17, 20), fs)
        self.assertEqual(night.run("night"), 0)                                # the 18:15 retry was DONE
        self.assertEqual(night.runs()[:3], [("evening", "INCOMPLETE", "17:30"), ("evening", "DONE", "18:15"),
                                            ("final", "DONE", "00:30")])       # no 19:00 attempt
        self.assertEqual([c[0] for c in fs[1].calls["daily"]], ["SPY"])        # the re-run pulled only SPY
        self.assertEqual(night.notes, [])                                       # a retry was left: quiet

    def test_an_expected_incomplete_0030_pull_leaves_a_complete_night_at_0(self):
        """Finals roll out around midnight, so a 00:30 pull that finds names not yet final is expected: the outcome
        counts the last overnight pull, and only the last one notifies an INCOMPLETE."""
        fs = [FakeSchwab(self.S), FakeSchwab(self.S, final_ready=False)] + [FakeSchwab(self.S) for _ in range(5)]
        night = RealNight(self.root, at(2026, 11, 30, 17, 20), fs)
        self.assertEqual(night.run("night"), 0)
        self.assertEqual([r[:2] for r in night.runs()],
                         [("evening", "DONE"), ("final", "INCOMPLETE")] + [("final", "DONE")] * 5)
        self.assertEqual(night.notes, [])

    def test_an_evening_incomplete_at_every_attempt_and_its_pulls_notify_once_each(self):
        fs = [FakeSchwab(self.S, truncate={"SPY": -1}) for _ in range(9)]
        night = RealNight(self.root, at(2026, 11, 30, 17, 20), fs)
        self.assertEqual(night.run("night"), 4)
        self.assertEqual([r[:2] for r in night.runs()], [("evening", "INCOMPLETE")] * 3 + [("final", "INCOMPLETE")] * 6)
        self.assertEqual([r[2] for r in night.runs()[:3]], ["17:30", "18:15", "19:00"])
        self.assertEqual(night.notes, ["evening 2026-11-30: INCOMPLETE (0 incomplete; SPY has no bar)",
                                       "final 2026-11-30: INCOMPLETE, 0 names not final, SPY not final"])

    def test_an_incomplete_evening_whose_retries_are_not_made_is_notified_once(self):
        """F2: SPY has no bar at 17:30 (INCOMPLETE, quiet: retries are left), then the Mac sleeps from 17:57. Woken Tue
        07:00, the collapsed retry is past the evening window; woken Tue 16:30, Tuesday has completed. Neither retry
        is made, the night exits 4, and one notification says the evening stayed INCOMPLETE."""
        for wake, pulls in ((at(2026, 12, 1, 7, 0), 2), (at(2026, 12, 1, 16, 30), 1)):
            root = self.root / f"{wake:%H%M}"
            fs = [FakeSchwab(self.S, truncate={"SPY": 4})] + [FakeSchwab(self.S) for _ in range(pulls)]
            night = RealNight(root, at(2026, 11, 30, 17, 20), fs, asleep=[(at(2026, 11, 30, 17, 57), wake)])
            self.assertEqual(night.run("night"), 4, wake)
            self.assertEqual(night.notes, ["evening 2026-11-30: INCOMPLETE, and its retries were not made"], wake)
            runs = night.runs()
            self.assertEqual([r for r in runs if r[0] == "evening"], [("evening", "INCOMPLETE", "17:30")], wake)
            self.assertEqual({r[1] for r in runs if r[0] == "final"}, {"DONE"}, wake)
            self.assertEqual((len(night.made), night.fakes), (1 + pulls, []), wake)  # no wrapper for a retry not made

    def test_a_night_cut_short_after_an_incomplete_pull_is_caught_up_with_only_its_unfinished_names(self):
        """F1: the process dies at Tue 00:55, after the 00:30 pull ended INCOMPLETE (TRX not final yet). An INCOMPLETE
        pull that started before the session's last target (07:30) does not complete the night, so the next start
        (a login at Tue 07:00) makes one catch-up pull, of the unfinished name only."""
        first = RealNight(self.root, at(2026, 11, 30, 17, 20), [FakeSchwab(self.S), FakeSchwab(self.S, truncate={"TRX": -1})],
                          kill=at(2026, 12, 1, 0, 55))
        with self.assertRaises(Killed):
            first.run("night")
        self.assertEqual(first.runs(), [("evening", "DONE", "17:30"), ("final", "INCOMPLETE", "00:30")])
        self.assertEqual(SB.catch_up_sessions(self.root, D(2026, 12, 1)), [self.S])
        catch = FakeSchwab(self.S)
        second = RealNight(self.root, at(2026, 12, 1, 7, 0), [catch], kill=at(2026, 12, 1, 8, 0))
        with self.assertRaises(Killed):
            second.run("night")
        self.assertEqual([c[0] for c in catch.calls["daily"]], ["TRX"])        # one pull, the unfinished name only
        self.assertEqual(second.runs()[2:], [("final", "DONE", "07:00")])
        self.assertEqual((second.made, first.notes, second.notes), ([at(2026, 12, 1, 7, 0)], [], []))
        self.assertEqual(SB.catch_up_sessions(self.root, D(2026, 12, 2)), [])

    def test_a_final_mode_with_several_targets_notifies_an_incomplete_only_on_its_last(self):
        clock = FakeClock(at(2026, 11, 30, 17, 35))
        SB.run_evening(FakeSchwab(self.S).md, root=self.root, clock=clock, sleep=clock.sleep, fetch=fetch_directory, **QUIET)
        night = RealNight(self.root, at(2026, 12, 1, 1, 0), [FakeSchwab(self.S, final_ready=False) for _ in range(2)])
        self.assertEqual(night.run("final", "--session", "2026-11-30", "--at", "01:30,04:30"), 4)
        self.assertEqual([r[:2] for r in night.runs()[1:]], [("final", "INCOMPLETE")] * 2)
        self.assertEqual(night.notes, ["final 2026-11-30: INCOMPLETE, 12 names not final, SPY not final"])


class MissedNights(TempRoot):
    """IF-11 / SVC-07: the missed-night detection (R7), and the critic's catch-up pulls (R8)."""

    def mark(self, s: dt.date, *runs) -> None:
        """Finished statuses for session ``s``, one per (mode, state); state None leaves a run STARTED (it died). An
        evening marked DONE or INCOMPLETE also leaves what a real one does: candidates.json and a usable row."""
        for i, (mode, state) in enumerate(runs):
            when = dt.datetime.combine(s, dt.time(17, 30), NY) + dt.timedelta(minutes=i)
            st = SB.RunStatus(self.root, s, mode, when)
            if state:
                st.finish(when, state)
            if mode == "evening" and state in ("DONE", "INCOMPLETE"):
                seed_evening(self.root, s, when)

    def test_sessions_without_an_evening_sample_are_flagged_once_with_one_notification(self):
        mon, tue, wed, thu, fri = D(2026, 11, 30), D(2026, 12, 1), D(2026, 12, 2), D(2026, 12, 3), D(2026, 12, 4)
        self.mark(mon, ("evening", "DONE"), ("final", "DONE"))
        self.mark(wed, ("evening", "FAILED"))                                  # failed with no usable row: missed
        self.mark(thu, ("evening", "FAILED"))                                  # failed, but its rows are usable
        Night(self.root, thu, ["X"]).evening("X", flat_hist(thu)[-4:] + [cdl(thu, "provisional", 20, 20.5, 19.5, 20, 1)],
                                             at(2026, 12, 3, 17, 31))
        notes = []
        got = SB.record_missed(self.root, fri, at(2026, 12, 4, 5, 0), lambda t, m: notes.append(m), log=lambda m: None)
        self.assertEqual(got, [tue, wed])
        self.assertEqual(notes, ["MISSED-NIGHT Tue 2026-12-01, Wed 2026-12-02: no evening sample (detected Fri 12-04 05:00)"])
        for s in (tue, wed):
            st = [x for x in SB.statuses(self.root / s.isoformat()) if x["state"] == "MISSED-NIGHT"]
            self.assertEqual([x["mode"] for x in st], ["evening"])
            self.assertEqual(st[0]["reason"], f"no evening sample for {s}: detected 2026-12-04T05:00:00-05:00 by the run "
                                              f"for 2026-12-04")
        runs = [r["session"] for r in SB.read_jsonl(self.root / "runs.jsonl") if r["state"] == "MISSED-NIGHT"]
        self.assertEqual(runs, ["2026-12-01", "2026-12-02"])
        self.assertEqual(SB.record_missed(self.root, fri, at(2026, 12, 4, 17, 20), lambda t, m: notes.append(m),
                                          log=lambda m: None), [])
        rc = SB.run_final(SB.MarketData(lambda *a: [], lambda *a: [], lambda *a: {}), root=self.root, session=tue,
                          clock=lambda: at(2026, 12, 4, 6, 0), sleep=lambda s: None,
                          notify=lambda t, m: notes.append(m), **QUIET)
        self.assertEqual((rc, len(notes)), (3, 1))                             # flagged and notified once, any mode

    def test_nothing_is_flagged_before_the_sampler_writes_a_status_and_legacy_folders_are_ignored(self):
        notes = []

        def note(t, m):
            notes.append(m)
        self.assertEqual(SB.record_missed(self.root, D(2026, 12, 4), at(2026, 12, 4, 5, 0), note, log=lambda m: None), [])
        legacy = self.root / "2026-11-11"                                      # night 1: rows, no status file
        legacy.mkdir()
        (legacy / "evening_1755.jsonl").write_text("")
        (legacy / "candidates.json").write_text("{}")                          # the real night-1 layout (m19)
        sat = D(2026, 11, 28)                                                  # a status, but not a session
        SB.RunStatus(self.root, sat, "final", at(2026, 11, 28, 5, 0)).finish(at(2026, 11, 28, 5, 0), "MISSED-NIGHT")
        (self.root / "notes").mkdir()
        self.assertEqual(SB.sampled_sessions(self.root), [])
        self.assertEqual(SB.record_missed(self.root, D(2026, 12, 4), at(2026, 12, 4, 5, 0), note, log=lambda m: None), [])
        self.assertEqual(notes, [])

    def test_the_window_is_the_last_ten_sessions_before_upto(self):
        self.mark(D(2026, 11, 2), ("evening", "DONE"), ("final", "DONE"))
        notes = []
        got = SB.record_missed(self.root, D(2026, 12, 1), at(2026, 12, 1, 5, 0), lambda t, m: notes.append(m),
                               log=lambda m: None)
        self.assertEqual(got, SB.sessions_between(D(2026, 11, 2), D(2026, 11, 30))[-10:])
        self.assertEqual((len(got), got[0], got[-1]), (10, D(2026, 11, 16), D(2026, 11, 30)))
        self.assertNotIn(D(2026, 11, 26), got)                                 # Thanksgiving is no session
        self.assertEqual(len(notes), 1)

    def test_catch_up_finds_evenings_whose_overnight_pulls_never_completed(self):
        mon, tue, wed, thu = D(2026, 11, 30), D(2026, 12, 1), D(2026, 12, 2), D(2026, 12, 3)
        self.mark(mon, ("evening", "DONE"), ("final", "FAILED"))                # every pull's token check failed
        self.mark(tue, ("evening", "INCOMPLETE"), ("final", "INCOMPLETE"))     # INCOMPLETE at 17:31, before 07:30
        self.mark(wed, ("evening", "DONE"), ("final", None))                   # its process died mid-pull
        self.mark(thu, ("final", "MISSED-NIGHT"))                              # no evening sample
        self.assertEqual(SB.catch_up_sessions(self.root, D(2026, 12, 4)), [mon, tue, wed])
        self.assertEqual(SB.catch_up_sessions(self.root, wed), [mon, tue])     # the window excludes upto

    def test_catch_up_finds_a_night_cut_short_after_an_incomplete_pull(self):
        """F1: an INCOMPLETE final pull completes the night only when it started at or after the session's last
        target (default 07:30 the next day; night_pass passes its own schedule's). FAILED, SKIPPED and MISSED-NIGHT
        final statuses never complete it, so a token that expired after the 00:30 pull does not strand the night."""
        s, upto = D(2026, 11, 30), D(2026, 12, 1)
        failed_after = [("FAILED", hm) for hm in ((1, 0), (1, 30), (4, 30), (6, 30), (7, 30))]
        for i, (finals, want) in enumerate((([("INCOMPLETE", (0, 30))], [s]),
                                            ([("INCOMPLETE", (7, 30))], []),
                                            ([("INCOMPLETE", (0, 30))] + failed_after, [s]),
                                            ([("SKIPPED", (7, 30)), ("FAILED", (7, 31))], [s]),
                                            ([("INCOMPLETE", (0, 30)), ("DONE", (1, 0))], []))):
            root = self.root / str(i)
            ev = at(2026, 11, 30, 17, 30)
            SB.RunStatus(root, s, "evening", ev).finish(at(2026, 11, 30, 17, 50), "DONE")
            seed_evening(root, s, ev)
            for state, (h, m) in finals:
                SB.RunStatus(root, s, "final", at(2026, 12, 1, h, m)).finish(at(2026, 12, 1, h, m), state)
            self.assertEqual(SB.catch_up_sessions(root, upto), want, finals)
        late = lambda x: at(2026, 12, 1, 8, 0)                                 # noqa: E731  a schedule ending 08:00
        self.assertEqual(SB.catch_up_sessions(self.root / "1", upto, last_target=late), [s])   # 07:30 is before it
        self.assertEqual(SB.catch_up_sessions(self.root / "0", upto, last_target=lambda x: None), [])   # no schedule

    def test_an_incomplete_evening_without_a_usable_row_is_no_sample(self):
        """F13: an evening status is not a sample. An INCOMPLETE evening with no usable row is MISSED-NIGHT to
        run_final, so the catch-up (and the missed-night detection's 'sampled' test) use run_final's own rule."""
        mon = D(2026, 11, 30)
        SB.RunStatus(self.root, mon, "evening", at(2026, 11, 30, 17, 30)).finish(at(2026, 11, 30, 17, 50), "INCOMPLETE")
        SB.RunStatus(self.root, mon, "final", at(2026, 12, 1, 0, 30)).finish(at(2026, 12, 1, 0, 30), "MISSED-NIGHT")
        self.assertFalse(SB._evening_usable(self.root / mon.isoformat()))
        self.assertEqual(SB.catch_up_sessions(self.root, D(2026, 12, 2)), [])
        self.assertEqual(SB.record_missed(self.root, D(2026, 12, 2), at(2026, 12, 2, 5, 0), None, log=lambda m: None),
                         [D(2026, 12, 1)])                                     # Monday is flagged already, Tuesday now

    def test_a_night_pass_records_the_missed_nights_then_makes_one_catch_up_pull_each(self):
        mon = D(2026, 11, 30)
        self.mark(mon, ("evening", "DONE"), ("final", "FAILED"))
        sim = NightSim(self.root, at(2026, 12, 3, 10, 0))                      # Tue and Wed: the Mac was off
        sim.run()
        self.assertEqual(sim.notes, ["MISSED-NIGHT Tue 2026-12-01, Wed 2026-12-02: no evening sample "
                                     "(detected Thu 12-03 10:00)"])
        self.assertEqual(sim.finals(mon), [(at(2026, 12, 3, 10, 0), False, True)])   # one, not full, INCOMPLETE notified
        self.assertTrue(any("catch-up final pull for 2026-11-30" in m for m in sim.logs))
        self.assertEqual(sim.finals(D(2026, 12, 1)) + sim.finals(D(2026, 12, 2)), [])
        self.assertEqual((sim.factory_calls[0], sim.awake[0]), (at(2026, 12, 3, 10, 0), (at(2026, 12, 3, 17, 20), True)))
        self.assertEqual(sim.evenings(), [(D(2026, 12, 3), at(2026, 12, 3, 17, 30), "ON_TIME")])


class CommandLine(MainHarness, TempRoot):
    """R11 (safety S9: --session), R12 (the last-resort handler) and R13 (a calendar that has run out)."""

    def test_final_session_is_refused_before_anything_is_written(self):
        for bad, why in (("2025-06-02", "outside the NYSE calendar carried here"),
                         ("2026-10-29", "outside the NYSE calendar carried here"),
                         ("2027-04-01", "outside the NYSE calendar carried here"),
                         ("2026-11-26", "not an NYSE session"), ("2026-12-05", "not an NYSE session"),
                         ("2026-12-01", "later than the last completed session, 2026-11-30"),
                         ("11/30/2026", "not an ISO date")):
            root, notes, logs = self.root / "r", [], []
            rc, seen = self.run_main(["final", "--session", bad, "--root", str(root)], notes=notes, logs=logs,
                                     market_data=self.STUB)
            self.assertEqual((rc, seen, notes), (2, [], []), bad)
            self.assertFalse(root.exists(), bad)                               # no folder, no status
            self.assertTrue(any(why in m for m in logs), (bad, logs))
            rc, _ = self.run_main(["final", "--session", bad, "--root", str(root)])     # without the runner: 2 as well
            self.assertEqual(rc, 2, bad)
            self.assertFalse(root.exists(), bad)
        rc, seen = self.run_main(["final", "--session", "2026-11-30", "--root", str(self.root / "ok")],
                                 market_data=self.STUB)
        self.assertEqual((rc, [k for k, _ in seen]), (0, ["final"]))

    def test_an_unexpected_error_is_logged_notified_and_returns_1_and_the_assertion_is_released(self):
        def boom(md, **kw):
            raise ValueError("bad candle")
        for mode in ("evening", "night"):
            notes, logs, awake = [], [], []
            clock = MovingClock(at(2026, 11, 30, 17, 35))
            with mock.patch.object(SB, "now_et", clock.now), mock.patch.object(SB.time, "sleep", clock.sleep), \
                    mock.patch.object(SB, "log_line", logs.append), mock.patch.object(SB, "run_evening", boom):
                rc = SB.main([mode, "--root", str(self.root / mode)], market_data=self.STUB,
                             token_hours=_token_ok, notify=lambda t, m: notes.append(m),
                             awake=lambda on: awake.append(on))
            self.assertEqual((rc, notes), (1, [f"{mode} crashed: ValueError"]), mode)
            self.assertTrue(any(f"{mode}: crashed: ValueError: bad candle" in m for m in logs), logs)
            if mode == "night":
                self.assertEqual(awake, [True, False])                         # released on the way out

    def test_the_evening_and_final_modes_run_the_missed_night_detection_first(self):
        """R7: every network run calls it first: evening with upto = the session it keys to, final with its own."""
        for root in (self.root / "e", self.root / "f"):
            SB.RunStatus(root, D(2026, 11, 30), "evening", at(2026, 11, 30, 17, 30)).finish(at(2026, 11, 30, 17, 50), "DONE")
            seed_evening(root, D(2026, 11, 30), at(2026, 11, 30, 17, 30))
        notes = []
        rc, seen = self.run_main(["evening", "--root", str(self.root / "e")], clock=MovingClock(at(2026, 12, 3, 17, 35)),
                                 notes=notes, market_data=self.STUB)
        self.assertEqual((rc, [k for k, _ in seen]), (0, ["evening"]))
        self.assertEqual(notes, ["MISSED-NIGHT Tue 2026-12-01, Wed 2026-12-02: no evening sample (detected Thu 12-03 17:35)"])
        notes.clear()
        rc, seen = self.run_main(["final", "--session", "2026-12-02", "--root", str(self.root / "f")],
                                 clock=MovingClock(at(2026, 12, 3, 17, 35)), notes=notes, market_data=self.STUB)
        self.assertEqual((rc, [k for k, _ in seen]), (0, ["final"]))
        self.assertEqual(notes, ["MISSED-NIGHT Tue 2026-12-01: no evening sample (detected Thu 12-03 17:35)"])

    def test_a_failing_notifier_or_a_full_disk_never_stops_an_alert_path(self):
        def broken(title, message):
            raise OSError("no GUI session")
        logs = []
        clock = FakeClock(at(2026, 11, 30, 17, 35))
        rc = SB.run_evening(ManyNames(self.root, D(2026, 11, 30), n=10, empty=("SPY",)).md, root=self.root, clock=clock,
                            sleep=clock.sleep, fetch=fetch_directory, notify=broken, log=logs.append)
        self.assertEqual((rc, SB.statuses(self.root / "2026-11-30", "evening")[-1]["state"]), (4, "INCOMPLETE"))
        self.assertTrue(any(m.startswith("notification failed (OSError: no GUI session)") for m in logs), logs)
        notes = []
        with full_disk(allow_first_status=False):                              # nothing can be written at all
            rc, _ = self.run_main(["evening", "--root", str(self.root / "full")], notes=notes, logs=logs)
        self.assertEqual((rc, [n.split(":")[0] for n in notes]), (1, ["evening FAILED"]))     # notified first
        self.assertTrue(any("the FAILED status could not be written (OSError" in m for m in logs), logs)

    def test_a_log_that_cannot_be_written_never_stops_an_alert(self):
        """F7: launchd's StandardOutPath is a file on the same disk, so on a truly full disk the log fails too. With
        the real log_line and a stdout that raises ENOSPC, the night still sends every alert and returns 1; nothing
        escapes main (the alert paths log before they notify)."""
        class FullStdout(io.StringIO):
            def write(self, s):
                raise OSError(errno.ENOSPC, "No space left on device")

            def flush(self):
                raise OSError(errno.ENOSPC, "No space left on device")
        notes, clock = [], MovingClock(at(2026, 11, 30, 17, 20))
        with mock.patch.object(SB, "now_et", clock.now), mock.patch.object(SB.time, "sleep", clock.sleep), \
                mock.patch.object(sys, "stdout", FullStdout()), full_disk(allow_first_status=False):
            rc = SB.main(["night", "--root", str(self.root)], market_data=lambda: FakeSchwab(D(2026, 11, 30)).md,
                         token_hours=_token_ok, notify=lambda t, m: notes.append(m))
        self.assertEqual(rc, 1)
        self.assertEqual(notes, ["evening 2026-11-30 FAILED: OSError"] * 3 + ["MISSED-NIGHT 2026-11-30: no evening sample"])
        with mock.patch("builtins.print", side_effect=OSError(errno.ENOSPC, "No space left on device")):
            SB.log_line("dropped, never raised")

    def test_a_calendar_that_has_run_out_is_notified_without_a_traceback(self):
        for mode in ("evening", "final", "night"):
            notes, root = [], self.root / mode
            rc, seen = self.run_main([mode, "--root", str(root)], clock=MovingClock(at(2027, 4, 1, 17, 20)), notes=notes,
                                     market_data=self.STUB)
            self.assertEqual((rc, seen), (1, []), mode)
            self.assertEqual(notes, [f"{mode} FAILED: the sampler's calendar ends 2027-03-31: extend it before sampling"])
            self.assertFalse(root.exists(), mode)
        rc, _ = self.run_main(["night", "--root", str(self.root / "x")], clock=MovingClock(at(2027, 4, 1, 17, 20)))
        self.assertEqual(rc, 1)                                                # without the runner too


class Docstrings(unittest.TestCase):
    """R15: what the docstrings say is what the code does (review SVC-17, IF-13, S4, S8, SVC-07)."""

    @staticmethod
    def norm(text: str) -> str:
        return " ".join((text or "").split())

    def test_the_sampler_comparison_and_runner_docstrings(self):
        sb, cb, pr = self.norm(SB.__doc__), self.norm(CB.__doc__), self.norm(PR.__doc__)
        self.assertIn("(t-4..t: the basis check reads t-1..t-4)", sb)
        self.assertIn("ALREADY_FINAL (a late sample: kept out of every flip denominator; counted in the finality "
                      "coverage)", cb)
        self.assertIn("three closures over the runner's client: the client is not an attribute of the wrapper, and the "
                      "contract tests forbid reaching it through the closures", self.norm(SB.MarketData.__doc__))
        for text in (sb, SB.FUND_NAMED_BDCS["MSIF"], SB.directory_decision(dict(
                symbol="ARCC", nasdaq_symbol="ARCC", name="Ares Capital Corporation - Closed End Fund", etf="N", test="N",
                source="nasdaqlisted.txt", exchange="Q", financial_status="N"))[1]):
            self.assertIn("BDCs are in the universe by the owner's ruling of 2026-11-12 (spec 3.1), known by their SEC 814- "
                          "file number at B3/B4, not by name", text)
        for text in (sb, cb):
            self.assertNotIn("21:00", text)
            self.assertIn("after 19:30 ET", text)
        for phrase in ("--final-at 00:30,01:00,01:30,04:30,06:30,07:30", "--full-at 06:30", "RunAtLoad",
                       "the runner holds the idle-sleep assertion", "from the missed-night detection",
                       '"evening <session>: INCOMPLETE, and its retries were not made"', "'nothing left'",
                       "A daytime start makes the catch-up pulls first"):
            self.assertIn(phrase, sb)
        for phrase in ("PRE_GO_LIVE_LOOKBACK_RULED = True below", "the owner's ruling of 2026-11-12"):
            self.assertIn(phrase, cb)
        for phrase in ("schwab-py rewrites the token file on each access-token refresh",
                       "that is the sampler's one write outside logs/phase2/",
                       "The client is rebuilt for every pull, so a re-authentication between pulls is picked up and "
                       "never reverted", "Do not re-authenticate while a pull is running (about 20 minutes)",
                       "--full-at 06:30", "RunAtLoad", "this runner holds the power assertion"):
            self.assertIn(phrase, pr)


# =========================================================================================================
# 5. The comparison: one night, every counter
# =========================================================================================================

class NightA(TempRoot):
    def setUp(self):
        super().setUp()
        build_night_a(self.root)
        self.n = CB.analyze_night(self.root / NIGHT_A.isoformat())
        self.t = self.n["tally"]

    def test_fixture_is_what_it_claims(self):
        h, f = shelf_hist(NIGHT_A), CASES_A["M1SIG"][3]
        self.assertEqual(CB.atr14(h), technicals.compute_levels([CB._tl(c) for c in h], last=21.0)["atr14"])
        self.assertTrue(CB.evaluate(h, f, set())["m1"]["touch"])

    def test_state_classes_and_denominators(self):
        n, t = self.n, self.t
        self.assertEqual(n["state"], "OK")
        self.assertEqual(n["late_reasons"], [])
        self.assertEqual(t["universe"], 16)
        self.assertEqual(t["pairs"], 14)                                       # TRUNC and NOTFIN are not compared
        self.assertEqual(t["fi_FINAL"], 14)
        self.assertEqual(t["fi_TRUNCATED"], 1)
        self.assertEqual(t["fi_NOT_FINAL"], 1)
        self.assertEqual(n["names_count"]["final_truncated"], 1)
        self.assertEqual(n["names"]["not_final_yet"], ["NOTFIN"])
        self.assertEqual(sorted(n["names"]["truncated_response"]), ["RETRY", "TRUNC"])
        self.assertEqual(t["truncated_responses"], 2)
        self.assertEqual(t["final_from_earlier_pull"], 1)                      # ERRL: the 06:30 error lost to 01:30
        self.assertEqual(t["no_quote_close"], 1)
        self.assertEqual(n["names"]["no_quote_close"], ["NOQ"])
        self.assertEqual(t.get("basis_change", 0), 0)

    def test_bar_level_counters(self):
        t = self.t
        self.assertEqual(t["diff_o"], 2)                                       # M2FLIP, OPENX
        self.assertEqual(t["diff_h"], 2)                                       # TRIG, SUBC
        self.assertEqual(t["diff_l"], 1)                                       # M1FLIP
        self.assertEqual(t["diff_c_candle"], 2)                                # M2FLIP's and SMAX's candle closes
        self.assertEqual(t["diff_c_scan"], 1)                                  # SMAX: quote close vs final close
        self.assertEqual(t["pairs_with_quote_close"], 13)
        self.assertEqual(t["diff_v"], 4)                                       # M2BOTH, TRIG, VOLX, FLAT2
        self.assertEqual(t["trigger_moves"], 1)                                # TRIG moves; SUBC's sub-cent high does not
        self.assertEqual((t.get("open_up", 0), t.get("open_down", 0)), (0, 2))
        self.assertEqual((t["vol_up"], t["vol_down"], t["vol_same"]), (3, 1, 10))
        self.assertEqual((t["quote_open_equal"], t["quote_open_compared"]), (14, 14))

    def test_finality_timeline_flags_a_gate_that_passes_with_names_unfinished(self):
        tl = self.n["timeline"]
        self.assertEqual(len(tl), 2)
        first = tl[0]
        self.assertEqual(first["file"], f"final_{SB.stamp(FINAL_A)}.jsonl")
        self.assertEqual(first["unfinished"], 2)
        self.assertEqual(first["unfinished_by_class"], {SB.TRUNCATED: 1, SB.NOT_FINAL: 1})
        self.assertAlmostEqual(first["coverage"], 14 / 16)
        self.assertFalse(first["gate_99"])
        self.assertTrue(first["spy_final"])

    def test_signal_level_flips(self):
        sig, t = self.n["signals"], self.t
        self.assertTrue(sig["run"], sig.get("reason"))
        self.assertEqual(sig["calendar_source"], "SPY's final bar dates")
        self.assertEqual(t["sig_pairs"], 13)
        self.assertEqual(t["m2_t_gap_flip"], 1)                                # the deliberately flipped M2 gap
        self.assertEqual(t["m2_t_volume_flip"], 1)                             # VOLX
        self.assertEqual(t["m2_flip"], 1)
        self.assertEqual((t["m2_eve"], t["m2_fin"], t["m2_both"], t["m2_either"]), (2, 1, 1, 2))
        self.assertEqual(t["m1_t_touch_flip"], 1)
        self.assertEqual((t["m1_eve"], t["m1_fin"], t["m1_both"], t["m1_flip"]), (1, 2, 1, 1))
        self.assertEqual(t.get("m1_t_valid_setup_flip", 0) + t.get("m1_t_rr_flip", 0) + t.get("m1_t_atr_floor_ok_flip", 0), 0)
        self.assertEqual(t["sma_flip"], 1)                                     # SMAX
        self.assertEqual(t.get("elig_flip", 0), 0)
        self.assertEqual(t.get("knife_flip", 0), 0)

    def test_breadth_both_ways_with_distance_to_fifty(self):
        b = self.n["signals"]["breadth"]
        self.assertEqual((b["evening"]["above"], b["evening"]["eligible"]), (7, 13))
        self.assertEqual((b["final"]["above"], b["final"]["eligible"]), (6, 13))
        self.assertTrue(b["evening"]["gate_open"])
        self.assertFalse(b["final"]["gate_open"])
        self.assertTrue(b["gate_flip"])
        self.assertEqual(b["evening"]["names_to_flip"], 1)
        self.assertEqual(b["final"]["names_to_flip"], 1)
        self.assertEqual(b["missing_final"], 2)                                # TRUNC and NOTFIN
        self.assertAlmostEqual(b["final_low"], 6 / 15)
        self.assertAlmostEqual(b["final_high"], 8 / 15)
        self.assertFalse(b["final_gate_robust"])

    def test_spy_gap_flip(self):
        g = self.n["signals"]["spy_gap"]
        self.assertAlmostEqual(g["evening"], 0.0105)
        self.assertAlmostEqual(g["final"], 0.0095)
        self.assertEqual((g["ok_evening"], g["ok_final"], g["flip"]), (False, True, True))

    def test_order_levels_and_tickets(self):
        t = self.t
        for k in PARAMS.stop_k:
            self.assertEqual(t.get(f"lv_m2_{k}_confirmed"), 1, k)              # M2BOTH: identical O/H/L/C
            self.assertEqual(t.get(f"lv_m2_{k}_disappeared"), 1, k)            # M2FLIP
            self.assertEqual(t.get(f"lv_m1_{k}_confirmed"), 1, k)              # M1SIG
            self.assertEqual(t.get(f"lv_m1_{k}_appeared"), 1, k)               # M1FLIP
            self.assertEqual(t.get(f"lv_m2_{k}_changed", 0) + t.get(f"lv_m1_{k}_changed", 0), 0)
            # breadth closes on the final bars, so every evening ticket disappears with it
            self.assertEqual(t.get(f"tk_m2_{k}_disappeared"), 2, k)
            self.assertEqual(t.get(f"tk_m1_{k}_disappeared"), 1, k)
            self.assertEqual(t.get(f"tk_m1_{k}_confirmed", 0) + t.get(f"tk_m2_{k}_confirmed", 0), 0)

    def test_moved_trigger_changes_the_levels(self):
        lv_a = CB.levels(CB.whole_cent_trigger(20.60), 1.0, 1.5, 19.0)
        lv_b = CB.levels(CB.whole_cent_trigger(20.64), 1.0, 1.5, 19.0)
        self.assertEqual((lv_a["T"], lv_b["T"]), (CB.Decimal("20.61"), CB.Decimal("20.65")))
        self.assertNotEqual(lv_a["P"], lv_b["P"])

    def test_fill_path_counts(self):
        t = self.t
        self.assertEqual(t["fill_names"], 13)
        self.assertEqual(t["fill_identical_bars"], 7)        # all but M2FLIP TRIG SUBC SMAX OPENX M1FLIP (volume is not read)
        expected = Counter_sum([CB.replay_fill_paths(sym, NIGHT_A, *self.bars(sym), 1.0 if CASES_A[sym][0] == "flat" else 0.8,
                                                     F.tier_bps(20e6, PARAMS), hist_for(CASES_A[sym][0], NIGHT_A))["counts"]
                                for sym in ("M2FLIP", "TRIG", "SUBC", "SMAX", "OPENX", "M1FLIP")])
        for k, v in expected.items():
            if k.endswith("changed"):
                self.assertEqual(t.get(f"fill_{k}", 0), v, k)
        self.assertGreater(t["fill_names_changed"], 0)

    def bars(self, sym):
        _, ev, q, fin = CASES_A[sym]
        return dict(ev, c=q), fin

    def test_margins_and_estimates(self):
        rep = CB.build_report(self.root)
        est = {(e["sym"], e["method"], e["side"]): e for e in rep["estimates"]}
        e = est[("M2FLIP", "M2", "evening")]
        self.assertTrue(e["flipped"])
        gap = next(p for p in e["parts"] if p["test"] == "gap")
        self.assertAlmostEqual(gap["margin"], 0.10, places=6)                 # (1.10 - 1.00) / ATR 1.00
        self.assertEqual((gap["x"], gap["n"]), (2, 13))                        # OPENX -0.30 and M2FLIP -0.15 ATR
        self.assertFalse(est[("M2BOTH", "M2", "evening")]["flipped"])
        touch = next(p for p in est[("M1FLIP", "M1", "final")]["parts"] if p["test"] == "touch")
        self.assertAlmostEqual(touch["margin"], (20.0 + 0.25 * 0.8036 - 20.15) / 0.8, places=4)


class Windows(unittest.TestCase):
    """The look-back windows come from params (adv_window, cost_dollar_volume_window); ATR(t-1) is compute_levels'
    own ATR14, the one period params.py does not carry."""

    def test_the_average_volume_and_dollar_volume_windows_come_from_params(self):
        h = flat_hist(NIGHT_A)                                                 # close 20.00, volume 1,000,000
        h[-30] = dict(h[-30], v=31_000_000)                                    # the 30th session back: in the window
        b, prior60 = bar(20.0, 20.4, 19.6, 20.0, 1_000_000), {c["d"] for c in h[-60:]}
        e = CB.evaluate(h, b, prior60)
        self.assertEqual((e["adv30"], e["adv_dollar"]), (2_000_000, 40_000_000))
        narrow = dataclasses.replace(PARAMS, adv_window=20, cost_dollar_volume_window=10)
        with mock.patch.object(CB, "PARAMS", narrow):
            e = CB.evaluate(h, b, prior60)
        self.assertEqual((e["adv30"], e["adv_dollar"]), (1_000_000, 20_000_000))

    def test_atr_at_t_minus_1_is_compute_levels_atr14(self):
        h = flat_hist(NIGHT_A)                                                 # every true range 1.00
        h[-14] = dict(h[-14], h=h[-14]["h"] + 1.4)                             # the 14th range back: 2.40
        want = technicals.compute_levels([CB._tl(c) for c in h], last=21.0)["atr14"]
        self.assertEqual((CB.atr14(h), want), (1.1, 1.1))
        self.assertEqual(CB.ATR_PERIOD, 14)


def Counter_sum(dicts):
    out = {}
    for d in dicts:
        for k, v in d.items():
            out[k] = out.get(k, 0) + v
    return out


class FillPathByHand(unittest.TestCase):
    """OPENX: evening open 20.40, final open 20.10, high 20.90, low 19.95, close 20.50, ATR(t-1) 1.00. Worked
    from spec 3.4: pending triggers T = 19.60..20.60 change when T lies in 19.85..20.40 (12 of 21, each k):
    T in 19.85..20.10 fills at C on the evening bar but at the open on the final bar; T in 20.15..20.40 fills
    at the open on the evening bar but at T intraday on the final bar. Open trades with S in 20.10..20.60 exit
    differently (11 of 21); targets near the open fill at P either way (0 of 21)."""

    def test_openx(self):
        _, ev, q, fin = CASES_A["OPENX"]
        r = CB.replay_fill_paths("OPENX", NIGHT_A, dict(ev, c=q), fin, 1.0, 20.0, flat_hist(NIGHT_A))
        c = r["counts"]
        self.assertEqual((c["pending: orders"], c["pending: changed"]), (63, 36))
        self.assertEqual((c["open, stop near the open: orders"], c["open, stop near the open: changed"]), (21, 11))
        self.assertEqual(c["open, target near the open: orders"], 21)
        self.assertNotIn("open, target near the open: changed", c)
        self.assertEqual(r["kinds"]["pending: entry kind"], 36)

    def test_identical_bars_never_step(self):
        b = bar(20.0, 20.5, 19.5, 20.0, 1)
        with mock.patch.object(F, "step", side_effect=AssertionError("stepped")):
            r = CB.replay_fill_paths("X", NIGHT_A, b, dict(b, v=2), 1.0, 20.0, flat_hist(NIGHT_A))
        self.assertEqual(r["counts"]["identical_bars"], 1)

    def test_sealed_sessions_are_refused_before_any_step(self):
        b = bar(20.0, 20.5, 19.5, 20.0, 1)
        with mock.patch.object(F, "step", side_effect=AssertionError("stepped")):
            with self.assertRaises(RuntimeError):
                CB.replay_fill_paths("X", D(2026, 10, 29), b, dict(b, o=20.1), 1.0, 20.0, flat_hist(D(2026, 10, 29)))


# =========================================================================================================
# 6. Many nights: pooling, LATE, MISSED-NIGHT, NOT SAMPLED, year end, the guard
# =========================================================================================================

class MultiNight(TempRoot):
    def setUp(self):
        super().setUp()
        build_night_a(self.root)                                                           # Mon 11-30, OK
        simple_night(self.root, D(2026, 12, 1), at(2026, 12, 1, 22, 35), at(2026, 12, 2, 1, 30),
                     names=("FLAT1", "FLAT2", "ALRDY"), already_final=("ALRDY",), open_moves=("FLAT1",))   # LATE
        c = self.root / "2026-12-02"                                                        # MISSED-NIGHT
        SB.RunStatus(self.root, D(2026, 12, 2), "final", at(2026, 12, 3, 1, 30)).finish(
            at(2026, 12, 3, 1, 30), "MISSED-NIGHT", reason="no evening sample")
        self.assertTrue(c.exists())
        simple_night(self.root, D(2026, 12, 4), at(2026, 12, 4, 17, 31), at(2026, 12, 5, 1, 30),
                     open_moves=("FLAT2",))                                                 # Fri, OK
        self.rep = CB.build_report(self.root)
        self.by = {n["session"]: n for n in self.rep["nights"]}

    def test_states_and_unsampled_sessions(self):
        self.assertEqual(self.by["2026-11-30"]["state"], "OK")
        self.assertEqual(self.by["2026-12-01"]["state"], "LATE")
        self.assertEqual(self.by["2026-12-02"]["state"], "MISSED-NIGHT")
        self.assertEqual(self.by["2026-12-04"]["state"], "OK")
        self.assertEqual(self.rep["not_sampled"], ["2026-12-03"])
        late = self.by["2026-12-01"]
        self.assertTrue(any("after the 19:30 cutoff" in r for r in late["late_reasons"]))
        self.assertTrue(any("1 evening candle(s) already final" in r for r in late["late_reasons"]))
        self.assertEqual(late["names"]["already_final"], ["ALRDY"])
        self.assertEqual(late["tally"]["pairs"], 2)                            # ALRDY is out of every denominator

    def test_pooling_excludes_late_and_missed_nights(self):
        self.assertEqual(self.rep["contributing"], ["2026-11-30", "2026-12-04"])
        t = self.rep["pooled"]["tally"]
        self.assertEqual(t["pairs"], 14 + 3)
        self.assertEqual(t["diff_o"], 2 + 1)
        rep2 = CB.build_report(self.root, include_late=True)
        self.assertEqual(rep2["contributing"], ["2026-11-30", "2026-12-01", "2026-12-04"])
        self.assertEqual(rep2["pooled"]["tally"]["pairs"], 14 + 2 + 3)
        self.assertEqual(rep2["pooled"]["tally"]["diff_o"], 2 + 1 + 1)

    def test_the_acceptance_bar_is_judged_per_method_over_every_sampled_night(self):
        """The owner's bar (2026-11-12): zero ticket flips on every sampled night, either direction, per method.
        Night A's breadth gate closes on the final bars, so its M1 and M2 tickets disappear: neither is met. The
        LATE night is judged too (it was sampled); the MISSED-NIGHT has no evening sample."""
        acc = self.rep["acceptance"]
        for m, flips in (("m1", 1), ("m2", 2)):
            self.assertFalse(acc[m]["met"], m)
            self.assertEqual(acc[m]["flip_nights"], ["2026-11-30"], m)
            self.assertEqual((acc[m]["nights"], acc[m]["flips"]), (3, flips * len(PARAMS.stop_k)), m)
        text = CB.render(self.rep)
        self.assertIn("M1 acceptance bar (ruled 2026-11-12): not met  (3 ticket flip(s) over 3 sampled night(s); "
                      "ticket flips on 2026-11-30)", text)
        self.assertIn("M2 acceptance bar (ruled 2026-11-12): not met", text)

    def test_the_acceptance_bar_rules(self):
        def night(session, state="OK", run=True, **tally):
            return dict(session=session, state=state, signals=dict(run=run), tally=tally)
        quiet = [night("2026-12-07"), night("2026-12-08", **{"tk_m1_1.5_confirmed": 3, "tk_m2_1.0_confirmed": 1})]
        acc = CB.acceptance(quiet)
        self.assertTrue(acc["m1"]["met"] and acc["m2"]["met"])
        self.assertIsNone(acc["m1"]["reason"])
        for x in ("changed", "disappeared", "appeared"):                  # either direction, any k
            acc = CB.acceptance(quiet + [night("2026-12-09", **{f"tk_m2_2.0_{x}": 1})])
            self.assertTrue(acc["m1"]["met"], x)                            # M1 and M2 are judged separately
            self.assertFalse(acc["m2"]["met"], x)
            self.assertEqual(acc["m2"]["flip_nights"], ["2026-12-09"], x)
        acc = CB.acceptance(quiet + [night("2026-12-09", state="LATE", **{"tk_m1_1.5_changed": 1}),
                                     night("2026-12-10", state="MISSED-NIGHT", run=False)])
        self.assertFalse(acc["m1"]["met"])                                 # a LATE night's flip counts: it was sampled
        self.assertEqual(acc["m1"]["flip_nights"], ["2026-12-09"])
        self.assertTrue(acc["m2"]["met"])                                  # the missed night is not judged
        for bad in (night("2026-12-09", run=False), night("2026-12-09", state="NO-FINAL", run=False)):
            acc = CB.acceptance(quiet + [bad])
            self.assertFalse(acc["m1"]["met"] or acc["m2"]["met"])        # zero flips not shown on that night
            self.assertEqual(acc["m1"]["unjudged"], ["2026-12-09"])
        acc = CB.acceptance([night("2026-12-10", state="MISSED-NIGHT", run=False)])
        self.assertFalse(acc["m1"]["met"] or acc["m2"]["met"])
        self.assertEqual(acc["m1"]["reason"], "no sampled night")

    def test_night_clustered_interval_and_bounds_print(self):
        text = CB.render(self.rep)
        self.assertIn("NOT SAMPLED (calendar sessions without a folder): 2026-12-03", text)
        self.assertIn("MISSED-NIGHT", text)
        self.assertRegex(text, r"\n    open\s+3 of 17 \(")
        self.assertNotIn("CI n/a (1 night)", text.split("BAR LEVEL")[1].split("\n")[1])
        self.assertIn("M2 (bar tests, no event filter): signals evening 2, final 1", text)

    def test_cli_json_and_go_live_cannot_move_earlier(self):
        out = self.root / "report.json"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(CB.main(["--all", "--root", str(self.root), "--json", str(out)]), 0)
            self.assertEqual(CB.main(["--all", "--root", str(self.root), "--go-live", "2026-11-01"]), 2)
            self.assertEqual(CB.main(["--root", str(self.root)]), 2)
        rep = load_json(out)
        self.assertEqual(rep["contributing"], ["2026-11-30", "2026-12-04"])
        self.assertIn("refused", buf.getvalue())


class YearEndAndMerge(TempRoot):
    def test_rows_are_ordered_by_pull_time_not_file_name(self):
        s = D(2026, 12, 31)
        n = Night(self.root, s, ["CCC"])
        h = flat_hist(s)
        n.quote("CCC", 20.0, at(2026, 12, 31, 17, 35))
        n.evening("CCC", h[-4:] + [cdl(s, "provisional", 20.0, 20.5, 19.5, 20.0, 1_000_000)], at(2026, 12, 31, 17, 35),
                  file_stamp="1735")
        # legacy month-day names: sorted by name, the 01-01 file would come first
        n.final("CCC", h + [cdl(s, "provisional", 20.0, 20.5, 19.5, 20.0, 1_000_100)], at(2026, 12, 31, 22, 0),
                file_name="final_1231_2200.jsonl")
        n.final("CCC", h + [cdl(s, "final", 20.0, 20.5, 19.5, 20.0, 1_000_200)], at(2027, 1, 1, 1, 30),
                file_name="final_0101_0130.jsonl")
        night = CB.analyze_night(self.root / "2026-12-31")
        self.assertEqual(night["tally"]["pairs"], 1)
        self.assertEqual([tl["file"] for tl in night["timeline"]], ["final_1231_2200.jsonl", "final_0101_0130.jsonl"])
        self.assertEqual(night["timeline"][-1]["coverage"], 1.0)

    def test_pick_final_keeps_the_best_record(self):
        s = D(2026, 11, 30)
        h = flat_hist(s)
        fin = cdl(s, "final", 20, 20.5, 19.5, 20, 1)
        good = dict(symbol="X", pulled=SB.iso(at(2026, 12, 1, 1, 30)), candles=h + [fin])
        short = dict(symbol="X", pulled=SB.iso(at(2026, 12, 1, 6, 30)), candles=h[-5:] + [fin])
        err = dict(symbol="X", pulled=SB.iso(at(2026, 12, 1, 7, 30)), error="HTTP 500")
        trunc = dict(symbol="X", pulled=SB.iso(at(2026, 12, 1, 7, 31)), candles=[fin])
        got = CB.pick_final([good, short, err, trunc], s.isoformat())
        self.assertEqual((got["cls"], len(got["hist"]), got["from_earlier"]), (SB.FINAL, 130, True))
        revised = dict(good, pulled=SB.iso(at(2026, 12, 1, 6, 0)), candles=h + [dict(fin, v=2)])
        self.assertTrue(CB.pick_final([good, revised], s.isoformat())["revised"])

    def test_basis_check(self):
        s = D(2026, 11, 30)
        h = flat_hist(s, n=6)
        self.assertEqual(CB.basis_check(h[-4:], h), ("ok", False))
        self.assertEqual(CB.basis_check([dict(c, v=c["v"] + 1) for c in h[-4:]], h), ("ok", True))
        split = [dict(c, o=c["o"] * 2, h=c["h"] * 2, l=c["l"] * 2, c=c["c"] * 2) for c in h[-4:]]
        self.assertEqual(CB.basis_check(split, h)[0], "split-like x0.5000")
        shifted = [dict(c, o=c["o"] + 1.6, h=c["h"] + 1.6, l=c["l"] + 1.6, c=c["c"] + 1.6) for c in h[-4:]]
        self.assertEqual(CB.basis_check(shifted, h)[0], "shift $-1.60")
        self.assertEqual(CB.basis_check([], h)[0], "unchecked")


class LookbackGuard(TempRoot):
    def test_a_pre_go_live_night_gets_its_signal_level_by_the_owners_ruling(self):
        """The owner's ruling of 2026-11-12 (spec 3.7): sealed bars may be read as look-back to compute indicators
        for any session after 2026-10-30, and signal-level flip comparisons resume. With the source's constants
        (go-live unset, so every night is pre-go-live; the ruling recorded) a pre-go-live night whose look-back
        reaches into the sealed window gets its signal level."""
        simple_night(self.root, D(2026, 11, 18), at(2026, 11, 18, 17, 30), at(2026, 11, 19, 1, 30), open_moves=("FLAT1",))
        with mock.patch.object(CB, "GO_LIVE_ACTUAL", None), \
                mock.patch.object(technicals, "compute_levels", wraps=technicals.compute_levels) as cl:
            n = CB.analyze_night(self.root / "2026-11-18")
        self.assertIs(CB.PRE_GO_LIVE_LOOKBACK_RULED, True)
        self.assertTrue(n["signals"]["run"], n["signals"].get("reason"))
        self.assertGreater(cl.call_count, 0)                                  # the look-back was read
        self.assertGreater(n["tally"]["fill_pending: changed"], 0)            # and the fill path ran (2026-11-18)
        self.assertLess(sessions_before(D(2026, 11, 18), 130)[0], CB.SEALED_LAST)    # a look-back into the window

    def test_pre_go_live_night_with_sealed_look_back_is_bar_level_only_without_the_ruling(self):
        simple_night(self.root, D(2026, 11, 18), at(2026, 11, 18, 17, 30), at(2026, 11, 19, 1, 30), open_moves=("FLAT1",))
        with mock.patch.object(CB, "PRE_GO_LIVE_LOOKBACK_RULED", False):
            with mock.patch.object(F, "step", side_effect=AssertionError("the fill model was called")), \
                    mock.patch.object(technicals, "compute_levels", side_effect=AssertionError("compute_levels was called")):
                n = CB.analyze_night(self.root / "2026-11-18")
            self.assertFalse(n["signals"]["run"])
            self.assertIn("pre-go-live night", n["signals"]["reason"])
            self.assertIn("review F1", n["signals"]["reason"])
            self.assertEqual(n["tally"]["diff_o"], 1)                          # the bar level still runs
            later = CB.analyze_night(self.root / "2026-11-18", go_live=D(2026, 12, 1))
            self.assertFalse(later["signals"]["run"])
        self.assertTrue(CB.analyze_night(self.root / "2026-11-18")["signals"]["run"])   # the ruling switches it on

    def test_sealed_session_is_never_evaluated(self):
        simple_night(self.root, D(2026, 10, 29), at(2026, 10, 29, 17, 30), at(2026, 10, 30, 1, 30), open_moves=("FLAT1",))
        with mock.patch.object(CB, "PRE_GO_LIVE_LOOKBACK_RULED", True), \
                mock.patch.object(F, "step", side_effect=AssertionError("the fill model was called")):
            n = CB.analyze_night(self.root / "2026-10-29")
        self.assertFalse(n["signals"]["run"])
        self.assertIn("inside the sealed OOS window", n["signals"]["reason"])

    def test_in_sample_night_without_sealed_look_back_runs(self):
        s = D(2024, 6, 3)
        simple_night(self.root, s, at(2024, 6, 3, 17, 30), at(2024, 6, 4, 1, 30), open_moves=("FLAT1",))
        n = CB.analyze_night(self.root / s.isoformat())
        self.assertTrue(n["signals"]["run"], n["signals"].get("reason"))
        self.assertGreater(n["tally"]["fill_pending: changed"], 0)

    def test_bars_only_reads_no_look_back(self):
        build_night_a(self.root)
        with mock.patch.object(technicals, "compute_levels", side_effect=AssertionError("compute_levels was called")):
            n = CB.analyze_night(self.root / NIGHT_A.isoformat(), bars_only=True)
        self.assertEqual(n["signals"], dict(run=False, reason="--bars-only"))
        self.assertEqual(n["tally"]["diff_o"], 2)


def relabel_look_back(day: Path, session: dt.date, start: dt.date = D(2024, 1, 2)) -> int:
    """Rewrite every final row's look-back candles with 2024 'd' labels while keeping their stamps (the reviewer's
    case, review_final/safety/run2/probes/probe_c_file_content.py). Returns the number of candles relabelled."""
    n = 0
    for p in sorted(day.glob("final_*.jsonl")):
        rows = SB.read_jsonl(p)
        for r in rows:
            for i, c in enumerate(r.get("candles") or []):
                if c["d"] < session.isoformat():
                    c["d"] = (start + dt.timedelta(days=i)).isoformat()
                    n += 1
        with open(p, "w") as fh:
            fh.write("".join(json.dumps(r) + "\n" for r in rows))
    return n


class StampsAndFolders(TempRoot):
    """Safety S6 (the guard reads the stamps, never a stored date), safety S9 (stray folders) and review SVC-04 (a
    FINAL row compared with a later FINAL row)."""

    def refused(self, day: Path, **kw) -> dict:
        with mock.patch.object(F, "step", side_effect=AssertionError("the fill model was called")), \
                mock.patch.object(technicals, "compute_levels", side_effect=AssertionError("compute_levels was called")):
            n = CB.analyze_night(day, **kw)
        self.assertFalse(n["signals"]["run"])
        return n

    def test_look_back_stamped_in_sealed_sessions_but_labelled_2024_is_refused(self):
        """Before the fix this night's signal level ran on bars stamped inside 2025-01-02..2026-10-30 (the probe:
        compute_levels got 720 bars, fills.step ran 210 times). Now every date is the stamp's own and a night whose
        stored dates disagree gets the bar level only, whatever go-live or a ruling says."""
        s = D(2026, 11, 18)                                                    # pre-go-live (go-live 2026-11-23 here)
        simple_night(self.root, s, at(2026, 11, 18, 17, 30), at(2026, 11, 19, 1, 30), open_moves=("FLAT1",))
        day = self.root / s.isoformat()
        moved = relabel_look_back(day, s)
        self.assertEqual(moved, 4 * 130)                                       # SPY and three names, 130 candles each
        n = self.refused(day)
        self.assertEqual(n["signals"]["reason"], f"stored dates disagree with the stamps ({moved} candles)")
        self.assertEqual(n["label_mismatch"], moved)
        with mock.patch.object(CB, "PRE_GO_LIVE_LOOKBACK_RULED", False):      # the ruling (True) or not: refused
            self.assertEqual(self.refused(day)["signals"]["reason"], n["signals"]["reason"])
        self.assertEqual((n["tally"]["pairs"], n["tally"]["diff_o"]), (3, 1))  # the bar level still runs ...
        self.assertEqual(n["tally"].get("basis_unchecked", 0), 0)              # ... on the stamps' dates
        late = D(2026, 12, 15)                                                 # post-go-live: refused all the same
        simple_night(self.root, late, at(2026, 12, 15, 17, 30), at(2026, 12, 16, 1, 30), open_moves=("FLAT1",))
        relabel_look_back(self.root / late.isoformat(), late)
        self.assertIn("stored dates disagree with the stamps", self.refused(self.root / late.isoformat())["signals"]["reason"])
        control = self.root / "control"
        simple_night(control, s, at(2026, 11, 18, 17, 30), at(2026, 11, 19, 1, 30), open_moves=("FLAT1",))
        with mock.patch.object(CB, "PRE_GO_LIVE_LOOKBACK_RULED", False):
            n = self.refused(control / s.isoformat())                          # pre-go-live, sealed look-back, no ruling
        self.assertEqual(n["label_mismatch"], 0)
        self.assertIn("pre-go-live night", n["signals"]["reason"])
        self.assertTrue(CB.analyze_night(control / s.isoformat())["signals"]["run"])     # by the 2026-11-12 ruling
        r = CB._fix_kinds(dict(candles=[cdl(D(2026, 11, 30), "final", 1, 1, 1, 1, 1), dict(t="09:30", o=1)],
                               _label_mismatch=99))
        self.assertNotIn("_label_mismatch", r)                                 # a stored mark is never trusted
        self.assertEqual(r["candles"][0]["d"], "2026-11-30")

    def test_stray_folders_are_ignored_listed_and_never_spoil_not_sampled(self):
        simple_night(self.root, D(2026, 11, 30), at(2026, 11, 30, 17, 30), at(2026, 12, 1, 1, 30))
        simple_night(self.root, D(2026, 12, 2), at(2026, 12, 2, 17, 30), at(2026, 12, 3, 1, 30))
        SB.RunStatus(self.root, D(2025, 6, 2), "final", at(2025, 6, 3, 1, 30)).finish(      # the S9 probe's stray
            at(2025, 6, 3, 1, 30), "MISSED-NIGHT", reason="no evening sample")
        for name in ("2026-10-29", "2026-10-30", "2026-12-05", "2027-04-01", "20261201", "notes"):
            (self.root / name).mkdir()
        rep = CB.build_report(self.root)
        self.assertEqual([n["session"] for n in rep["nights"]], ["2026-11-30", "2026-12-02"])
        self.assertEqual(rep["not_sampled"], ["2026-12-01"])
        self.assertEqual({i["folder"]: i["reason"] for i in rep["meta"]["ignored"]}, {
            "2025-06-02": "not after 2026-10-30", "2026-10-29": "not after 2026-10-30",
            "2026-10-30": "not after 2026-10-30",                              # the seal's last day (m33)
            "2026-12-05": "not an NYSE session",
            "2027-04-01": "outside the calendar carried by sample_bars.py (2026-11-01..2027-03-31)",
            "20261201": "not a YYYY-MM-DD session date", "notes": "not a YYYY-MM-DD session date"})
        self.assertIn("IGNORED folders (a night is a carried-calendar session after 2026-10-30): 2025-06-02 (not after "
                      "2026-10-30)", CB.render(rep))
        rep = CB.build_report(self.root, ["2026-11-30", "2025-06-02", "2026-12-03"])
        self.assertEqual([n["session"] for n in rep["nights"]], ["2026-11-30"])
        self.assertEqual([i["folder"] for i in rep["meta"]["ignored"]], ["2025-06-02"])
        self.assertEqual(rep["meta"]["requested_missing"], ["2026-12-03"])

    def test_a_final_bar_revised_between_two_final_pulls_is_counted(self):
        """Review SVC-04: with only unfinished names re-pulled, each name had one FINAL row and this count was 0 by
        construction. The 06:30 full pull gives a second FINAL row to compare."""
        s = D(2026, 11, 30)
        n = simple_night(self.root, s, at(2026, 11, 30, 17, 35), at(2026, 12, 1, 1, 30))
        h = flat_hist(s)
        n.final("FLAT1", h + [cdl(s, "final", 20.0, 20.5, 19.6, 20.0, 1_002_700)], at(2026, 12, 1, 6, 30))     # revised
        n.final("FLAT2", h + [cdl(s, "final", 20.0, 20.5, 19.6, 20.0, 1_002_000)], at(2026, 12, 1, 6, 30, 1))  # the same
        t = CB.analyze_night(self.root / s.isoformat())["tally"]
        self.assertEqual(t["final_revised_between_pulls"], 1)
        other = self.root / "sampled"                                          # the same through the sampler itself
        clock = FakeClock(at(2026, 11, 30, 17, 35))
        SB.run_evening(FakeSchwab(s).md, root=other, clock=clock, sleep=clock.sleep, fetch=fetch_directory, **QUIET)
        SB.run_final(FakeSchwab(s).md, root=other, clock=FakeClock(at(2026, 12, 1, 1, 30)), sleep=lambda x: None, **QUIET)
        later = FakeSchwab(s, revise={"CW": 700})
        SB.run_final(later.md, root=other, clock=FakeClock(at(2026, 12, 1, 6, 30)), sleep=lambda x: None, full=True,
                     **QUIET)
        self.assertEqual(len(later.calls["daily"]), 13)                        # full: every symbol again
        night = CB.analyze_night(other / s.isoformat())
        self.assertEqual(night["tally"]["final_revised_between_pulls"], 1)     # CW
        self.assertIn("final candle revised between pulls: 1", CB.render(CB.build_report(other)))


class GoLiveFailsClosed(TempRoot):
    """Review D2: every night is pre-go-live until the reviewed constant GO_LIVE_ACTUAL records go-live;
    params.go_live_target is only a target and never opens the guard. PRE_GO_LIVE_LOOKBACK_RULED is the second,
    independent condition: it opens pre-go-live nights (and only those). Neither opens a sealed session. The
    constant records the owner's ruling of 2026-11-12 (spec 3.7), so it is True in the source; the tests that show
    go-live deciding alone set it False."""

    NIGHTS = ((D(2026, 11, 20), at(2026, 11, 20, 17, 30), at(2026, 11, 21, 1, 30)),    # Fri before the target
              (D(2026, 11, 23), at(2026, 11, 23, 17, 30), at(2026, 11, 24, 1, 30)),    # the target day
              (D(2026, 11, 30), at(2026, 11, 30, 17, 30), at(2026, 12, 1, 1, 30)))     # a week after it

    def setUp(self):
        super().setUp()
        for session, ev, fi in self.NIGHTS:
            simple_night(self.root, session, ev, fi, open_moves=("FLAT1",))

    def refused(self, day: str, **kw) -> dict:
        """analyze_night with the fill model and compute_levels made to fail if called: a refused night calls neither."""
        with mock.patch.object(F, "step", side_effect=AssertionError("the fill model was called")), \
                mock.patch.object(technicals, "compute_levels", side_effect=AssertionError("compute_levels was called")):
            n = CB.analyze_night(self.root / day, **kw)
        self.assertFalse(n["signals"]["run"], (day, kw))
        self.assertEqual(n["tally"]["diff_o"], 1)                              # the bar level still runs
        return n

    def runs(self, day: str, **kw) -> dict:
        n = CB.analyze_night(self.root / day, **kw)
        self.assertTrue(n["signals"]["run"], (day, kw, n["signals"].get("reason")))
        return n

    def test_the_source_records_the_ruling_and_not_go_live(self):
        """GO_LIVE_ACTUAL stays unset (go-live has not happened); PRE_GO_LIVE_LOOKBACK_RULED records the owner's ruling
        of 2026-11-12, and the comment above it cites it (spec 3.7)."""
        with open(CB.__file__, encoding="utf-8") as fh:
            source = fh.read()
        tree = ast.parse(source)
        value, line = {}, {}
        for node in tree.body:                                                 # module-level assignments only
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                value[node.target.id], line[node.target.id] = node.value, node.lineno
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        value[t.id], line[t.id] = node.value, node.lineno
        for name, want in (("GO_LIVE_ACTUAL", None), ("PRE_GO_LIVE_LOOKBACK_RULED", True)):
            self.assertIsInstance(value[name], ast.Constant, name)
            self.assertIs(value[name].value, want, name)
        above = []                                                             # the comment block right above it
        for ln in reversed(source.splitlines()[:line["PRE_GO_LIVE_LOOKBACK_RULED"] - 1]):
            if not ln.startswith("#"):
                break
            above.insert(0, ln.lstrip("#").strip())
        comment = " ".join(above)
        for phrase in ("The owner's ruling of 2026-11-12, recorded in spec 3.7", "Signal-level flip comparisons can resume"):
            self.assertIn(phrase, comment)

    def test_with_go_live_unset_every_night_is_pre_go_live(self):
        with mock.patch.object(CB, "GO_LIVE_ACTUAL", None):
            with mock.patch.object(CB, "PRE_GO_LIVE_LOOKBACK_RULED", False):  # go-live alone decides
                for session, _, _ in self.NIGHTS:                              # on and after the target too
                    reason = self.refused(session.isoformat())["signals"]["reason"]
                    self.assertIn("pre-go-live night (go-live not recorded: GO_LIVE_ACTUAL is unset", reason)
                    self.assertIn(f"params.go_live_target {PARAMS.go_live_target} is only a target", reason)
                    self.assertIn("review F1", reason)
                self.refused("2026-11-30", go_live=D(2026, 11, 23))
                rep = CB.build_report(self.root)
                self.assertEqual([n["session"] for n in rep["nights"] if n["signals"]["run"]], [])
            self.assertIsNone(CB.effective_go_live())
            self.assertIsNone(CB.effective_go_live(D(2026, 11, 23)))           # a requested date opens nothing
            rep = CB.build_report(self.root)                                   # the ruling: pre-go-live nights run
            self.assertEqual([n["session"] for n in rep["nights"] if n["signals"]["run"]],
                             ["2026-11-20", "2026-11-23", "2026-11-30"])
            self.assertIsNone(rep["meta"]["go_live"])
            text = CB.render(rep)
            self.assertIn("go-live NOT RECORDED (GO_LIVE_ACTUAL unset; params.go_live_target 2026-11-23 is only a "
                          "target): every night is pre-go-live", text)
            self.assertIn("pre-go-live look-back ruled: True (the owner's ruling of 2026-11-12, spec 3.7", text)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(CB.main(["--all", "--root", str(self.root), "--go-live", "2026-11-23"]), 2)
            self.assertIn("refused: go-live is not recorded", buf.getvalue())

    def test_the_params_target_is_never_read_as_go_live(self):
        long_past = dataclasses.replace(PARAMS, go_live_target="2026-11-01")
        with mock.patch.object(CB, "GO_LIVE_ACTUAL", None), mock.patch.object(CB, "PARAMS", long_past), \
                mock.patch.object(CB, "PRE_GO_LIVE_LOOKBACK_RULED", False):
            self.refused("2026-11-30")
            self.refused("2026-11-23")

    def test_a_recorded_go_live_opens_that_day_on_and_a_request_only_tightens(self):
        with mock.patch.object(CB, "GO_LIVE_ACTUAL", D(2026, 11, 23)), \
                mock.patch.object(CB, "PRE_GO_LIVE_LOOKBACK_RULED", False):
            self.assertIn("pre-go-live night (go-live 2026-11-23)", self.refused("2026-11-20")["signals"]["reason"])
            self.runs("2026-11-23")
            self.runs("2026-11-30")
            self.refused("2026-11-23", go_live=D(2026, 11, 24))                # later: tightens
            self.refused("2026-11-20", go_live=D(2026, 11, 1))                 # earlier: cannot loosen
            self.assertEqual(CB.effective_go_live(D(2026, 11, 1)), D(2026, 11, 23))
            self.assertEqual(CB.effective_go_live(D(2026, 12, 1)), D(2026, 12, 1))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(CB.main(["--all", "--root", str(self.root), "--go-live", "2026-11-01"]), 2)
                self.assertEqual(CB.main(["--all", "--root", str(self.root), "--go-live", "2026-11-24",
                                          "--json", str(self.root / "r.json")]), 0)
            self.assertIn("earlier than GO_LIVE_ACTUAL 2026-11-23: refused", buf.getvalue())
            rep = load_json(self.root / "r.json")
            self.assertEqual((rep["meta"]["go_live"], rep["meta"]["go_live_actual"]), ("2026-11-24", "2026-11-23"))
            self.assertEqual([n["session"] for n in rep["nights"] if n["signals"]["run"]], ["2026-11-30"])

    def test_a_go_live_that_is_not_a_plain_date_fails_closed(self):
        for bad in ("2026-11-23", dt.datetime(2026, 11, 23, 0, 0), 20261123, True):
            with self.subTest(bad=bad), mock.patch.object(CB, "GO_LIVE_ACTUAL", bad), \
                    mock.patch.object(CB, "PRE_GO_LIVE_LOOKBACK_RULED", False):
                self.assertIsNone(CB.effective_go_live())
                self.refused("2026-11-30")

    def test_the_ruling_is_a_second_independent_condition(self):
        with mock.patch.object(CB, "GO_LIVE_ACTUAL", None), mock.patch.object(CB, "PRE_GO_LIVE_LOOKBACK_RULED", True):
            self.runs("2026-11-20")                                            # ruled: pre-go-live nights run
            self.runs("2026-11-30")
        with mock.patch.object(CB, "GO_LIVE_ACTUAL", D(2026, 11, 23)), \
                mock.patch.object(CB, "PRE_GO_LIVE_LOOKBACK_RULED", False):
            self.refused("2026-11-20")                                         # not ruled: go-live decides
            self.runs("2026-11-23")
        for not_true in ("True", 1, [True]):                                   # only True itself is a ruling
            with self.subTest(ruled=not_true), mock.patch.object(CB, "GO_LIVE_ACTUAL", None), \
                    mock.patch.object(CB, "PRE_GO_LIVE_LOOKBACK_RULED", not_true):
                self.refused("2026-11-20")
        simple_night(self.root, D(2026, 10, 29), at(2026, 10, 29, 17, 30), at(2026, 10, 30, 1, 30), open_moves=("FLAT1",))
        with mock.patch.object(CB, "GO_LIVE_ACTUAL", D(2026, 10, 1)), mock.patch.object(CB, "PRE_GO_LIVE_LOOKBACK_RULED", True):
            self.assertIn("inside the sealed OOS window", self.refused("2026-10-29")["signals"]["reason"])


class EndToEnd(TempRoot):
    def test_sampler_output_feeds_the_comparison(self):
        s = D(2026, 11, 30)
        clock = FakeClock(at(2026, 11, 30, 17, 35))
        SB.run_evening(FakeSchwab(s, truncate={"TRX": -1}).md, root=self.root, clock=clock, sleep=clock.sleep,
                       fetch=fetch_directory, **QUIET)
        clock = FakeClock(at(2026, 12, 1, 1, 30))
        SB.run_final(FakeSchwab(s, truncate={"TRX": -1}).md, root=self.root, clock=clock, sleep=clock.sleep, **QUIET)
        n = CB.analyze_night(self.root / "2026-11-30")
        t = n["tally"]
        self.assertEqual(n["state"], "OK")
        self.assertEqual((t["universe"], t["pairs"], t["ev_TRUNCATED"]), (12, 11, 1))
        self.assertEqual(t["diff_o"], 1)                                       # AAA
        self.assertEqual(t["diff_v"], 11)
        self.assertTrue(n["signals"]["run"])
        self.assertEqual(n["names"]["truncated_response"], ["TRX"])
        self.assertEqual(n["minute_symbols"], 3)


# =========================================================================================================
# 7. Statistics and the order formulas
# =========================================================================================================

class Statistics(unittest.TestCase):
    def test_exact_upper_bounds(self):
        self.assertAlmostEqual(CB.upper_bound(0, 10), 0.2589, places=4)       # "0 of 10 M2 signals, upper bound 26%"
        for n, want in ((5, 0.451), (20, 0.139), (30, 0.095), (60, 0.049)):
            self.assertAlmostEqual(CB.upper_bound(0, n), want, places=3)
        self.assertAlmostEqual(CB.upper_bound(1, 10), 0.3942, places=3)
        self.assertEqual(CB.upper_bound(10, 10), 1.0)
        self.assertIsNone(CB.upper_bound(0, 0))
        self.assertIn("0 of 10 (0.00%; 95% upper bound 25.9%)", CB.rate(0, 10))

    def test_clustered_interval(self):
        self.assertIsNone(CB.clustered_ci([1], [10]))
        lo, hi = CB.clustered_ci([1, 1], [10, 10])
        self.assertAlmostEqual(lo, 0.1)
        self.assertAlmostEqual(hi, 0.1)
        lo, hi = CB.clustered_ci([0, 4], [10, 10])
        self.assertLess(lo, 0.2)
        self.assertGreater(hi, 0.2)

    def test_levels_by_hand(self):
        lv = CB.levels(CB.Decimal("20.61"), 0.8036, 1.5, 19.84)
        D_ = CB.Decimal
        self.assertEqual((lv["T"], lv["C"], lv["S"], lv["P"], lv["N"], lv["sizable"]),
                         (D_("20.61"), D_("20.81"), D_("19.40"), D_("24.24"), 10, True))
        self.assertEqual(CB.levels(D_("20.61"), 0.8036, 1.0, 19.84)["S"], D_("19.80"))   # T - 1.0 ATR is below S0
        self.assertEqual(CB.whole_cent_trigger(20.511), D_("20.53"))
        self.assertEqual(CB.whole_cent_trigger(20.514), D_("20.53"))
        self.assertEqual(CB.whole_cent_trigger(20.6), D_("20.61"))
        self.assertIsNone(CB.levels(D_("1.00"), 2.0, 1.0, None))                # S would be below zero: refused
        self.assertTrue(CB.ORDER_SOURCE)


class OrderSource(TempRoot):
    """Review D6: compare_bars builds every T, level and ticket through loops/phase2/orders.py, which must pass a
    startup self-check on known answers. There is no local copy of the formulas: without a usable orders.py the
    whole-cent T, the levels, the tickets, the fill path and the signal level print NOT RUN with the reason."""

    def test_orders_py_is_in_use_and_no_copy_of_its_formulas_remains(self):
        self.assertIsNotNone(CB.ORDERS)
        self.assertTrue(CB.ORDER_SOURCE.startswith("loops/phase2/orders.py ("), CB.ORDER_SOURCE)
        for name in ("local_levels", "local_trigger", "SELF_CHECK"):
            self.assertFalse(hasattr(CB, name), name)
        with open(CB.__file__, encoding="utf-8") as fh:
            text = fh.read()
        # the parameters only the order formulas read: T's offset, C's ATR share, P's R multiple and the sizing
        for p in ("trigger_offset", "ceiling_atr", "target_r", "basis", "risk_pct", "position_cap_pct", "min_shares"):
            self.assertIsNone(re.search(r"PARAMS\." + p + r"\b", text), p)

    def test_levels_and_t_follow_the_spec_text_oracle(self):
        rnd = random.Random(20261112)
        for _ in range(2000):
            high = round(rnd.uniform(5, 99), rnd.choice([2, 3, 4, 6]))
            atr = round(rnd.uniform(0.05, 5.0), 4)
            k = rnd.choice(PARAMS.stop_k)
            t = CB.whole_cent_trigger(high)
            self.assertEqual(t, H.ceil_cent(H.q(high) + H.Fraction(1, 100)), high)
            s0 = rnd.choice([None, round(high - rnd.uniform(0.05, 3.0), 2), round(high - rnd.uniform(0.05, 3.0), 6)])
            self.assertEqual(CB.levels(t, atr, k, s0), H.spec_levels(t, atr, k, s0), (high, atr, k, s0))

    def test_an_absent_module_is_not_usable_and_nothing_replaces_it(self):
        import phase2
        saved = phase2.__dict__.pop("orders", None)          # `from phase2 import orders` reads this attribute first
        try:
            with mock.patch.dict(sys.modules, {"phase2.orders": None}):
                mod, source = CB._order_module()
        finally:
            if saved is not None:
                phase2.orders = saved
        self.assertIsNone(mod)
        self.assertIn("loops/phase2/orders.py is not usable: it cannot be imported", source)

    def fake_orders(self, **changes):
        real = CB.ORDERS
        ns = dict(trigger_from_high=real.trigger_from_high, build_bracket=real.build_bracket,
                  paper_shares=real.paper_shares, ATR_ONLY=real.ATR_ONLY)
        ns.update(changes)
        return types.SimpleNamespace(**ns)

    def check_with(self, fake):
        import phase2
        with mock.patch.object(phase2, "orders", fake), mock.patch.dict(sys.modules, {"phase2.orders": fake}):
            return CB._order_module()

    def test_a_module_that_departs_from_a_known_answer_fails_the_self_check(self):
        real = CB.ORDERS

        def t_down(high, params):                    # the rejected alternative: the high cut to the cent, + 0.01
            return CB.Decimal(repr(high)).quantize(CB.CENT, rounding=CB.ROUND_FLOOR) + CB.CENT
        mod, source = self.check_with(self.fake_orders(trigger_from_high=t_down))
        self.assertIsNone(mod)
        self.assertIn("failed the startup self-check: trigger_from_high(20.511) is 20.52", source)

        def ceiling_up(trigger, atr, k, params, *, structural_stop):
            b = real.build_bracket(trigger, atr, k, params, structural_stop=structural_stop)
            return real.Bracket(b.trigger, b.ceiling + CB.Decimal("0.01"), b.stop, b.target + CB.Decimal("0.01"))
        mod, source = self.check_with(self.fake_orders(build_bracket=ceiling_up))
        self.assertIsNone(mod)
        self.assertIn("failed the startup self-check on", source)

        def never_refuses(trigger, atr, k, params, *, structural_stop):
            try:
                return real.build_bracket(trigger, atr, k, params, structural_stop=structural_stop)
            except ValueError:
                return real.Bracket(CB.Decimal("1.00"), CB.Decimal("1.50"), CB.Decimal("0.50"), CB.Decimal("2.50"))
        mod, source = self.check_with(self.fake_orders(build_bracket=never_refuses))
        self.assertIsNone(mod)
        self.assertIn("must be refused", source)
        mod, source = self.check_with(types.SimpleNamespace(build_bracket=real.build_bracket))
        self.assertIsNone(mod)
        self.assertIn("lacks", source)
        mod, _ = self.check_with(self.fake_orders())                                     # the real functions pass
        self.assertIsNotNone(mod)

    def test_without_orders_the_levels_tickets_and_signal_level_print_not_run(self):
        build_night_a(self.root)
        why = "loops/phase2/orders.py is not usable: it cannot be imported (test)"
        with mock.patch.object(CB, "ORDERS", None), mock.patch.object(CB, "ORDER_SOURCE", why), \
                mock.patch.object(F, "step", side_effect=AssertionError("the fill model was called")), \
                mock.patch.object(technicals, "compute_levels", side_effect=AssertionError("compute_levels was called")):
            n = CB.analyze_night(self.root / NIGHT_A.isoformat())
            rep = CB.build_report(self.root)
            text = CB.render(rep)
            with self.assertRaises(CB.OrdersUnavailable):
                CB.whole_cent_trigger(20.5)
            with self.assertRaises(CB.OrdersUnavailable):
                CB.levels(CB.Decimal("20.61"), 0.8036, 1.5, 19.84)
        self.assertFalse(n["signals"]["run"])
        self.assertTrue(n["signals"]["reason"].startswith(why), n["signals"]["reason"])
        self.assertEqual(n["tally"]["diff_o"], 2)                              # the bar level still runs ...
        self.assertNotIn("trigger_moves", n["tally"])                          # ... except the whole-cent T
        self.assertFalse(rep["meta"]["orders_ok"])
        for line in (f"order levels: NOT RUN: {why}", "whole-cent T NOT RUN", f"order levels T/C/S/P/N: NOT RUN: {why}",
                     f"tickets (breadth on): NOT RUN: {why}", f"day-t fill path (synthetic brackets): NOT RUN: {why}",
                     f"signal level NOT RUN: {why}"):
            self.assertIn(line, text)
        self.assertRegex(text, r"whole-cent trigger T\s+NOT RUN: ")


# =========================================================================================================
# 8. Contracts for the new files (spec 2 and 3.7)
# =========================================================================================================

MODULES = [os.path.join(ROOT, "loops", "phase2", f) for f in ("sample_bars.py", "compare_bars.py")] + \
    [os.path.join(ROOT, "loops", "phase2_sample.py")]
TEST_FILES = [os.path.abspath(__file__)] + [os.path.join(ROOT, "tests", f) for f in ("test_phase2_flips_scenarios.py",
                                                                                     "phase2_flip_helpers.py")]
NEW_FILES = MODULES + TEST_FILES


class Contracts(unittest.TestCase):
    def read(self, path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_no_order_placing_names(self):
        words = ["place" + "_order", "replace" + "_order", "cancel" + "_order", "order" + "_executor"]
        for path in NEW_FILES:
            text = self.read(path)
            for w in words:
                self.assertNotIn(w, text, f"{path} references {w}")

    def test_no_unseal_and_no_private_fills_names(self):
        # built from pieces, so that this file itself never carries the tokens the repo's contract test looks for
        unseals = ["UNSEALED" + "_BY_PICK", "KNOWN_ANSWER" + "_REPLAY"]
        private = ["_check" + "_seal", "_is_known" + "_answer", "_entry" + "_session", "_held" + "_session",
                   "_oos" + "_window", "_Se" + "al", "_SE" + "ALS", "_SPEC_OOS" + "_WINDOW", "_KNOWN_ANSWER" + "_RECORDS",
                   "_REPLAY_TARGET" + "_MULT", "__kw" + "defaults__", "__de" + "faults__", "object." + "__setattr__"]
        for path in NEW_FILES:
            text = self.read(path)
            for w in unseals:
                self.assertNotIn(w, text, path)
            for w in private:
                self.assertIsNone(re.search(r"(?<![A-Za-z0-9_])" + re.escape(w) + r"(?![A-Za-z0-9_])", text), (path, w))
        for path in MODULES:                                                   # the modules never pass a seal argument
            self.assertNotIn("seal" + "=", self.read(path), path)

    def module_imports(self, path):
        tree = ast.parse(self.read(path))
        out = set()
        for node in tree.body:                                                 # module level only
            if isinstance(node, ast.Import):
                out |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                out.add((node.module or "").split(".")[0])
        return out

    def test_importing_reaches_no_network_or_client(self):
        for name in ("sample_bars.py", "compare_bars.py"):
            imports = self.module_imports(os.path.join(ROOT, "loops", "phase2", name))
            self.assertFalse(imports & {"config", "httpx", "schwab", "requests", "urllib", "loop_common", "socket"},
                             (name, imports))
            anywhere = set()                                                   # function-level imports too (review D7)
            for node in ast.walk(ast.parse(self.read(os.path.join(ROOT, "loops", "phase2", name)))):
                if isinstance(node, ast.Import):
                    anywhere |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    anywhere.add((node.module or "").split(".")[0])
            self.assertFalse(anywhere & {"config", "schwab", "loop_common", "dotenv"}, (name, anywhere))
            text = self.read(os.path.join(ROOT, "loops", "phase2", name))
            for word in ("loop_common", "dotenv", "resolve_token_path", "token_age_days", "environ", "getenv"):
                # safety S5: the package reads neither the token nor the settings; the runner hands it a reader
                self.assertIsNone(re.search(r"(?<![A-Za-z0-9_])" + word + r"(?![A-Za-z0-9_])", text), (name, word))
        self.assertLessEqual(self.module_imports(os.path.join(ROOT, "loops", "phase2", "compare_bars.py")),
                             {"__future__", "argparse", "datetime", "json", "math", "sys", "collections", "decimal",
                              "pathlib", "typing", "technicals", "phase2"})

    # sample_bars names compare_bars may use: constants and readers only (review safety F7: no atomic_write_json,
    # RunStatus, _write_status, record_missed or any run_* function)
    CB_READS_SB = {"ALREADY_FINAL", "CALENDAR_FIRST", "CALENDAR_LAST", "CalendarError", "EMPTY", "ERROR", "FINAL",
                   "M2_LIKE_GAP", "M2_LIKE_VOLUME", "NOT_FINAL", "NO_BAR", "NY", "OUT", "PROVISIONAL", "TRUNCATED",
                   "better_class", "evening_timing", "is_session", "iso", "m2_like_quote", "now_et", "pulled_at",
                   "row_class", "session_tags", "sessions_between", "stamp_kind", "statuses"}
    PATH_WRITES = {"write_text", "write_bytes", "touch", "mkdir", "unlink", "rename", "rmdir", "symlink_to"}

    @staticmethod
    def write_opens(tree: ast.Module) -> list[tuple[str, int]]:
        """(top-level place, line) of every open() that may write: the builtin with a mode that is not a constant
        read mode ('r', 'rb', ...), or any .open() method call (Path.open, io.open, os.open) with an argument that is
        not one, in any quoting or keyword form."""
        def writes(mode) -> bool:
            return not (isinstance(mode, ast.Constant) and isinstance(mode.value, str) and not set(mode.value) & set("wax+"))
        out = []
        for stmt in tree.body:
            place = stmt.name if isinstance(stmt, (ast.FunctionDef, ast.ClassDef)) else "module"
            for node in ast.walk(stmt):
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Name) and node.func.id == "open":
                    modes = node.args[1:2] + [k.value for k in node.keywords if k.arg == "mode"]
                elif isinstance(node.func, ast.Attribute) and node.func.attr == "open":
                    modes = list(node.args) + [k.value for k in node.keywords if k.arg in ("mode", "flags")]
                else:
                    continue
                if any(writes(m) for m in modes):
                    out.append((place, node.lineno))
        return out

    def test_compare_bars_never_writes_without_json(self):
        """Review safety F7: compare_bars is READ-ONLY. By the AST: exactly one open() that may write, inside main (the
        --json report); no Path method that writes, moves or removes; and from sample_bars only the constants and
        readers it uses today."""
        tree = ast.parse(self.read(os.path.join(ROOT, "loops", "phase2", "compare_bars.py")))
        self.assertEqual([place for place, _ in self.write_opens(tree)], ["main"])
        self.assertEqual(sorted({n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call)
                                 and isinstance(n.func, ast.Attribute) and n.func.attr in self.PATH_WRITES}), [])
        used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                and n.value.id == "SB"}
        self.assertLessEqual(used, self.CB_READS_SB, sorted(used - self.CB_READS_SB))
        sb_imports = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                      and "sample_bars" in ast.unparse(n)]
        self.assertEqual(sb_imports, ["from phase2 import sample_bars as SB"])    # the one name it reaches SB by
        caught = ("def f(day):\n    open(day / 'x', 'w')", "def f(p):\n    open(p, mode='a')", "def f(p, m):\n    open(p, m)",
                  "def f(p):\n    p.open('w')", "def f(p):\n    io.open(p, 'r+')", "def f(p):\n    os.open(p, flags)")
        for src in caught:                                                    # the scan's own positive cases
            self.assertTrue(self.write_opens(ast.parse(src)), src)
        for src in ("def f(p):\n    open(p)", "def f(p):\n    open(p, 'rb')", "def f(p):\n    p.open()",
                    "def f(p):\n    open(p, encoding='utf-8', errors='replace')"):
            self.assertEqual(self.write_opens(ast.parse(src)), [], src)

    def test_compare_bars_leaves_the_sample_root_unchanged(self):
        """Review safety F7: a full report over the sample root, without --json, leaves every file and folder as it
        was (paths and bytes), the night folders, a MISSED-NIGHT folder and ignored folders included."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_night_a(root)
            simple_night(root, D(2026, 12, 1), at(2026, 12, 1, 22, 35), at(2026, 12, 2, 1, 30),
                         names=("FLAT1", "FLAT2", "ALRDY"), already_final=("ALRDY",))
            SB.RunStatus(root, D(2026, 12, 2), "final", at(2026, 12, 3, 1, 30)).finish(
                at(2026, 12, 3, 1, 30), "MISSED-NIGHT", reason="no evening sample")
            simple_night(root, D(2026, 11, 18), at(2026, 11, 18, 17, 30), at(2026, 11, 19, 1, 30))   # pre-go-live
            for name in ("2026-10-29", "notes"):
                (root / name).mkdir()

            def snapshot() -> dict:
                return {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None) for p in sorted(root.rglob("*"))}
            before = snapshot()
            self.assertGreater(len(before), 20)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(CB.main(["--all", "--root", str(root)]), 0)
            self.assertIn("NIGHTS", out.getvalue())
            self.assertEqual(snapshot(), before)


class LaunchdTemplate(unittest.TestCase):
    """The flip-measurement sampler's night job: its committed launchd template, the file that gets installed (spec
    4, step 4). Not the step-1 nightly scan (ruled 2026-11-12), which has no template yet."""

    PATH = os.path.join(ROOT, "deploy", "launchd", "com.stockmonitor.phase2barsample.night.plist")

    def test_the_night_template_runs_the_runner_weekdays_at_1720_and_at_load(self):
        import plistlib
        with open(self.PATH, "rb") as fh:
            p = plistlib.load(fh)
        self.assertEqual(set(p), {"Label", "ProgramArguments", "WorkingDirectory", "StartCalendarInterval",
                                  "RunAtLoad", "StandardOutPath", "StandardErrorPath"})
        self.assertEqual(p["Label"], "com.stockmonitor.phase2barsample.night")
        # the runner, never sample_bars.py itself, and no caffeinate: the runner holds the assertion (R10)
        self.assertEqual(p["ProgramArguments"], ["{{PROJECT_ROOT}}/loops/run.sh", "loops/phase2_sample.py", "night"])
        self.assertEqual(p["WorkingDirectory"], "{{PROJECT_ROOT}}")
        self.assertIs(p["RunAtLoad"], True)                                    # a login or restart starts it
        launch = (dt.datetime.combine(D(2026, 11, 30), dt.time.fromisoformat(PARAMS.evening_scan_et)) - SB.AWAKE_LEAD)
        self.assertEqual(p["StartCalendarInterval"],
                         [{"Weekday": d, "Hour": launch.hour, "Minute": launch.minute} for d in range(1, 6)])
        self.assertEqual((launch.hour, launch.minute), (17, 20))
        self.assertEqual((p["StandardOutPath"], p["StandardErrorPath"]),
                         ("{{PROJECT_ROOT}}/logs/launchd_phase2barsample.out",
                          "{{PROJECT_ROOT}}/logs/launchd_phase2barsample.err"))


if __name__ == "__main__":
    unittest.main()
