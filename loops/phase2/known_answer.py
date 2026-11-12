"""The experiment's 14 real stop-outs: the only orders the OOS seal lets through before the pick.

Spec 3.7 step 2 (ruling 2026-11-11): the exemption that lets the known-answer contract run before
the freeze is scoped to these 14 real fill records and the bars those trades need, entry day
through exit day. Under it, fills.py evaluates an order only if it is one of these replays exactly:
  * the record's ticker;
  * trigger = ceiling = the real entry fill, and the real stop;
  * a one-session entry window that is the record's entry day (signaled before it);
  * a target REPLAY_TARGET_MULT times the entry, far above every bar, so the replay can end only at
    the real stop;
  * sessions from the entry day through the exit day.
Anything else inside the sealed window is refused under it.

Prices are on the basis of the bars recorded in tests/fixtures/phase2_known_answer.json: FRO sits
$1.60 below its as-traded prices (special distribution, 2026-09-18). A test compares this table
with that fixture, record by record, so the two cannot drift apart.

PURE data: no network, no clock, no file I/O.
"""

from __future__ import annotations

import datetime as dt
from typing import NamedTuple


REPLAY_TARGET_MULT = 3.0   # the replay's target: 3 x the entry price, never reached in these trades


class Record(NamedTuple):
    label: str
    ticker: str
    entry_date: dt.date
    exit_date: dt.date
    entry: float       # the real entry fill (Schwab's average price, to a tenth of a cent), on the bar basis
    stop: float        # the real stop, on the bar basis


RECORDS = (
    Record("EVER", "EVER", dt.date(2026, 4, 30), dt.date(2026, 4, 30), 15.57, 14.76),
    Record("TASK #1", "TASK", dt.date(2026, 5, 7), dt.date(2026, 5, 7), 6.37, 6.27),
    Record("TASK #2", "TASK", dt.date(2026, 5, 8), dt.date(2026, 5, 8), 6.31, 6.20),
    Record("APPN", "APPN", dt.date(2026, 5, 11), dt.date(2026, 5, 13), 21.34, 19.50),
    Record("CXM", "CXM", dt.date(2026, 6, 9), dt.date(2026, 6, 18), 5.33, 5.00),
    Record("FRO", "FRO", dt.date(2026, 7, 30), dt.date(2026, 8, 11), 37.00, 35.74),
    Record("AEO", "AEO", dt.date(2026, 7, 31), dt.date(2026, 8, 12), 17.075, 16.55),
    Record("CCL", "CCL", dt.date(2026, 8, 11), dt.date(2026, 8, 19), 27.665, 26.95),
    Record("ASO", "ASO", dt.date(2026, 8, 14), dt.date(2026, 8, 17), 47.91, 46.48),
    Record("RF", "RF", dt.date(2026, 8, 25), dt.date(2026, 8, 31), 30.425, 29.90),
    Record("F", "F", dt.date(2026, 9, 1), dt.date(2026, 9, 9), 13.98, 13.68),
    Record("CNK", "CNK", dt.date(2026, 9, 10), dt.date(2026, 9, 15), 35.00, 34.05),
    Record("AR", "AR", dt.date(2026, 9, 17), dt.date(2026, 9, 21), 35.71, 34.78),
    Record("RRC", "RRC", dt.date(2026, 9, 17), dt.date(2026, 9, 21), 39.11, 38.28),
)
