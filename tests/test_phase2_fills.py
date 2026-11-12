"""Unit tests for the Phase 2 fill model (loops/phase2/fills.py), no network.

Every expected value is derived from the text of specs/phase2_spec.md sections
3.1, 3.3, 3.4, 3.5, 3.7, 4 and 6, not from the implementation. Two fixtures:

  BASE   T 20.00, C 20.25, S 19.00, P 23.00, ATR 1.00, 20 bps tier
         (h = 0.04 at $20, 0.038 at $19, 0.046 at $23). Easy to check by hand,
         but ATR, T - S and $1 are all the same number.
         Costs (3.4): trigger entry h, opening fill 2h, target h, time exit 2h,
         every stop exit 4h. So a stop at S nets 19.00 - 4 x 0.038 = 18.848.
  UNITS  T 20.00, C 20.10, S 19.40, P 21.80, ATR 0.40, 5 bps tier (k = 1.5, so
         T - S = 0.60). ATR != T - S != 1, so a rule that confuses dollars,
         ATRs and R cannot pass.

Test sessions are in-sample dates (2023): by default the model refuses the
sealed out-of-sample window 2025-01-02..2026-10-30 (spec 3.7 step 2).

Run:  python -m unittest tests.test_phase2_fills
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import os
import random
import sys
import unittest
from dataclasses import replace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "loops"))

from phase2 import fills as F  # noqa: E402
from phase2.params import PARAMS, params_hash, unset  # noqa: E402

P0 = PARAMS                                           # the parameter set as it stands
X2 = replace(P0, cost_mult=PARAMS.cost_sensitivity_mult)   # the "costs x 2" row: every cost doubles
CB = replace(P0, crash_bar_bound=True)                # the crash-bar row
SIGNAL_DAY = dt.date(2023, 1, 9)                      # a Monday, in-sample

UNITS = dict(trigger=20.00, ceiling=20.10, stop=19.40, target=21.80, atr=0.40, tier_bps=5.0)


def day(n: int) -> dt.date:
    """The n-th weekday after the signal day (n = 1 is the first window session)."""
    d, left = SIGNAL_DAY, n
    while left:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            left -= 1
    return d


def bar(n: int, o: float, h: float, lo: float, c: float) -> F.Bar:
    return F.Bar(day(n), o, h, lo, c)


def order(**kw) -> F.Order:
    base = dict(ticker="TEST", signal_date=SIGNAL_DAY, trigger=20.00, ceiling=20.25, stop=19.00,
                target=23.00, window=3, atr=1.0, tier_bps=20.0)
    base.update(kw)
    return F.Order(**base)


def feed(o: F.Order, bars, params=P0, breadth=None, seal=F.SEALED) -> F.Order:
    """Step through bars in order. An int in place of a bar means 'that session has no bar'."""
    for i, b in enumerate(bars):
        ok = True if breadth is None else breadth[i]
        session, the_bar = (day(b), None) if isinstance(b, int) else (b.date, b)
        o = F.step(o, session, the_bar, breadth_ok=ok, params=params, seal=seal)
    return o


TRIGGER_ENTRY = (1, 19.80, 20.10, 19.70, 20.05)       # open < T <= high: filled at T, no exit that day
OPEN_ENTRY = (1, 20.20, 20.30, 20.10, 20.25)          # T <= open <= C: filled at the open, no exit that day
CEILING_ENTRY = (1, 20.40, 20.60, 20.24, 20.50)       # open > C, low through C: filled at C, no exit that day
NO_FILL = (19.50, 19.90, 19.40, 19.60)
QUIET = (20.00, 20.50, 19.50, 20.00)
QUIET40 = [(n,) + QUIET for n in range(2, 42)]        # sessions 1..40 after a fill on day(1)


def held(entry=TRIGGER_ENTRY, params=P0, **kw) -> F.Order:
    """A trade filled on session 1 (at T unless another entry bar is given) and still open."""
    o = feed(order(**kw), [bar(*entry)], params=params)
    assert o.state == F.OPEN
    return o


def after_40_sessions(entry=TRIGGER_ENTRY, params=P0) -> F.Order:
    o = feed(held(entry, params), [bar(*q) for q in QUIET40], params=params)
    assert (o.state, o.sessions_held) == (F.OPEN, 40)
    return o


class EntryTests(unittest.TestCase):
    """3.4 entry table."""

    def test_no_fill_below_trigger(self):
        o = feed(order(), [bar(1, 19.50, 19.99, 19.40, 19.60)])
        self.assertEqual((o.state, o.sessions_pending), (F.PENDING, 1))

    def test_intraday_trigger_fills_at_trigger_and_pays_h(self):
        o = held()
        self.assertEqual((o.entry_kind, o.entry_raw), (F.ENTRY_TRIGGER, 20.00))
        self.assertAlmostEqual(o.entry_cost, 0.04)
        self.assertEqual((o.entry_date, o.sessions_held), (day(1), 0))

    def test_trigger_fires_on_a_touch(self):
        o = feed(order(), [bar(1, 19.90, 20.00, 19.80, 19.95)])
        self.assertEqual((o.state, o.entry_kind, o.entry_raw), (F.OPEN, F.ENTRY_TRIGGER, 20.00))

    def test_open_equal_to_trigger_is_an_opening_fill_paying_2h(self):
        o = feed(order(), [bar(1, 20.00, 20.10, 19.90, 20.05)])
        self.assertEqual((o.entry_kind, o.entry_raw), (F.ENTRY_OPEN, 20.00))
        self.assertAlmostEqual(o.entry_cost, 0.08)

    def test_open_between_trigger_and_ceiling_fills_at_the_open(self):
        o = held(OPEN_ENTRY)
        self.assertEqual((o.entry_kind, o.entry_raw), (F.ENTRY_OPEN, 20.20))
        self.assertAlmostEqual(o.entry_cost, 2 * 0.002 * 20.20)

    def test_open_equal_to_ceiling_still_fills_at_the_open(self):
        o = feed(order(), [bar(1, 20.25, 20.30, 20.10, 20.20)])
        self.assertEqual((o.entry_kind, o.entry_raw), (F.ENTRY_OPEN, 20.25))
        self.assertAlmostEqual(o.entry_cost, 2 * 0.002 * 20.25)          # still an opening fill: 2h

    def test_an_open_just_above_the_ceiling_is_not_an_opening_fill(self):
        o = feed(order(), [bar(1, 20.26, 20.60, 20.25, 20.50)])          # resting at C, low only touches it
        self.assertEqual((o.state, o.cancel_reason), (F.CANCELED, F.CANCEL_TRIGGERED_UNFILLED))
        o = feed(order(), [bar(1, 20.26, 20.60, 20.24, 20.50)])
        self.assertEqual((o.entry_kind, o.entry_raw), (F.ENTRY_CEILING, 20.25))

    def test_gap_above_ceiling_without_trade_through_is_canceled_after_the_close(self):
        o = feed(order(), [bar(1, 20.40, 20.60, 20.25, 20.50)])          # low == C: a touch is not enough
        self.assertEqual((o.state, o.cancel_reason), (F.CANCELED, F.CANCEL_TRIGGERED_UNFILLED))
        self.assertFalse(o.is_trade)

    def test_a_gap_above_the_ceiling_is_canceled_even_if_the_close_comes_back_inside(self):
        o = feed(order(), [bar(1, 20.40, 20.60, 20.245, 20.25)])         # the low was never a full cent through C
        self.assertEqual((o.state, o.cancel_reason), (F.CANCELED, F.CANCEL_TRIGGERED_UNFILLED))

    def test_gap_above_ceiling_with_trade_through_fills_at_the_ceiling(self):
        o = held(CEILING_ENTRY)
        self.assertEqual((o.entry_kind, o.entry_raw), (F.ENTRY_CEILING, 20.25))
        self.assertAlmostEqual(o.entry_cost, 0.002 * 20.25)              # a limit fill pays h, not 2h

    def test_triggered_unfilled_order_does_not_come_back_the_next_day(self):
        o = feed(order(), [bar(1, 20.40, 20.60, 20.30, 20.50), bar(2, 19.90, 20.10, 19.80, 20.00)])
        self.assertEqual((o.state, o.cancel_reason, o.last_session), (F.CANCELED, F.CANCEL_TRIGGERED_UNFILLED, day(1)))


class EntrySessionExitTests(unittest.TestCase):
    """3.4 'Exits on the entry session'."""

    def test_stop_on_the_entry_session_after_an_opening_fill(self):
        o = feed(order(), [bar(1, 20.10, 20.20, 18.95, 19.10)])
        self.assertEqual((o.state, o.exit_kind, o.exit_raw, o.exit_date), (F.CLOSED, F.EXIT_STOP, 19.00, day(1)))
        self.assertAlmostEqual(F.r_multiple(o), (19.00 - 4 * 0.038) - (20.10 + 2 * 0.002 * 20.10))

    def test_stop_on_the_entry_session_after_an_intraday_trigger_is_assumed(self):
        # Spec 3.5 anchor 1: T 20.00, S 19.00, intraday trigger, intraday stop -> (19.00 - 0.152 - 20.04) = -1.192
        o = feed(order(), [bar(1, 19.50, 20.10, 18.90, 19.20)])
        self.assertEqual((o.entry_kind, o.exit_kind), (F.ENTRY_TRIGGER, F.EXIT_STOP))
        self.assertAlmostEqual(F.r_multiple(o), -1.192)

    def test_stop_on_the_entry_session_after_a_fill_at_the_ceiling(self):
        o = feed(order(), [bar(1, 20.40, 20.60, 18.95, 19.00)])
        self.assertEqual((o.entry_kind, o.exit_kind), (F.ENTRY_CEILING, F.EXIT_STOP))
        self.assertAlmostEqual(F.r_multiple(o), (19.00 - 4 * 0.038) - (20.25 + 0.002 * 20.25))

    def test_the_stop_fires_on_a_touch_after_an_intraday_trigger(self):
        o = feed(order(), [bar(1, 19.50, 20.10, 19.00, 19.20)])
        self.assertEqual((o.state, o.entry_kind, o.exit_kind, o.exit_raw), (F.CLOSED, F.ENTRY_TRIGGER, F.EXIT_STOP, 19.00))
        self.assertAlmostEqual(F.r_multiple(o), -1.192)

    def test_the_stop_fires_on_a_touch_after_an_opening_fill(self):
        o = feed(order(), [bar(1, 20.10, 20.20, 19.00, 19.10)])
        self.assertEqual((o.entry_kind, o.exit_kind, o.exit_raw), (F.ENTRY_OPEN, F.EXIT_STOP, 19.00))
        self.assertAlmostEqual(F.r_multiple(o), (19.00 - 4 * 0.038) - (20.10 + 2 * 0.002 * 20.10))

    def test_the_stop_fires_on_a_touch_after_a_fill_at_the_ceiling(self):
        o = feed(order(), [bar(1, 20.40, 20.60, 19.00, 19.05)])
        self.assertEqual((o.entry_kind, o.exit_kind, o.exit_raw), (F.ENTRY_CEILING, F.EXIT_STOP, 19.00))
        self.assertAlmostEqual(F.r_multiple(o), (19.00 - 4 * 0.038) - (20.25 + 0.002 * 20.25))

    def test_an_intraday_trigger_from_an_open_below_the_stop_is_stopped_at_s(self):
        o = feed(order(), [bar(1, 18.90, 20.10, 18.80, 19.50)])           # the low is assumed to follow the fill
        self.assertEqual((o.entry_kind, o.exit_kind, o.exit_raw), (F.ENTRY_TRIGGER, F.EXIT_STOP, 19.00))

    def test_target_on_the_entry_session_after_an_intraday_trigger(self):
        o = feed(order(), [bar(1, 19.90, 23.01, 19.80, 22.90)])
        self.assertEqual((o.state, o.exit_kind, o.exit_raw), (F.CLOSED, F.EXIT_TARGET, 23.00))
        self.assertAlmostEqual(F.r_multiple(o), (23.00 - 0.046) - 20.04)

    def test_target_on_the_entry_session_after_an_opening_fill(self):
        o = feed(order(), [bar(1, 20.10, 23.05, 20.00, 23.00)])
        self.assertEqual((o.entry_kind, o.exit_kind, o.exit_raw), (F.ENTRY_OPEN, F.EXIT_TARGET, 23.00))

    def test_target_needs_a_one_cent_trade_through(self):
        o = feed(order(), [bar(1, 19.90, 23.00, 19.80, 22.90)])           # high == P: no fill
        self.assertEqual(o.state, F.OPEN)

    def test_fill_at_ceiling_gets_no_target_credit_from_the_high_alone(self):
        o = feed(order(), [bar(1, 20.40, 23.50, 20.24, 22.00)])           # the high may predate the fill
        self.assertEqual((o.state, o.entry_kind), (F.OPEN, F.ENTRY_CEILING))

    def test_fill_at_ceiling_gets_target_credit_when_the_close_is_through(self):
        o = feed(order(), [bar(1, 20.40, 23.50, 20.24, 23.01)])
        self.assertEqual((o.state, o.exit_kind, o.exit_raw), (F.CLOSED, F.EXIT_TARGET, 23.00))
        o = feed(order(), [bar(1, 20.40, 23.50, 20.24, 23.00)])           # close == P: not through
        self.assertEqual(o.state, F.OPEN)

    def test_stop_wins_when_both_levels_print_after_an_intraday_trigger(self):
        o = feed(order(), [bar(1, 19.90, 23.50, 18.90, 21.00)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_STOP, 19.00))

    def test_stop_wins_when_both_levels_print_after_an_opening_fill(self):
        o = feed(order(), [bar(1, 20.10, 23.50, 18.90, 21.00)])
        self.assertEqual((o.entry_kind, o.exit_kind, o.exit_raw), (F.ENTRY_OPEN, F.EXIT_STOP, 19.00))
        self.assertAlmostEqual(F.r_multiple(o), (19.00 - 4 * 0.038) - (20.10 + 2 * 0.002 * 20.10))

    def test_stop_wins_when_both_levels_print_after_a_fill_at_the_ceiling(self):
        o = feed(order(), [bar(1, 20.40, 23.60, 18.90, 23.50)])           # the close is through P as well
        self.assertEqual((o.entry_kind, o.exit_kind, o.exit_raw), (F.ENTRY_CEILING, F.EXIT_STOP, 19.00))


class LaterSessionTests(unittest.TestCase):
    """3.4 'Later sessions, in order' 1-4."""

    def test_gap_through_the_stop_fills_at_the_open_and_pays_4h(self):
        # Spec 3.5 anchor 2: the same trade with a gap-through open at 18.80 -> (18.80 - 0.1504 - 20.04) = -1.3904
        o = feed(held(), [bar(2, 18.80, 18.90, 18.50, 18.60)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_GAP_STOP, 18.80))
        self.assertAlmostEqual(o.exit_cost, 0.1504)
        self.assertAlmostEqual(F.r_multiple(o), -1.3904)

    def test_open_exactly_at_the_stop_is_a_gap_through(self):
        o = feed(held(), [bar(2, 19.00, 19.20, 18.90, 19.10)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_GAP_STOP, 19.00))
        self.assertAlmostEqual(F.r_multiple(o), (19.00 - 4 * 0.038) - 20.04)

    def test_gap_past_the_target_fills_at_the_target_with_no_bonus(self):
        o = feed(held(), [bar(2, 24.00, 24.50, 23.80, 24.20)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TARGET, 23.00))
        self.assertAlmostEqual(o.exit_cost, 0.046)                    # a limit fill pays h
        self.assertAlmostEqual(F.r_multiple(o), 2.914)

    def test_a_gap_past_the_target_needs_the_one_cent_trade_through_at_the_open(self):
        # Rule 2 (ruling 2026-11-11): open >= P + 0.01. An open exactly at P is not a fill ...
        self.assertEqual(feed(held(), [bar(2, 23.00, 23.00, 22.50, 22.80)]).state, F.OPEN)
        # ... but the bar can still trade through P afterwards (rule 4): target at P, paying h.
        o = feed(held(), [bar(2, 23.00, 23.01, 22.50, 22.80)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TARGET, 23.00))
        self.assertAlmostEqual(F.r_multiple(o), 2.914)
        o = feed(held(), [bar(2, 23.01, 23.01, 22.50, 22.80)])        # the first open that is a gap past P
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TARGET, 23.00))
        self.assertAlmostEqual(F.r_multiple(o), 2.914)

    def test_an_open_at_the_target_can_still_be_stopped_later_in_the_bar(self):
        o = feed(held(), [bar(2, 23.00, 23.00, 18.90, 19.50)])        # no fill at the open; the low reaches S
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_STOP, 19.00))

    def test_gap_past_the_target_beats_a_later_trade_down_to_the_stop(self):
        o = feed(held(), [bar(2, 23.50, 23.60, 18.90, 19.00)])        # rule 2 before rule 3
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TARGET, 23.00))
        self.assertAlmostEqual(F.r_multiple(o), 2.914)

    def test_intraday_stop_fires_on_a_touch(self):
        o = feed(held(), [bar(2, 19.90, 20.00, 19.00, 19.50)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_STOP, 19.00))
        self.assertAlmostEqual(F.r_multiple(o), -1.192)

    def test_intraday_target_needs_a_trade_through(self):
        self.assertEqual(feed(held(), [bar(2, 22.00, 23.00, 21.90, 22.50)]).state, F.OPEN)
        o = feed(held(), [bar(2, 22.00, 23.01, 21.90, 22.50)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TARGET, 23.00))

    def test_stop_wins_when_both_levels_print_in_one_bar(self):
        o = feed(held(), [bar(2, 20.00, 23.50, 18.90, 20.00)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_STOP, 19.00))

    def test_a_quiet_session_changes_nothing_but_the_count(self):
        o = feed(held(), [bar(2, 20.00, 20.50, 19.50, 20.10)])
        self.assertEqual((o.state, o.sessions_held, o.last_session), (F.OPEN, 1, day(2)))

    def test_loss_from_a_fill_above_the_trigger_is_worse_than_one_r(self):
        o = feed(held(OPEN_ENTRY), [bar(2, 20.00, 20.10, 18.90, 19.00)])
        self.assertAlmostEqual(F.r_multiple(o), (19.00 - 4 * 0.038) - (20.20 + 0.0808))
        self.assertLess(F.r_multiple(o), -1.3)


class EntryKindLaterSessionTests(unittest.TestCase):
    """The later-session rules are the same whatever the entry path was (3.4)."""

    NET = {TRIGGER_ENTRY: 20.00 + 0.04, OPEN_ENTRY: 20.20 + 2 * 0.002 * 20.20, CEILING_ENTRY: 20.25 + 0.002 * 20.25}

    def test_a_fill_at_the_ceiling_is_credited_from_the_high_on_later_sessions(self):
        o = feed(held(CEILING_ENTRY), [bar(2, 21.00, 23.50, 20.90, 22.00)])    # close below P: the high is enough now
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TARGET, 23.00))
        self.assertAlmostEqual(F.r_multiple(o), (23.00 - 0.046) - self.NET[CEILING_ENTRY])

    def test_gap_through_the_stop_for_every_entry_kind(self):
        for entry, net in self.NET.items():
            o = feed(held(entry), [bar(2, 18.80, 18.90, 18.50, 18.60)])
            self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_GAP_STOP, 18.80))
            self.assertAlmostEqual(F.r_multiple(o), (18.80 - 0.1504) - net)

    def test_intraday_stop_for_every_entry_kind(self):
        for entry, net in self.NET.items():
            o = feed(held(entry), [bar(2, 19.90, 20.00, 19.00, 19.50)])
            self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_STOP, 19.00))
            self.assertAlmostEqual(F.r_multiple(o), (19.00 - 4 * 0.038) - net)

    def test_time_exit_for_every_entry_kind(self):
        for entry, net in self.NET.items():
            o = feed(after_40_sessions(entry), [bar(42, 20.30, 20.40, 20.20, 20.35)])
            self.assertEqual((o.exit_kind, o.exit_raw, o.sessions_held), (F.EXIT_TIME, 20.30, 41))
            self.assertAlmostEqual(F.r_multiple(o), (20.30 - 2 * 0.002 * 20.30) - net)


class TimeExitTests(unittest.TestCase):
    """3.4 'Time exit': sold at the open of session 41, with the OCO rules applied first."""

    def test_still_open_after_session_40_is_sold_at_the_open_of_session_41(self):
        o = feed(after_40_sessions(), [bar(42, 20.30, 20.40, 20.20, 20.35)])
        self.assertEqual((o.exit_kind, o.exit_raw, o.exit_date, o.sessions_held), (F.EXIT_TIME, 20.30, day(42), 41))
        self.assertAlmostEqual(o.exit_cost, 2 * 0.002 * 20.30)          # an opening fill pays 2h

    def test_time_exit_is_at_the_open_even_if_the_bar_later_hits_the_stop(self):
        o = feed(after_40_sessions(), [bar(42, 20.30, 20.40, 18.50, 18.60)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TIME, 20.30))

    def test_time_exit_is_at_the_open_even_if_the_bar_later_reaches_the_target(self):
        o = feed(after_40_sessions(), [bar(42, 20.30, 23.50, 20.20, 23.40)])
        self.assertEqual((o.exit_kind, o.exit_raw, o.sessions_held), (F.EXIT_TIME, 20.30, 41))
        self.assertAlmostEqual(F.r_multiple(o), (20.30 - 2 * 0.002 * 20.30) - 20.04)

    def test_oco_applies_first_on_session_41_stop(self):
        o = feed(after_40_sessions(), [bar(42, 18.90, 19.00, 18.50, 18.60)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_GAP_STOP, 18.90))

    def test_oco_applies_first_on_session_41_target_so_the_3r_cap_is_exact(self):
        o = feed(after_40_sessions(), [bar(42, 23.40, 23.60, 23.30, 23.50)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TARGET, 23.00))
        self.assertLess(F.r_multiple(o), 3.0)

    def test_session_41_opening_exactly_at_the_target_is_a_time_exit_at_that_open(self):
        o = feed(after_40_sessions(), [bar(42, 23.00, 23.50, 22.90, 23.40)])   # not a gap past P: sold at the open
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TIME, 23.00))
        self.assertAlmostEqual(F.r_multiple(o), (23.00 - 2 * 0.046) - 20.04)
        self.assertLess(F.r_multiple(o), 3.0)

    def test_session_40_itself_is_an_ordinary_session(self):
        o = feed(held(), [bar(*q) for q in QUIET40[:-1]])                   # sessions 1..39
        o = feed(o, [bar(41, 20.30, 20.40, 20.20, 20.35)])                  # session 40: no time exit yet
        self.assertEqual((o.state, o.sessions_held), (F.OPEN, 40))

    def test_missing_bars_count_toward_the_hold(self):
        bars = [bar(n, *QUIET) if n % 5 else n for n in range(2, 42)]       # every fifth session has no bar
        o = feed(held(), bars)
        self.assertEqual((o.state, o.sessions_held), (F.OPEN, 40))
        o = feed(o, [bar(42, 20.30, 20.40, 20.20, 20.35)])
        self.assertEqual((o.exit_kind, o.exit_date), (F.EXIT_TIME, day(42)))

    def test_time_exit_on_a_missing_bar_happens_at_the_next_bars_open(self):
        o = feed(after_40_sessions(), [42])
        self.assertEqual((o.state, o.sessions_held), (F.OPEN, 41))
        o = feed(o, [bar(43, 20.10, 20.20, 20.00, 20.15)])
        self.assertEqual((o.exit_kind, o.exit_raw, o.exit_date, o.sessions_held), (F.EXIT_TIME, 20.10, day(43), 42))

    def test_a_delayed_time_exit_still_applies_the_oco_first(self):
        o = feed(after_40_sessions(), [42, bar(43, 24.00, 24.50, 23.80, 24.20)])    # the next bar gaps past P
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TARGET, 23.00))
        self.assertAlmostEqual(F.r_multiple(o), 2.914)
        o = feed(after_40_sessions(), [42, bar(43, 18.50, 18.60, 18.40, 18.45)])    # the next bar gaps through S
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_GAP_STOP, 18.50))

    def test_a_delayed_time_exit_is_at_the_open_whatever_the_bar_does_later(self):
        for later in ((20.10, 20.20, 18.50, 19.00), (20.10, 23.50, 20.00, 23.40), (20.10, 23.50, 18.50, 20.00)):
            o = feed(after_40_sessions(), [42, bar(43, *later)])
            self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TIME, 20.10))

    def test_every_missing_session_counts_even_after_session_40(self):
        o = feed(after_40_sessions(), [42, 43])
        self.assertEqual((o.state, o.sessions_held), (F.OPEN, 42))
        o = feed(o, [bar(44, 20.10, 20.20, 20.00, 20.15)])
        self.assertEqual((o.exit_kind, o.sessions_held), (F.EXIT_TIME, 43))

    def test_a_time_exit_whose_bar_never_arrives_is_marked_like_any_open_trade(self):
        o = feed(after_40_sessions(), [42])
        ev = F.evaluate_at_cutoff(o, day(42), 20.00, P0)                    # the latest earlier close
        self.assertEqual(ev.status, "marked")
        self.assertAlmostEqual(ev.r, (20.00 - 0.04) - 20.04)

    def test_a_missing_bar_then_a_gap_through_fills_at_that_open(self):
        o = feed(held(), [2, bar(3, 18.00, 18.20, 17.90, 18.10)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_GAP_STOP, 18.00))

    def test_weak_breadth_does_not_stop_the_hold_clock(self):
        o = feed(held(), [bar(*q) for q in QUIET40], breadth=[False] * 40)
        self.assertEqual((o.state, o.sessions_held), (F.OPEN, 40))
        o = feed(o, [bar(42, 20.30, 20.40, 20.20, 20.35)], breadth=[False])
        self.assertEqual((o.exit_kind, o.sessions_held), (F.EXIT_TIME, 41))


class PendingLifecycleTests(unittest.TestCase):
    """3.2 windows and cancels; 3.3 breadth cancel."""

    def test_m1_window_of_three_sessions_then_expired(self):
        o = feed(order(window=3), [bar(1, *NO_FILL), bar(2, *NO_FILL)])
        self.assertEqual(o.state, F.PENDING)
        o = feed(o, [bar(3, *NO_FILL)])
        self.assertEqual((o.state, o.sessions_pending, o.is_trade), (F.EXPIRED, 3, False))

    def test_m2_window_of_five_sessions(self):
        o = feed(order(window=5), [bar(n, *NO_FILL) for n in range(1, 5)])
        self.assertEqual(o.state, F.PENDING)
        self.assertEqual(feed(o, [bar(5, *NO_FILL)]).state, F.EXPIRED)

    def test_a_fill_on_the_last_window_session_counts(self):
        o = feed(order(window=3), [bar(1, *NO_FILL), bar(2, *NO_FILL), bar(3, 19.80, 20.10, 19.70, 20.05)])
        self.assertEqual((o.state, o.entry_date), (F.OPEN, day(3)))

    def test_an_expired_order_ignores_later_sessions(self):
        o = feed(order(window=1), [bar(1, *NO_FILL), bar(2, 19.80, 20.10, 19.70, 20.05)])
        self.assertEqual((o.state, o.last_session), (F.EXPIRED, day(1)))

    def test_a_close_below_the_structure_cancels_the_pending_order(self):
        o = feed(order(invalidation=19.40), [bar(1, 19.60, 19.80, 19.30, 19.39)])
        self.assertEqual((o.state, o.cancel_reason), (F.CANCELED, F.CANCEL_INVALIDATED))

    def test_a_close_at_the_structure_does_not_cancel(self):
        o = feed(order(invalidation=19.40), [bar(1, 19.60, 19.80, 19.30, 19.40)])
        self.assertEqual(o.state, F.PENDING)

    def test_invalidation_never_touches_a_filled_trade(self):
        o = feed(order(invalidation=19.40), [bar(1, 19.80, 20.10, 19.30, 19.35)])
        self.assertEqual(o.state, F.OPEN)                             # filled at T; low 19.30 > S
        o = feed(o, [bar(2, 19.60, 19.80, 19.30, 19.35)])             # a later close below the structure
        self.assertEqual((o.state, o.sessions_held), (F.OPEN, 1))

    def test_breadth_below_half_cancels_an_unfilled_order_at_that_close(self):
        o = feed(order(), [bar(1, *NO_FILL)], breadth=[False])
        self.assertEqual((o.state, o.cancel_reason), (F.CANCELED, F.CANCEL_BREADTH))

    def test_a_fill_on_a_session_whose_own_close_has_weak_breadth_stands(self):
        # The gate is breadth at the PRIOR close; this session's breadth governs tomorrow's fills.
        o = feed(order(), [bar(*TRIGGER_ENTRY)], breadth=[False])
        self.assertEqual(o.state, F.OPEN)

    def test_a_fill_on_a_later_window_session_ignores_that_sessions_breadth_too(self):
        o = feed(order(), [bar(1, *NO_FILL), bar(2, 19.80, 20.10, 19.70, 20.05)], breadth=[True, False])
        self.assertEqual((o.state, o.entry_date), (F.OPEN, day(2)))

    def test_an_open_trade_ignores_a_weak_breadth_close(self):
        o = feed(held(), [bar(2, 20.00, 20.50, 19.50, 20.10)], breadth=[False])
        self.assertEqual((o.state, o.sessions_held, o.cancel_reason), (F.OPEN, 1, None))

    def test_missing_bars_count_toward_the_entry_window(self):
        o = feed(order(window=3), [1, 2])
        self.assertEqual((o.state, o.sessions_pending, o.last_session), (F.PENDING, 2, day(2)))
        self.assertEqual(feed(o, [3]).state, F.EXPIRED)

    def test_a_missing_bar_neither_fills_nor_invalidates(self):
        o = feed(order(invalidation=19.40), [1])
        self.assertEqual((o.state, o.sessions_pending), (F.PENDING, 1))
        o = feed(o, [bar(2, 19.60, 19.80, 19.30, 19.39)])
        self.assertEqual((o.state, o.cancel_reason), (F.CANCELED, F.CANCEL_INVALIDATED))

    def test_breadth_cancels_even_when_the_bar_is_missing(self):
        o = feed(order(), [1], breadth=[False])
        self.assertEqual((o.state, o.cancel_reason), (F.CANCELED, F.CANCEL_BREADTH))

    def test_the_cancel_rules_apply_on_every_window_session_not_only_the_first(self):
        quiet = bar(1, 19.50, 19.90, 19.45, 19.60)
        inside = bar(3, 20.10, 20.30, 20.00, 20.20)                   # would be an opening fill
        new = lambda: feed(order(window=5, invalidation=19.40), [quiet])
        o = feed(new(), [bar(2, 19.50, 19.90, 19.45, 19.60), inside], breadth=[False, True])
        self.assertEqual((o.state, o.cancel_reason, o.entry_date), (F.CANCELED, F.CANCEL_BREADTH, None))
        o = feed(new(), [bar(2, 19.50, 19.90, 19.30, 19.39), inside])
        self.assertEqual((o.state, o.cancel_reason, o.entry_date), (F.CANCELED, F.CANCEL_INVALIDATED, None))
        o = feed(new(), [bar(2, 20.40, 20.60, 20.30, 20.50), inside])
        self.assertEqual((o.state, o.cancel_reason, o.entry_date), (F.CANCELED, F.CANCEL_TRIGGERED_UNFILLED, None))

    def test_terminal_orders_never_change(self):
        closed = feed(held(), [bar(2, 18.80, 18.90, 18.50, 18.60)])
        self.assertEqual(feed(closed, [bar(3, 25.0, 26.0, 24.0, 25.5)]), closed)
        self.assertEqual(feed(closed, [bar(2, 25.0, 26.0, 24.0, 25.5)]), closed)

    def test_a_replaced_order_is_dead_and_can_no_longer_fill(self):
        c = F.cancel(order(), F.CANCEL_REPLACED)
        self.assertEqual((c.state, c.cancel_reason, c.is_trade), (F.CANCELED, F.CANCEL_REPLACED, False))
        self.assertEqual(feed(c, [bar(*TRIGGER_ENTRY)]), c)

    def test_cancel_only_applies_to_pending_orders_and_known_reasons(self):
        with self.assertRaises(ValueError):
            F.cancel(held(), F.CANCEL_REPLACED)
        with self.assertRaises(ValueError):
            F.cancel(order(), "because")

    def test_is_trade_means_filled(self):
        self.assertFalse(order().is_trade)
        self.assertFalse(feed(order(), [bar(1, *NO_FILL)]).is_trade)
        self.assertTrue(held().is_trade)
        self.assertTrue(feed(held(), [bar(2, 18.80, 18.90, 18.50, 18.60)]).is_trade)

    def test_run_matches_step_by_step_and_stops_at_the_exit(self):
        bars = [bar(1, *NO_FILL), bar(2, 19.80, 20.10, 19.70, 20.05), bar(3, 18.80, 18.90, 18.50, 18.60),
                bar(4, 30.0, 31.0, 29.0, 30.5)]
        ran = F.run(order(), [(b.date, b, True) for b in bars], params=P0)
        self.assertEqual(ran, feed(order(), bars[:3]))
        self.assertEqual((ran.exit_kind, ran.last_session), (F.EXIT_GAP_STOP, day(3)))

    def test_run_never_touches_a_session_after_the_exit(self):
        sealed = dt.date(2025, 1, 2)                                   # stepping this session would raise
        ran = F.run(order(), [(day(1), bar(*TRIGGER_ENTRY), True), (day(2), bar(2, 18.80, 18.90, 18.50, 18.60), True),
                              (sealed, None, True)], params=P0)
        self.assertEqual((ran.state, ran.exit_date), (F.CLOSED, day(2)))

    def test_run_cancels_on_a_weak_breadth_close(self):
        ran = F.run(order(), [(day(1), bar(1, *NO_FILL), False), (day(2), bar(2, 19.80, 20.10, 19.70, 20.05), True)],
                    params=P0)
        self.assertEqual((ran.state, ran.cancel_reason, ran.last_session), (F.CANCELED, F.CANCEL_BREADTH, day(1)))


class CancelReasonTests(unittest.TestCase):
    """3.4 table, open > C: 'the nightly prints CANCEL "triggered-unfilled"'. The spec gives no order for
    the other coincidences; these pin the one the module documents."""

    def test_triggered_unfilled_is_the_reason_even_on_the_last_window_session(self):
        o = feed(order(window=1), [bar(1, 20.40, 20.60, 20.30, 20.50)])
        self.assertEqual((o.state, o.cancel_reason), (F.CANCELED, F.CANCEL_TRIGGERED_UNFILLED))

    def test_triggered_unfilled_beats_invalidation(self):
        # Only possible within a cent of the trigger: T = C = 20.00, structure at 19.995. The bar gaps
        # above C, never trades a full cent back through it, and closes below the structure.
        o = feed(order(ceiling=20.00, invalidation=19.995), [bar(1, 20.40, 20.60, 19.992, 19.993)])
        self.assertEqual((o.state, o.cancel_reason), (F.CANCELED, F.CANCEL_TRIGGERED_UNFILLED))

    def test_triggered_unfilled_beats_breadth(self):
        o = feed(order(), [bar(1, 20.40, 20.60, 20.30, 20.50)], breadth=[False])
        self.assertEqual((o.state, o.cancel_reason), (F.CANCELED, F.CANCEL_TRIGGERED_UNFILLED))

    def test_invalidation_beats_breadth(self):
        o = feed(order(invalidation=19.40), [bar(1, 19.60, 19.80, 19.30, 19.39)], breadth=[False])
        self.assertEqual((o.state, o.cancel_reason), (F.CANCELED, F.CANCEL_INVALIDATED))

    def test_breadth_beats_expiry(self):
        o = feed(order(window=1), [bar(1, *NO_FILL)], breadth=[False])
        self.assertEqual((o.state, o.cancel_reason), (F.CANCELED, F.CANCEL_BREADTH))

    def test_invalidation_beats_expiry(self):
        o = feed(order(window=1, invalidation=19.40), [bar(1, 19.60, 19.80, 19.30, 19.39)])
        self.assertEqual((o.state, o.cancel_reason), (F.CANCELED, F.CANCEL_INVALIDATED))


class SessionOrderTests(unittest.TestCase):
    """Section 4: the tracker is idempotent, keyed by session. The model consumes each session once, in
    order; a re-run rebuilds the order from its signal day."""

    def step(self, o, n, b):
        return F.step(o, day(n), b, breadth_ok=True, params=P0)

    def test_a_session_cannot_be_consumed_twice(self):
        p = feed(order(), [bar(1, *NO_FILL)])
        for again in (bar(1, *NO_FILL), bar(1, 19.80, 20.10, 19.70, 20.05), None):
            with self.assertRaises(ValueError):
                self.step(p, 1, again)
        h = held()
        for again in (bar(*TRIGGER_ENTRY), bar(1, 1.0, 50.0, 1.0, 25.0), None):
            with self.assertRaises(ValueError):
                self.step(h, 1, again)

    def test_a_session_consumed_without_a_bar_cannot_be_given_one_later(self):
        p = self.step(order(), 1, None)
        self.assertEqual((p.sessions_pending, p.last_session), (1, day(1)))
        with self.assertRaises(ValueError):
            self.step(p, 1, bar(1, 19.80, 20.10, 19.70, 20.05))
        h = self.step(held(), 2, None)
        self.assertEqual((h.sessions_held, h.last_session), (1, day(2)))
        with self.assertRaises(ValueError):
            self.step(h, 2, bar(2, 18.80, 18.90, 18.50, 18.60))

    def test_a_recomputed_breadth_figure_cannot_be_slipped_into_a_consumed_session(self):
        p = feed(order(), [bar(1, *NO_FILL)])
        with self.assertRaises(ValueError):
            F.step(p, day(1), bar(1, *NO_FILL), breadth_ok=False, params=P0)

    def test_an_earlier_session_is_an_error(self):
        o = feed(held(), [bar(2, 20.00, 20.50, 19.50, 20.10)])
        with self.assertRaises(ValueError):
            self.step(o, 1, bar(*TRIGGER_ENTRY))

    def test_a_late_bar_is_applied_by_rebuilding_from_the_signal_day(self):
        rebound = bar(3, 19.50, 19.80, 19.40, 19.60)
        live = feed(held(), [2, rebound])                             # session 2 had no bar when the tracker ran
        self.assertEqual(live.state, F.OPEN)
        gap = bar(2, 18.80, 18.90, 18.50, 18.60)                      # ... and it shows a gap through S
        rebuilt = F.run(order(), [(day(1), bar(*TRIGGER_ENTRY), True), (day(2), gap, True), (day(3), rebound, True)],
                        params=P0)
        self.assertEqual((rebuilt.exit_kind, rebuilt.exit_date), (F.EXIT_GAP_STOP, day(2)))
        self.assertAlmostEqual(F.r_multiple(rebuilt), -1.3904)

    def test_an_order_cannot_act_on_its_signal_day(self):
        with self.assertRaises(ValueError):
            F.step(order(), SIGNAL_DAY, F.Bar(SIGNAL_DAY, 19.8, 20.1, 19.7, 20.0), breadth_ok=True, params=P0)

    def test_a_bar_for_the_wrong_session_is_an_error(self):
        with self.assertRaises(ValueError):
            self.step(order(), 2, bar(1, 19.8, 20.1, 19.7, 20.0))

    def test_the_model_is_deterministic(self):
        bars = InvariantTests.random_path(random.Random(7))
        once = lambda: F.run(order(window=5), [(b.date, b, True) for b in bars], params=P0)
        self.assertEqual(once(), once())


class OosSealTests(unittest.TestCase):
    """3.7 step 2: until a committed pick exists, fills.py refuses to evaluate any session from
    2025-01-02 to 2026-10-30."""

    def one(self, signal: dt.date, session: dt.date, params=P0, **kw) -> F.Order:
        return F.step(order(signal_date=signal), session, F.Bar(session, 19.80, 20.10, 19.70, 20.05),
                      breadth_ok=True, params=params, **kw)

    def test_the_last_in_sample_session_runs(self):
        self.assertEqual(self.one(dt.date(2024, 12, 30), dt.date(2024, 12, 31)).state, F.OPEN)

    def test_sealed_sessions_are_refused_by_default(self):
        for signal, session in ((dt.date(2024, 12, 31), dt.date(2025, 1, 2)),
                                (dt.date(2026, 6, 1), dt.date(2026, 6, 2)),
                                (dt.date(2026, 10, 29), dt.date(2026, 10, 30))):
            with self.assertRaises(F.SealedSessionError):
                self.one(signal, session)
            with self.assertRaises(F.SealedSessionError):
                self.one(signal, session, seal=F.SEALED)

    def test_the_first_session_after_the_window_runs(self):
        self.assertEqual(self.one(dt.date(2026, 10, 30), dt.date(2026, 11, 2)).state, F.OPEN)

    def test_an_unseal_has_to_be_one_of_the_two_named_ones(self):
        self.assertEqual(self.one(dt.date(2026, 6, 1), dt.date(2026, 6, 2), seal=F.UNSEALED_BY_PICK).state, F.OPEN)
        for seal in (True, False, None, "open", ""):
            with self.assertRaises(ValueError):
                self.one(dt.date(2026, 6, 1), dt.date(2026, 6, 2), seal=seal)

    def known(self, ticker, signal, session, trigger, stop, **kw):
        o = F.Order(ticker=ticker, signal_date=signal, trigger=trigger, ceiling=trigger, stop=stop, target=3 * trigger,
                    window=1, atr=0.5, tier_bps=20.0)
        b = F.Bar(session, trigger, trigger + 0.05, trigger - 0.05, trigger)
        return F.step(o, session, b, breadth_ok=True, params=P0, **kw)

    def test_the_known_answer_exemption_covers_only_the_14_real_records_and_their_bars(self):
        ka = F.KNOWN_ANSWER_REPLAY
        # CXM's real record: entry 2026-06-09 at 5.33, stop 5.00, out on 2026-06-18 (ruling 2026-11-11)
        self.assertEqual(self.known("CXM", dt.date(2026, 6, 8), dt.date(2026, 6, 9), 5.33, 5.00, seal=ka).state, F.OPEN)
        refused = [("TEST", dt.date(2026, 6, 8), dt.date(2026, 6, 9), 5.33, 5.00),     # not one of the 14 names
                   ("CXM", dt.date(2026, 6, 5), dt.date(2026, 6, 8), 5.33, 5.00),      # the session before its entry day
                   ("CXM", dt.date(2026, 6, 17), dt.date(2026, 6, 18), 5.33, 5.00),    # pending on a day that is not the entry day
                   ("CXM", dt.date(2026, 6, 18), dt.date(2026, 6, 19), 5.33, 5.00),    # the session after its exit day
                   ("CXM", dt.date(2026, 6, 8), dt.date(2026, 6, 9), 5.34, 5.00),      # not its real entry
                   ("CXM", dt.date(2026, 6, 8), dt.date(2026, 6, 9), 5.33, 4.99),      # not its real stop
                   ("CXM", dt.date(2025, 6, 8), dt.date(2025, 6, 9), 5.33, 5.00)]      # another year
        for args in refused:
            with self.assertRaises(F.SealedSessionError):
                self.known(*args, seal=ka)
        # outside the sealed window the exemption changes nothing
        self.assertEqual(self.known("TEST", dt.date(2026, 10, 30), dt.date(2026, 11, 2), 5.33, 5.00, seal=ka).state, F.OPEN)

    def test_a_string_or_a_look_alike_object_never_unseals(self):
        for seal in ("unsealed_by_pick", "known_answer_replay", "UNSEALED_BY_PICK", "sealed",
                     type(F.SEALED)("unsealed-by-pick"), type(F.SEALED)("known-answer")):
            with self.subTest(seal=seal):
                with self.assertRaises(ValueError):
                    self.one(dt.date(2026, 6, 1), dt.date(2026, 6, 2), seal=seal)

    def test_a_seal_cannot_be_serialized_or_rebuilt(self):
        import copy
        import pickle
        for seal in (F.SEALED, F.UNSEALED_BY_PICK, F.KNOWN_ANSWER_REPLAY):
            with self.assertRaises(TypeError):
                pickle.dumps(seal)
            with self.assertRaises(TypeError):
                copy.deepcopy(seal)

    def test_params_with_another_window_cannot_open_the_spec_window(self):
        sealed_sessions = ((dt.date(2024, 12, 31), dt.date(2025, 1, 2)), (dt.date(2025, 6, 2), dt.date(2025, 6, 3)),
                           (dt.date(2026, 10, 29), dt.date(2026, 10, 30)))
        for moved in (replace(P0, oos_start="1900-01-01", oos_end="1900-01-01"),
                      replace(P0, oos_start="2099-01-01", oos_end="2099-12-31")):
            for signal, session in sealed_sessions:
                with self.subTest(window=(moved.oos_start, moved.oos_end), session=session):
                    with self.assertRaises(F.SealedSessionError):
                        self.one(signal, session, params=moved)
            self.assertEqual(self.one(dt.date(2026, 10, 30), dt.date(2026, 11, 2), params=moved).state, F.OPEN)

    def test_an_inverted_window_is_an_error(self):
        with self.assertRaises(ValueError):
            self.one(dt.date(2023, 1, 9), dt.date(2023, 1, 10), params=replace(P0, oos_start="2026-10-30", oos_end="2025-01-02"))

    def test_run_is_sealed_too(self):
        d = dt.date(2025, 1, 2)
        sessions = [(d, F.Bar(d, 19.80, 20.10, 19.70, 20.05), True)]
        with self.assertRaises(F.SealedSessionError):
            F.run(order(signal_date=dt.date(2024, 12, 31)), sessions, params=P0)
        ran = F.run(order(signal_date=dt.date(2024, 12, 31)), sessions, params=P0, seal=F.UNSEALED_BY_PICK)
        self.assertEqual(ran.state, F.OPEN)

    def test_a_finished_order_is_refused_a_sealed_session_like_any_other(self):
        closed = feed(held(), [bar(2, 18.80, 18.90, 18.50, 18.60)])
        with self.assertRaises(F.SealedSessionError):
            F.step(closed, dt.date(2025, 3, 3), None, breadth_ok=True, params=P0)

    def test_the_window_is_read_from_params(self):
        only_day_1 = replace(P0, oos_start=day(1).isoformat(), oos_end=day(1).isoformat())
        with self.assertRaises(F.SealedSessionError) as refused:
            feed(order(), [bar(*TRIGGER_ENTRY)], params=only_day_1)
        self.assertIn(f"window {day(1)}..{day(1)} (the params window) (spec", str(refused.exception))
        with self.assertRaises(F.SealedSessionError) as refused:
            self.one(dt.date(2026, 6, 1), dt.date(2026, 6, 2), params=only_day_1)
        self.assertIn("window 2025-01-02..2026-10-30 (spec", str(refused.exception))      # the window that matched
        only_day_2 = replace(P0, oos_start=day(2).isoformat(), oos_end=day(2).isoformat())
        self.assertEqual(feed(order(), [bar(*TRIGGER_ENTRY)], params=only_day_2).state, F.OPEN)
        self.assertEqual((PARAMS.oos_start, PARAMS.oos_end), ("2025-01-02", "2026-10-30"))


class SealScopeTests(unittest.TestCase):
    """3.7 step 2 and ruling 2026-11-11: the exemption covers exact replays of the 14 records, entry day to exit day;
    and the seal holds for a trade that is already open."""

    def known(self, ticker, signal, session, trigger, stop, seal=F.KNOWN_ANSWER_REPLAY):
        o = F.Order(ticker=ticker, signal_date=signal, trigger=trigger, ceiling=trigger, stop=stop, target=3 * trigger,
                    window=1, atr=0.5, tier_bps=20.0)
        b = F.Bar(session, trigger, trigger + 0.05, trigger - 0.05, trigger)
        return F.step(o, session, b, breadth_ok=True, params=P0, seal=seal)

    def test_a_price_a_fraction_of_a_cent_off_the_record_is_refused(self):
        d = dt.date
        for args in (("CXM", d(2026, 6, 8), d(2026, 6, 9), 5.335, 5.00), ("CXM", d(2026, 6, 8), d(2026, 6, 9), 5.33, 5.004),
                     ("AEO", d(2026, 7, 30), d(2026, 7, 31), 17.08, 16.55), ("AEO", d(2026, 7, 30), d(2026, 7, 31), 17.07, 16.55)):
            with self.subTest(args=args):
                with self.assertRaises(F.SealedSessionError):
                    self.known(*args)
        self.assertEqual(self.known("AEO", d(2026, 7, 30), d(2026, 7, 31), 17.075, 16.55).state, F.OPEN)   # the real record

    def test_an_in_sample_trade_still_open_is_refused_the_first_sealed_session(self):
        last_is, first_oos = dt.date(2024, 12, 31), dt.date(2025, 1, 2)
        o = F.step(order(signal_date=dt.date(2024, 12, 30)), last_is, F.Bar(last_is, 19.80, 20.10, 19.70, 20.05),
                   breadth_ok=True, params=P0)
        self.assertEqual(o.state, F.OPEN)
        with self.assertRaises(F.SealedSessionError):
            F.step(o, first_oos, F.Bar(first_oos, 20.00, 20.50, 19.50, 20.10), breadth_ok=True, params=P0)
        with self.assertRaises(F.SealedSessionError):
            F.step(o, first_oos, None, breadth_ok=True, params=P0)
        with self.assertRaises(F.SealedSessionError):
            F.evaluate_at_cutoff(o, first_oos, 20.10, P0)                               # nor marked there


class SubCentPriceTests(unittest.TestCase):
    """3.4: 'low <= C - 0.01', 'high >= P + 0.01', 'close >= P + 0.01'; stops and triggers fire on a touch.
    Real Schwab bars are off the cent grid (the known-answer fixture has a high of 30.8999; B1 saw a
    close of 168.795633)."""

    def test_low_just_short_of_a_cent_through_the_ceiling(self):
        for low in (20.2401, 20.245, 20.240001):
            o = feed(order(), [bar(1, 20.40, 20.60, low, 20.50)])
            self.assertEqual((o.state, o.cancel_reason), (F.CANCELED, F.CANCEL_TRIGGERED_UNFILLED))

    def test_high_just_short_of_a_cent_through_the_target_on_the_entry_session(self):
        for high in (23.0099, 23.0051, 23.009999):
            o = feed(order(), [bar(1, 19.90, high, 19.80, 22.90)])
            self.assertEqual((o.state, o.entry_kind), (F.OPEN, F.ENTRY_TRIGGER))

    def test_close_just_short_of_a_cent_through_the_target_after_a_fill_at_the_ceiling(self):
        o = feed(order(), [bar(1, 20.40, 23.50, 20.24, 23.0099)])
        self.assertEqual((o.state, o.entry_kind), (F.OPEN, F.ENTRY_CEILING))

    def test_high_just_short_of_a_cent_through_the_target_on_a_later_session(self):
        self.assertEqual(feed(held(), [bar(2, 22.00, 23.0099, 21.90, 22.50)]).state, F.OPEN)

    def test_open_a_fraction_above_the_ceiling_is_not_an_opening_fill(self):
        o = feed(order(), [bar(1, 20.2501, 20.60, 20.2401, 20.50)])
        self.assertEqual((o.state, o.cancel_reason), (F.CANCELED, F.CANCEL_TRIGGERED_UNFILLED))
        o = feed(order(), [bar(1, 20.2501, 20.60, 20.24, 20.50)])
        self.assertEqual((o.entry_kind, o.entry_raw), (F.ENTRY_CEILING, 20.25))

    def test_a_hair_above_the_stop_is_not_a_stop(self):
        self.assertEqual(feed(order(), [bar(1, 19.90, 20.10, 19.0001, 19.50)]).state, F.OPEN)
        self.assertEqual(feed(held(), [bar(2, 19.90, 20.00, 19.000004, 19.50)]).state, F.OPEN)
        self.assertEqual(feed(held(), [bar(2, 19.000004, 19.50, 19.000004, 19.40)]).state, F.OPEN)   # not a gap-through

    def test_a_hair_below_the_trigger_is_not_a_trigger(self):
        self.assertEqual(feed(order(), [bar(1, 19.90, 19.9999, 19.80, 19.95)]).state, F.PENDING)
        self.assertEqual(feed(order(), [bar(1, 19.90, 19.999996, 19.80, 19.95)]).state, F.PENDING)
        self.assertEqual(feed(order(), [bar(1, 19.9999, 20.10, 19.90, 20.05)]).entry_kind, F.ENTRY_TRIGGER)

    def test_an_open_short_of_a_cent_through_the_target_is_not_a_gap_past_it(self):
        for open_ in (22.999996, 23.0000, 23.005, 23.009999):          # all short of P + 0.01
            o = feed(held(), [bar(2, open_, 23.009999, 22.90, 22.95)])
            self.assertEqual(o.state, F.OPEN)
        o = feed(held(), [bar(2, 23.010000, 23.02, 22.90, 22.95)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TARGET, 23.00))

    def test_a_close_a_hair_below_the_structure_cancels(self):
        o = feed(order(invalidation=19.40), [bar(1, 19.60, 19.80, 19.30, 19.399996)])
        self.assertEqual((o.state, o.cancel_reason), (F.CANCELED, F.CANCEL_INVALIDATED))


class ExactCentBoundaryTests(unittest.TestCase):
    """The one-cent trade-through must hold exactly for every level. T 20.08, S 19.00 -> P = T + 3(T - S)
    = 23.32; ATR 0.64 -> C = 20.24. In binary floating point 23.32 + 0.01 > 23.33 and 20.24 - 0.01 < 20.23."""

    LEVELS = dict(trigger=20.08, ceiling=20.24, stop=19.00, target=23.32, atr=0.64)

    def test_fill_at_the_ceiling_exactly_one_cent_through(self):
        o = feed(order(**self.LEVELS), [bar(1, 20.40, 20.60, 20.23, 20.50)])
        self.assertEqual((o.state, o.entry_kind, o.entry_raw), (F.OPEN, F.ENTRY_CEILING, 20.24))

    def test_target_exactly_one_cent_through_on_the_entry_session(self):
        o = feed(order(**self.LEVELS), [bar(1, 19.90, 23.33, 19.80, 22.90)])
        self.assertEqual((o.state, o.exit_kind, o.exit_raw), (F.CLOSED, F.EXIT_TARGET, 23.32))

    def test_target_exactly_one_cent_through_on_a_later_session(self):
        o = feed(order(**self.LEVELS), [bar(1, 19.90, 20.10, 19.80, 20.05), bar(2, 22.00, 23.33, 21.90, 22.50)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TARGET, 23.32))

    def test_close_exactly_one_cent_through_after_a_fill_at_the_ceiling(self):
        o = feed(order(**self.LEVELS), [bar(1, 20.40, 23.50, 20.23, 23.33)])
        self.assertEqual((o.entry_kind, o.exit_kind), (F.ENTRY_CEILING, F.EXIT_TARGET))

    def test_float_built_levels_compare_as_their_decimal_values(self):
        o = order(trigger=64.12 + 0.01, ceiling=64.95, stop=57.55, target=83.87, atr=3.3)   # 64.13000000000001
        self.assertEqual(feed(o, [bar(1, 64.13, 64.13, 64.00, 64.05)]).entry_kind, F.ENTRY_OPEN)
        o = order(trigger=5.01, ceiling=5.06, stop=4.85, target=5.49, atr=0.2)
        self.assertEqual(feed(o, [bar(1, 5.10, 5.12, 5.05, 5.08)]).entry_kind, F.ENTRY_CEILING)   # low == C - 0.01


class UnitsTests(unittest.TestCase):
    """An order whose ATR (0.40), planned risk (0.60) and tier (5 bps) are three different numbers."""

    def test_r_is_divided_by_the_planned_risk(self):
        o = feed(order(**UNITS), [bar(1, 19.90, 20.05, 19.30, 19.35)])          # trigger at T, stopped at S
        self.assertEqual((o.entry_kind, o.exit_kind), (F.ENTRY_TRIGGER, F.EXIT_STOP))
        self.assertAlmostEqual(o.planned_risk, 0.60)
        self.assertAlmostEqual(o.exit_cost, 4 * 0.0097)                         # 4h in the 5 bps tier at 19.40
        self.assertAlmostEqual(F.r_multiple(o), ((19.40 - 4 * 0.0097) - (20.00 + 0.0100)) / 0.60)

    def test_a_target_is_three_planned_risks_before_costs(self):
        o = feed(order(**UNITS), [bar(1, 19.90, 20.05, 19.80, 20.00), bar(2, 20.50, 21.81, 20.40, 21.50)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TARGET, 21.80))
        self.assertAlmostEqual(F.r_multiple(o), ((21.80 - 0.0109) - 20.01) / 0.60)

    def test_an_opening_fill_pays_2h_and_its_stop_out_is_over_the_planned_risk(self):
        o = feed(order(**UNITS), [bar(1, 20.02, 20.05, 19.30, 19.35)])
        self.assertEqual((o.entry_kind, o.entry_raw), (F.ENTRY_OPEN, 20.02))
        self.assertAlmostEqual(o.entry_cost, 2 * 0.0005 * 20.02)                # 2h in the 5 bps tier
        self.assertAlmostEqual(F.r_multiple(o), ((19.40 - 4 * 0.0097) - (20.02 + 0.02002)) / 0.60)

    def test_a_gap_through_pays_4h_at_the_open_and_a_mark_is_per_planned_risk(self):
        o = feed(order(**UNITS), [bar(1, 19.90, 20.05, 19.80, 20.00)])              # intraday trigger at T
        ev = F.evaluate_at_cutoff(o, o.last_session, 20.30, P0)
        self.assertAlmostEqual(ev.r, ((20.30 - 0.0005 * 20.30) - (20.00 + 0.0005 * 20.00)) / 0.60)
        o = feed(o, [bar(2, 19.30, 19.35, 19.20, 19.25)])                           # gap through S
        self.assertEqual(o.exit_raw, 19.30)
        self.assertAlmostEqual(F.r_multiple(o), ((19.30 - 4 * 0.0005 * 19.30) - (20.00 + 0.0100)) / 0.60)

    def test_the_half_cent_floor_is_multiplied_like_any_half_spread(self):
        cheap = dict(trigger=6.00, ceiling=6.05, stop=5.80, target=6.60, atr=0.20, tier_bps=5.0)   # 5 bps x $6 < half a cent
        o = feed(order(**cheap), [bar(1, 6.02, 6.04, 5.90, 6.00)])
        self.assertAlmostEqual(o.entry_cost, 0.010)                      # 2 x max(0.00301, 0.005)
        o = feed(o, [bar(2, 5.70, 5.75, 5.60, 5.65)])
        self.assertAlmostEqual(o.exit_cost, 0.020)                       # gap-through: 4 x max(0.00285, 0.005)

    def test_crash_bar_threshold_is_one_atr_below_the_stop(self):
        o = feed(order(**UNITS), [bar(1, 19.90, 20.05, 19.80, 20.00)], params=CB)
        hit = feed(o, [bar(2, 19.90, 20.00, 18.99, 19.10)], params=CB)   # S - ATR = 19.00; the low is below it
        self.assertEqual((hit.exit_raw, hit.crash_bar), (18.99, True))
        miss = feed(o, [bar(2, 19.90, 20.00, 19.00, 19.10)], params=CB)  # exactly one ATR through: not a crash bar
        self.assertEqual((miss.exit_raw, miss.crash_bar), (19.40, False))


class CostTests(unittest.TestCase):
    """3.4 costs."""

    def test_tiers_by_average_dollar_volume(self):
        self.assertEqual([F.tier_bps(v, PARAMS) for v in (250e6, 100e6, 99.9e6, 25e6, 24.9e6, 5e6, 4.9e6, 0)],
                         [5.0, 5.0, 10.0, 10.0, 20.0, 20.0, 40.0, 40.0])

    def test_a_missing_or_negative_dollar_volume_is_an_error_not_the_widest_tier(self):
        for bad in (float("nan"), float("inf"), -1.0):
            with self.assertRaises(ValueError):
                F.tier_bps(bad, PARAMS)

    def test_a_tier_table_that_does_not_reach_zero_is_an_error(self):
        with self.assertRaises(ValueError):
            F.tier_bps(1.0, replace(PARAMS, cost_tiers=((100e6, 5.0), (25e6, 10.0))))

    def test_half_spread_is_bps_of_price_with_a_half_cent_floor(self):
        self.assertAlmostEqual(F.half_spread(20.00, 20.0, P0), 0.04)
        self.assertAlmostEqual(F.half_spread(5.00, 5.0, P0), 0.005)      # 0.0025 floors at half a cent
        self.assertAlmostEqual(F.half_spread(8.00, 40.0, P0), 0.032)
        self.assertAlmostEqual(F.half_spread(60.00, 10.0, P0), 0.06)

    def test_a_tier_that_is_not_one_of_the_four_is_an_error(self):
        for bad in (0.002, 15.0, 0.0005):                                # a fraction instead of bps; a made-up tier
            with self.assertRaises(ValueError):
                F.half_spread(20.00, bad, P0)
        with self.assertRaises(ValueError):
            feed(order(tier_bps=15.0), [bar(*TRIGGER_ENTRY)])

    def test_each_kind_of_fill_pays_its_own_number_of_half_spreads(self):
        self.assertAlmostEqual(held().entry_cost, 0.04)                                  # intraday trigger: h
        self.assertAlmostEqual(held(OPEN_ENTRY).entry_cost, 2 * 0.002 * 20.20)           # opening fill: 2h
        self.assertAlmostEqual(held(CEILING_ENTRY).entry_cost, 0.002 * 20.25)            # fill at C: h
        exits = {(2, 19.90, 20.00, 19.00, 19.50): (F.EXIT_STOP, 4 * 0.038),              # intraday stop: 4h
                 (2, 18.80, 18.90, 18.50, 18.60): (F.EXIT_GAP_STOP, 4 * 0.0376),         # gap-through stop: 4h
                 (2, 22.00, 23.01, 21.90, 22.50): (F.EXIT_TARGET, 0.046),                # target: h
                 (2, 24.00, 24.50, 23.80, 24.20): (F.EXIT_TARGET, 0.046)}                # gap past the target: h
        for exit_bar, (kind, cost) in exits.items():
            o = feed(held(), [bar(*exit_bar)])
            self.assertEqual(o.exit_kind, kind)
            self.assertAlmostEqual(o.exit_cost, cost)
        o = feed(after_40_sessions(), [bar(42, 20.30, 20.40, 20.20, 20.35)])
        self.assertAlmostEqual(o.exit_cost, 2 * 0.002 * 20.30)                           # time exit: 2h

    def test_four_is_the_stop_exit_multiple_and_it_is_read_from_params(self):
        self.assertEqual(PARAMS.stop_exit_cost_mult, 4.0)
        three = replace(P0, stop_exit_cost_mult=3.0)
        o = feed(held(params=three), [bar(2, 19.90, 20.00, 19.00, 19.50)], params=three)
        self.assertAlmostEqual(o.exit_cost, 3 * 0.038)

    def test_costs_times_two_doubles_a_later_session_intraday_stop(self):
        o = feed(held(params=X2), [bar(2, 19.90, 20.00, 19.00, 19.50)], params=X2)       # 4h -> 8h
        self.assertEqual(o.exit_kind, F.EXIT_STOP)
        self.assertAlmostEqual(o.exit_cost, 8 * 0.038)
        self.assertAlmostEqual(F.r_multiple(o), (19.00 - 8 * 0.038) - (20.00 + 2 * 0.04))   # -1.384

    def test_costs_times_two_doubles_every_cost_including_the_stop_exit(self):
        o = feed(order(), [bar(1, 19.50, 20.10, 18.90, 19.20)], params=X2)              # trigger h -> 2h; stop 4h -> 8h
        self.assertAlmostEqual(o.entry_cost, 2 * 0.04)
        self.assertAlmostEqual(o.exit_cost, 8 * 0.038)
        self.assertAlmostEqual(F.r_multiple(o), (19.00 - 8 * 0.038) - (20.00 + 0.08))
        o = feed(held(OPEN_ENTRY, params=X2), [bar(2, 18.80, 18.90, 18.50, 18.60)], params=X2)   # opening 2h -> 4h; gap 4h -> 8h
        self.assertAlmostEqual(o.entry_cost, 4 * 0.002 * 20.20)
        self.assertAlmostEqual(o.exit_cost, 8 * 0.0376)
        o = feed(after_40_sessions(params=X2), [bar(42, 20.30, 20.40, 20.20, 20.35)], params=X2)  # time exit 2h -> 4h
        self.assertAlmostEqual(o.exit_cost, 4 * 0.002 * 20.30)

    def test_the_half_cent_floor_doubles_too(self):
        self.assertAlmostEqual(F.half_spread(5.00, 5.0, X2), 0.010)      # 2 x max(0.0025, 0.005)
        self.assertAlmostEqual(F.half_spread(8.00, 5.0, X2), 0.010)      # 2 x max(0.0040, 0.005)

    def test_marks_pay_double_too(self):
        o = feed(order(), [bar(*TRIGGER_ENTRY), bar(2, 20.00, 20.60, 19.90, 20.50)], params=X2)
        want = (20.50 - 2 * 0.041) - (20.00 + 2 * 0.04)
        self.assertAlmostEqual(F.evaluate_at_cutoff(o, day(2), 20.50, X2).r, want)
        self.assertAlmostEqual(F.r_multiple(F.close_at_mark(o, day(2), 20.50, X2)), want)

    def test_every_trade_pays_both_legs(self):
        o = feed(held(), [bar(2, 22.00, 23.01, 21.90, 22.50)])
        self.assertGreater(o.entry_cost, 0)
        self.assertGreater(o.exit_cost, 0)
        self.assertAlmostEqual(F.net_entry(o), 20.04)


class FillPriceTests(unittest.TestCase):
    """3.4 (ruling 2026-11-11): there is no slippage term. Every fill is at the open, T, C, S or P exactly."""

    def test_an_opening_buy_fills_exactly_at_the_open(self):
        for open_ in (20.00, 20.10, 20.22, 20.25):
            o = feed(order(), [bar(1, open_, 20.30, 19.95, 20.20)])
            self.assertEqual((o.entry_kind, o.entry_raw), (F.ENTRY_OPEN, open_))
        o = feed(order(atr=2.0, ceiling=20.50), [bar(1, 20.10, 20.30, 20.00, 20.20)])   # the ATR plays no part
        self.assertEqual(o.entry_raw, 20.10)

    def test_a_gap_through_stop_fills_exactly_at_the_open(self):
        o = feed(held(atr=2.0, ceiling=20.50), [bar(2, 18.80, 18.90, 18.50, 18.60)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_GAP_STOP, 18.80))
        self.assertAlmostEqual(F.r_multiple(o), -1.3904)

    def test_a_time_exit_fills_exactly_at_the_open_even_just_above_the_stop(self):
        o = feed(after_40_sessions(), [bar(42, 19.02, 19.10, 19.01, 19.05)])     # open > S: not a gap-through
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TIME, 19.02))
        self.assertAlmostEqual(F.r_multiple(o), (19.02 - 2 * 0.002 * 19.02) - 20.04)

    def test_a_collapse_is_sold_at_its_open(self):
        o = feed(held(), [bar(2, 0.03, 0.04, 0.02, 0.03)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_GAP_STOP, 0.03))
        self.assertAlmostEqual(o.exit_cost, 4 * 0.005)                           # the half-cent floor, four times


class CrashBarBoundTests(unittest.TestCase):
    """3.4 sensitivity row: 'on stop sessions with open > S and low < S - 1 ATR, fill at the low'."""

    def test_off_by_default_an_intraday_stop_fills_at_the_stop(self):
        o = feed(held(), [bar(2, 19.90, 20.00, 17.90, 18.00)])
        self.assertEqual((o.exit_raw, o.crash_bar), (19.00, False))

    def test_on_a_bar_more_than_one_atr_through_the_stop_fills_at_the_low(self):
        o = feed(held(params=CB), [bar(2, 19.90, 20.00, 17.90, 18.00)], params=CB)
        self.assertEqual((o.exit_kind, o.exit_raw, o.crash_bar), (F.EXIT_STOP, 17.90, True))
        self.assertAlmostEqual(o.exit_cost, 4 * 0.002 * 17.90)              # still a stop exit: 4h, on the fill price

    def test_on_exactly_one_atr_through_the_stop_is_not_a_crash_bar(self):
        o = feed(held(params=CB), [bar(2, 19.90, 20.00, 18.00, 18.10)], params=CB)
        self.assertEqual((o.exit_raw, o.crash_bar), (19.00, False))

    def test_the_threshold_is_in_atrs_not_dollars(self):
        o = feed(held(params=CB, atr=0.5), [bar(2, 19.90, 20.00, 18.40, 18.45)], params=CB)
        self.assertEqual((o.exit_kind, o.exit_raw, o.crash_bar), (F.EXIT_STOP, 18.40, True))      # S - ATR = 18.50
        o = feed(held(params=CB, atr=2.0, ceiling=20.50), [bar(2, 19.90, 20.00, 17.50, 17.60)], params=CB)
        self.assertEqual((o.exit_kind, o.exit_raw, o.crash_bar), (F.EXIT_STOP, 19.00, False))     # S - ATR = 17.00

    def test_on_applies_on_the_entry_session_when_the_open_is_above_the_stop(self):
        o = feed(order(), [bar(1, 19.90, 20.10, 17.50, 17.60)], params=CB)
        self.assertEqual((o.exit_raw, o.crash_bar), (17.50, True))

    def test_on_does_not_apply_on_an_entry_session_that_opened_at_or_below_the_stop(self):
        o = feed(order(), [bar(1, 18.90, 20.10, 17.50, 17.60)], params=CB)   # the spec's condition open > S is false
        self.assertEqual((o.exit_kind, o.exit_raw, o.crash_bar), (F.EXIT_STOP, 19.00, False))
        self.assertAlmostEqual(F.r_multiple(o), -1.192)
        o = feed(order(), [bar(1, 19.00, 20.10, 17.50, 17.60)], params=CB)   # open == S
        self.assertEqual((o.exit_raw, o.crash_bar), (19.00, False))

    def test_a_gap_through_stays_at_the_open(self):
        o = feed(held(params=CB), [bar(2, 18.80, 18.90, 17.50, 17.60)], params=CB)
        self.assertEqual((o.exit_kind, o.exit_raw, o.crash_bar), (F.EXIT_GAP_STOP, 18.80, False))
        self.assertAlmostEqual(F.r_multiple(o), -1.3904)

    def test_an_order_that_has_not_exited_is_not_flagged(self):
        self.assertFalse(order().crash_bar)
        self.assertFalse(held(params=CB).crash_bar)

    def test_other_exits_are_never_flagged(self):
        for bars in ([bar(2, 24.00, 24.50, 23.80, 24.20)], [bar(2, 22.00, 23.01, 21.90, 22.50)],
                     [bar(*q) for q in QUIET40] + [bar(42, 20.30, 20.40, 20.20, 20.35)]):
            self.assertFalse(feed(held(params=CB), bars, params=CB).crash_bar)


class CutoffEvaluationTests(unittest.TestCase):
    """Section 6: one rule for trades open at a cutoff -- forward window, analog band windows, IS pick marks."""

    def test_a_trade_closed_by_the_cutoff_reports_its_realized_r(self):
        o = feed(held(), [bar(2, 18.80, 18.90, 18.50, 18.60)])
        self.assertEqual(F.evaluate_at_cutoff(o, day(5), None, P0), F.Evaluation(F.r_multiple(o), "closed"))

    def test_a_trade_that_exits_on_the_cutoff_session_reports_its_realized_r(self):
        o = feed(held(), [bar(2, 18.80, 18.90, 18.50, 18.60)])
        ev = F.evaluate_at_cutoff(o, day(2), 18.60, P0)               # the runner passes the close for every order
        self.assertEqual(ev.status, "closed")
        self.assertAlmostEqual(ev.r, -1.3904)

    def test_a_trade_still_open_is_marked_at_the_cutoff_close_net_of_the_exit_half_spread(self):
        o = feed(held(), [bar(2, 20.00, 20.60, 19.90, 20.50), bar(3, 20.50, 21.20, 20.40, 21.00)])
        ev = F.evaluate_at_cutoff(o, day(3), 21.00, P0)
        self.assertEqual(ev.status, "marked")
        self.assertAlmostEqual(ev.r, (21.00 - 0.042) - 20.04)

    def test_a_mark_is_divided_by_the_planned_risk(self):
        o = feed(held(stop=18.00, target=26.00), [bar(2, 20.00, 20.60, 19.90, 20.50), bar(3, 20.50, 21.20, 20.40, 21.00)])
        self.assertAlmostEqual(F.evaluate_at_cutoff(o, day(3), 21.00, P0).r, ((21.00 - 0.042) - 20.04) / 2.00)

    def test_a_mark_is_measured_from_the_actual_fill_over_the_planned_risk(self):
        o = feed(held(OPEN_ENTRY), [bar(2, 20.50, 21.20, 20.40, 21.00)])
        self.assertAlmostEqual(F.evaluate_at_cutoff(o, day(2), 21.00, P0).r, (21.00 - 0.042) - (20.20 + 2 * 0.002 * 20.20))

    def test_marking_and_closing_at_the_mark_give_the_same_number(self):
        o = feed(held(), [bar(2, 20.00, 20.60, 19.90, 20.50)])
        closed = F.close_at_mark(o, day(2), 20.50, P0)
        self.assertEqual((closed.state, closed.exit_kind, closed.exit_date, closed.exit_raw),
                         (F.CLOSED, F.EXIT_MARK, day(2), 20.50))
        self.assertAlmostEqual(F.r_multiple(closed), F.evaluate_at_cutoff(o, day(2), 20.50, P0).r)
        self.assertEqual(F.evaluate_at_cutoff(closed, day(2), None, P0).status, "closed")

    def test_a_mark_is_the_close_itself_even_a_fraction_of_a_cent_above_the_target(self):
        o = feed(held(), [bar(2, 22.90, 23.008, 22.80, 23.006)])      # the high is short of P + 0.01: still open
        self.assertEqual(o.state, F.OPEN)
        want = (23.006 - 0.002 * 23.006) - 20.04
        self.assertAlmostEqual(F.evaluate_at_cutoff(o, day(2), 23.006, P0).r, want)
        self.assertAlmostEqual(F.r_multiple(F.close_at_mark(o, day(2), 23.006, P0)), want)

    def test_a_close_that_an_open_trade_cannot_have_is_an_error(self):
        o = feed(held(), [bar(2, 20.00, 20.60, 19.90, 20.50)])
        # at or below S; a cent or more through P; and the close of a 2:1 split that was never applied
        for impossible in (19.00, 18.50, 23.01, 30.00, 10.25):
            with self.assertRaises(ValueError):
                F.evaluate_at_cutoff(o, day(2), impossible, P0)
            with self.assertRaises(ValueError):
                F.close_at_mark(o, day(2), impossible, P0)
        for possible in (19.0001, 23.0099):
            self.assertEqual(F.evaluate_at_cutoff(o, day(2), possible, P0).status, "marked")
            self.assertEqual(F.close_at_mark(o, day(2), possible, P0).exit_raw, possible)

    def test_close_at_mark_refuses_an_order_that_never_filled(self):
        pending = feed(order(), [bar(1, *NO_FILL)])
        with self.assertRaises(ValueError):
            F.close_at_mark(pending, day(1), 19.60, P0)

    def test_an_order_that_never_filled_is_not_a_trade(self):
        pending = feed(order(), [bar(1, *NO_FILL)])
        expired = feed(order(window=1), [bar(1, *NO_FILL)])
        canceled = feed(order(), [bar(1, 20.40, 20.60, 20.30, 20.50)])
        for o in (pending, expired, canceled):
            self.assertIsNone(F.evaluate_at_cutoff(o, day(1), 19.60, P0))
        for o in (expired, canceled, F.cancel(order(), F.CANCEL_REPLACED)):
            self.assertIsNone(F.evaluate_at_cutoff(o, day(9), 19.60, P0))   # dead orders stay non-trades

    def test_an_order_signaled_at_the_cutoff_close_is_not_a_trade_yet(self):
        self.assertIsNone(F.evaluate_at_cutoff(order(), SIGNAL_DAY, 19.95, P0))

    def test_a_trade_filled_on_the_cutoff_session_is_marked(self):
        ev = F.evaluate_at_cutoff(held(), day(1), 20.05, P0)
        self.assertAlmostEqual(ev.r, (20.05 - 0.002 * 20.05) - 20.04)

    def test_misuse_is_an_error_not_a_silent_number(self):
        o = held()
        with self.assertRaises(ValueError):
            F.evaluate_at_cutoff(o, day(4), 21.00, P0)                # open, not advanced to the cutoff
        for bad_close in (None, 0.0, -1.0, float("nan")):
            with self.assertRaises(ValueError):
                F.evaluate_at_cutoff(o, day(1), bad_close, P0)        # open, no usable close to mark at
        closed = feed(o, [bar(2, 18.80, 18.90, 18.50, 18.60)])
        with self.assertRaises(ValueError):
            F.evaluate_at_cutoff(closed, day(1), 20.0, P0)            # advanced past the cutoff
        with self.assertRaises(ValueError):
            F.close_at_mark(closed, day(2), 18.60, P0)                # already closed

    def test_an_open_trade_advanced_past_the_cutoff_is_an_error(self):
        o = feed(held(), [bar(2, 20.00, 20.60, 19.90, 20.50), bar(3, 20.50, 21.20, 20.40, 21.00)])
        with self.assertRaises(ValueError):
            F.evaluate_at_cutoff(o, day(2), 20.50, P0)                # a mark here would use a later state

    def test_a_stale_pending_order_is_an_error_not_a_non_trade(self):
        stale = feed(order(), [bar(1, *NO_FILL)])                     # advanced through day 1 only
        with self.assertRaises(ValueError):
            F.evaluate_at_cutoff(stale, day(2), 20.05, P0)            # it could have filled on day 2
        with self.assertRaises(ValueError):
            F.evaluate_at_cutoff(order(), day(2), 20.05, P0)          # never advanced at all
        with self.assertRaises(ValueError):
            F.evaluate_at_cutoff(order(signal_date=day(3)), day(2), 20.05, P0)   # signaled after the cutoff

    def test_close_at_mark_refuses_a_date_the_trade_was_not_advanced_to_and_a_bad_close(self):
        o = feed(held(), [bar(2, 20.00, 20.60, 19.90, 20.50)])
        with self.assertRaises(ValueError):
            F.close_at_mark(o, day(5), 20.50, P0)
        for bad_close in (0.0, -1.0, float("nan")):
            with self.assertRaises(ValueError):
                F.close_at_mark(o, day(2), bad_close, P0)


class RescaleTests(unittest.TestCase):
    """Section 4: 'the levels ... of open forward and paper trades are rescaled'; 3.1: R is scale-free."""

    def test_a_two_for_one_split_halves_every_price_and_keeps_r(self):
        o = F.rescale(held(), 0.5)
        self.assertEqual((o.trigger, o.ceiling, o.stop, o.target, o.atr), (10.0, 10.125, 9.5, 11.5, 0.5))
        self.assertAlmostEqual(o.entry_raw + o.entry_cost, 10.02)
        o = feed(o, [bar(2, 9.40, 9.45, 9.25, 9.30)])                 # 18.80 on the old basis
        self.assertEqual(o.exit_kind, F.EXIT_GAP_STOP)
        self.assertAlmostEqual(F.r_multiple(o), -1.3904)

    def test_a_pending_order_and_its_invalidation_level_rescale(self):
        o = F.rescale(order(invalidation=19.40), 0.5)
        self.assertEqual((o.state, o.invalidation, o.entry_raw), (F.PENDING, 9.7, None))
        self.assertEqual((o.trigger, o.ceiling, o.stop, o.target), (10.0, 10.125, 9.5, 11.5))
        o = F.rescale(order(), 0.5)                                    # no invalidation level
        self.assertEqual((o.trigger, o.ceiling, o.stop, o.target, o.atr, o.invalidation), (10.0, 10.125, 9.5, 11.5, 0.5, None))

    def test_rescaling_a_closed_trade_keeps_its_r(self):
        r = F.rescale(feed(held(), [bar(2, 18.80, 18.90, 18.50, 18.60)]), 0.5)
        self.assertAlmostEqual(r.exit_raw, 9.40)
        self.assertAlmostEqual(r.exit_cost, 0.0752)
        self.assertAlmostEqual(F.r_multiple(r), -1.3904)

    def test_a_split_does_not_restart_the_hold_clock(self):
        o = feed(held(), [bar(n, *QUIET) for n in range(2, 12)])            # sessions 1..10
        o = F.rescale(o, 0.5)                                                # 2:1 split before session 11
        self.assertEqual((o.sessions_held, o.last_session), (10, day(11)))
        o = feed(o, [bar(n, 10.00, 10.25, 9.75, 10.00) for n in range(12, 42)])   # sessions 11..40
        self.assertEqual((o.state, o.sessions_held), (F.OPEN, 40))
        o = feed(o, [bar(42, 10.15, 10.20, 10.10, 10.18)])
        self.assertEqual((o.exit_kind, o.exit_raw, o.sessions_held), (F.EXIT_TIME, 10.15, 41))

    def test_a_split_does_not_restart_the_entry_window(self):
        o = feed(order(window=3, invalidation=19.40), [bar(1, *NO_FILL), bar(2, *NO_FILL)])
        o = F.rescale(o, 0.5)                                                # split before the third window session
        self.assertEqual((o.trigger, o.ceiling, o.stop, o.target, o.sessions_pending), (10.0, 10.125, 9.5, 11.5, 2))
        o = feed(o, [bar(3, 9.75, 9.95, 9.70, 9.80)])                        # no fill: the window is over
        self.assertEqual(o.state, F.EXPIRED)

    def test_a_three_for_two_split_scales_exactly(self):
        o = F.rescale(held(), 2 / 3)
        for got, old in ((o.trigger, 20.00), (o.ceiling, 20.25), (o.stop, 19.00), (o.target, 23.00), (o.atr, 1.0)):
            self.assertAlmostEqual(got, old * 2 / 3, places=9)              # 12.6667, not 12.67
        o = feed(o, [bar(2, 12.5333, 12.60, 12.40, 12.45)])                 # 18.80 on the old basis
        self.assertEqual(o.exit_kind, F.EXIT_GAP_STOP)
        self.assertAlmostEqual(F.r_multiple(o), -1.3904, places=3)

    def test_a_three_for_one_split_keeps_r_without_rounding_the_stop(self):
        o = F.rescale(held(stop=19.01), 1 / 3)
        self.assertAlmostEqual(o.target, 23.00 / 3, places=9)
        self.assertAlmostEqual(o.ceiling, 20.25 / 3, places=9)
        o = feed(o, [bar(2, 6.20, 6.25, 6.10, 6.15)])                       # 18.60 on the old basis: a gap through S
        self.assertEqual(o.exit_kind, F.EXIT_GAP_STOP)
        self.assertAlmostEqual(F.r_multiple(o), ((18.60 - 4 * 0.002 * 18.60) - 20.04) / 0.99, places=9)

    def test_a_reverse_split_scales_up(self):
        o = feed(F.rescale(held(), 10.0), [bar(2, 188.00, 189.00, 185.00, 186.00)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_GAP_STOP, 188.00))
        self.assertAlmostEqual(F.r_multiple(o), -1.3904)

    def test_ratio_must_be_a_finite_positive_number(self):
        for bad in (0, -0.5, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                F.rescale(order(), bad)


class ShiftTests(unittest.TestCase):
    """3.1 / 4: a special distribution rebases the bars by a constant dollar amount (FRO, $1.60). 'A dollar
    shift keeps every price difference, so ATR, risk and R are unaffected'; costs in bps are off by the shift."""

    def test_every_level_moves_by_the_same_dollars(self):
        o = F.shift(order(invalidation=19.40), -1.60)
        for got, want in ((o.trigger, 18.40), (o.ceiling, 18.65), (o.stop, 17.40), (o.target, 21.40), (o.invalidation, 17.80)):
            self.assertAlmostEqual(got, want, places=9)
        self.assertAlmostEqual(o.planned_risk, 1.00, places=9)
        self.assertEqual((o.atr, o.state, o.entry_raw, o.exit_raw), (1.0, F.PENDING, None, None))

    def test_an_open_trade_keeps_its_risk_its_paid_cost_and_its_clock(self):
        h = feed(held(), [bar(2, 20.00, 20.50, 19.50, 20.10)])          # one session held
        s = F.shift(h, -1.60)
        self.assertAlmostEqual(s.entry_raw, 18.40, places=9)
        self.assertEqual((s.entry_cost, s.sessions_held, s.last_session), (h.entry_cost, 1, day(2)))
        s = feed(s, [bar(3, 17.20, 17.30, 17.00, 17.10)])               # 18.80 on the old basis: a gap through S
        self.assertEqual(s.exit_kind, F.EXIT_GAP_STOP)
        self.assertAlmostEqual(s.exit_raw, 17.20)
        # Price differences are unchanged; only the exit's bps cost is charged on the lower price.
        self.assertAlmostEqual(F.r_multiple(s), (17.20 - 4 * 0.002 * 17.20) - (18.40 + 0.04))

    def test_a_closed_trade_keeps_its_r(self):
        c = feed(held(), [bar(2, 18.80, 18.90, 18.50, 18.60)])
        shifted = F.shift(c, -1.60)
        self.assertAlmostEqual(shifted.exit_raw, 17.20, places=9)
        self.assertEqual((shifted.entry_cost, shifted.exit_cost), (c.entry_cost, c.exit_cost))
        self.assertAlmostEqual(F.r_multiple(shifted), -1.3904)

    def test_a_shift_and_its_reverse_restore_the_order(self):
        back = F.shift(F.shift(held(), -1.60), 1.60)
        for got, want in ((back.trigger, 20.00), (back.stop, 19.00), (back.target, 23.00), (back.entry_raw, 20.00)):
            self.assertAlmostEqual(got, want, places=9)

    def test_a_shift_that_would_put_the_stop_at_or_below_zero_is_refused(self):
        for bad in (-19.00, -25.00, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                F.shift(order(), bad)


class ValidationTests(unittest.TestCase):
    def test_levels_must_be_ordered_and_positive(self):
        for bad in (dict(stop=20.00), dict(ceiling=19.99), dict(target=20.25), dict(target=20.00), dict(stop=0.0),
                    dict(stop=-1.0)):
            with self.assertRaises(ValueError):
                order(**bad)

    def test_trigger_may_equal_ceiling(self):
        self.assertEqual(order(ceiling=20.00).ceiling, 20.00)

    def test_the_invalidation_level_sits_below_the_trigger(self):
        # 3.2: the shelf floor (M1) or the gap-day low (M2), both below T = the signal-day high + 0.01
        for bad in (20.00, 20.10, 23.00):
            with self.assertRaises(ValueError):
                order(invalidation=bad)
        self.assertEqual(order(invalidation=19.99).invalidation, 19.99)

    def test_orders_and_bars_cannot_be_modified_in_place(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            held().stop = 1.0
        with self.assertRaises(dataclasses.FrozenInstanceError):
            bar(*TRIGGER_ENTRY).low = 1.0

    def test_window_atr_and_tier_must_be_positive(self):
        for bad in (dict(window=0), dict(atr=0.0), dict(tier_bps=0.0), dict(atr=-1.0)):
            with self.assertRaises(ValueError):
                order(**bad)

    def test_levels_atr_and_tier_must_be_finite_numbers(self):
        nan, inf = float("nan"), float("inf")
        for bad in (dict(atr=nan), dict(tier_bps=nan), dict(trigger=nan), dict(target=inf), dict(stop=nan),
                    dict(ceiling=nan), dict(invalidation=nan), dict(atr=inf), dict(atr=None)):
            with self.assertRaises(ValueError):
                order(**bad)

    def test_impossible_bars_are_rejected(self):
        for o, h, lo, c in ((20.0, 19.0, 19.5, 19.2),       # low > high
                            (20.0, 21.0, 19.0, 21.5),       # close above the high
                            (20.0, 21.0, 19.5, 19.2),       # close below the low
                            (20.0, 21.0, 20.5, 20.8),       # open below the low
                            (21.5, 21.0, 19.0, 20.0),       # open above the high
                            (1.0, 1.0, 0.0, 0.5),           # a zero low
                            (20.0, float("nan"), 19.0, 20.0), (20.0, float("inf"), 19.0, 20.0)):
            with self.assertRaises(ValueError):
                F.Bar(day(1), o, h, lo, c)

    def test_r_is_only_defined_for_closed_trades(self):
        with self.assertRaises(ValueError):
            F.r_multiple(held())

    def test_breadth_and_params_have_no_defaults(self):
        with self.assertRaises(TypeError):
            F.step(order(), day(1), bar(*TRIGGER_ENTRY), params=P0)             # breadth forgotten
        with self.assertRaises(TypeError):
            F.step(order(), day(1), bar(*TRIGGER_ENTRY), breadth_ok=True)       # params forgotten
        with self.assertRaises(TypeError):
            F.run(order(), [(day(1), bar(*TRIGGER_ENTRY), True)])
        with self.assertRaises(TypeError):
            F.evaluate_at_cutoff(held(), day(1), 20.05)
        with self.assertRaises(TypeError):
            F.close_at_mark(held(), day(1), 20.05)
        with self.assertRaises(TypeError):
            F.half_spread(20.00, 20.0)

    def test_breadth_must_be_a_real_true_or_false(self):
        for bad in (None, 1, 0, "yes", 0.6):
            with self.assertRaises(TypeError):
                F.step(order(), day(1), bar(1, *NO_FILL), breadth_ok=bad, params=P0)


class InvariantTests(unittest.TestCase):
    """Randomized paths: whatever the bars do, the model's outputs stay inside the spec's bounds."""

    @staticmethod
    def random_path(rng: random.Random, sessions: int = 70):
        px, bars = rng.uniform(18.5, 20.5), []
        for n in range(1, sessions + 1):
            o = max(1.0, px + rng.gauss(0, 0.5))
            c = max(1.0, o + rng.gauss(0, 0.7))
            h = max(o, c) + abs(rng.gauss(0, 0.4))
            lo = max(0.5, min(o, c) - abs(rng.gauss(0, 0.4)))
            bars.append(bar(n, round(o, 2), round(h, 2), round(lo, 2), round(c, 2)))
            px = c
        return bars

    def test_bounds_hold_on_two_thousand_random_paths(self):
        rng = random.Random(20261110)
        cap = (23.00 - 20.00) / (20.00 - 19.00)
        kinds = set()
        for _ in range(2000):
            bars = self.random_path(rng)
            o = F.run(order(window=5), [(b.date, b, True) for b in bars], params=P0)
            if not o.is_trade:
                continue
            self.assertTrue(20.00 <= o.entry_raw <= 20.25)             # filled inside [T, C]
            self.assertLessEqual(o.sessions_held, 41)
            if o.state != F.CLOSED:
                continue
            kinds.add((o.entry_kind, o.exit_kind))
            self.assertLessEqual(o.exit_raw, 23.00)                     # never credited above P
            if o.exit_kind == F.EXIT_TARGET:
                self.assertEqual(o.exit_raw, 23.00)
            if o.exit_kind == F.EXIT_STOP:
                self.assertEqual(o.exit_raw, 19.00)
            if o.exit_kind == F.EXIT_GAP_STOP:
                self.assertLessEqual(o.exit_raw, 19.00)
            if o.exit_kind == F.EXIT_TIME:
                self.assertEqual(o.sessions_held, 41)
                self.assertTrue(19.00 < o.exit_raw <= 23.00)            # OCO applies first at that open
            self.assertLess(F.r_multiple(o), cap)                       # the 3R cap, after costs
            if o.exit_kind in (F.EXIT_STOP, F.EXIT_GAP_STOP):
                # the best stop-out is a trigger entry at T stopped at S: (19.00 - 4 x 0.038) - 20.04 = -1.192
                self.assertLessEqual(F.r_multiple(o), -1.192 + 1e-9)
        self.assertTrue({F.EXIT_STOP, F.EXIT_GAP_STOP, F.EXIT_TARGET} <= {k for _, k in kinds})
        self.assertTrue({F.ENTRY_OPEN, F.ENTRY_TRIGGER, F.ENTRY_CEILING} <= {k for k, _ in kinds})

    def test_quiet_paths_reach_the_time_exit_and_it_respects_its_bounds(self):
        rng = random.Random(20261112)
        seen = set()
        for _ in range(300):
            px, bars = rng.uniform(19.6, 20.4), []
            for n in range(1, 61):
                o_ = max(1.0, px + rng.gauss(0, 0.125))
                c_ = max(1.0, o_ + rng.gauss(0, 0.175))
                h_ = max(o_, c_) + abs(rng.gauss(0, 0.1))
                lo_ = max(0.5, min(o_, c_) - abs(rng.gauss(0, 0.1)))
                bars.append(bar(n, round(o_, 2), round(h_, 2), round(lo_, 2), round(c_, 2)))
                px = c_
            o = F.run(order(window=5), [(b.date, b, True) for b in bars], params=P0)
            if o.state != F.CLOSED:
                continue
            seen.add(o.exit_kind)
            if o.exit_kind == F.EXIT_TIME:
                self.assertEqual(o.sessions_held, 41)
                self.assertTrue(19.00 < o.exit_raw < 23.01)             # open above S, short of a gap past P
            if o.exit_kind in (F.EXIT_STOP, F.EXIT_GAP_STOP):
                self.assertLessEqual(F.r_multiple(o), -1.192 + 1e-9)
            self.assertLess(F.r_multiple(o), 3.0)
        self.assertIn(F.EXIT_TIME, seen)

    def test_bounds_hold_with_missing_bars_and_weak_breadth(self):
        rng = random.Random(20261111)
        seen = set()
        for _ in range(1500):
            sessions = [(b.date, None if rng.random() < 0.06 else b, rng.random() >= 0.05)
                        for b in self.random_path(rng)]
            o = F.run(order(window=5), sessions, params=P0)
            if not o.is_trade:
                self.assertIn(o.state, (F.CANCELED, F.EXPIRED))        # 70 sessions always outlast a 5-session window
                self.assertLessEqual(o.sessions_pending, 5)
                seen.add(o.cancel_reason or o.state)
                continue
            before = [ok for d, _, ok in sessions if d < o.entry_date]
            self.assertLess(len(before), 5)                             # filled inside the 5-session window
            self.assertTrue(all(before))                                # 3.3: breadth held at every earlier close
            self.assertTrue(20.00 <= o.entry_raw <= 20.25)              # never bought above the ceiling
            if o.state != F.CLOSED:
                continue
            after = [b for d, b, _ in sessions if o.entry_date < d <= o.exit_date]
            if o.exit_date == o.entry_date:
                self.assertEqual(o.sessions_held, 0)
            else:
                self.assertEqual(len(after), o.sessions_held)           # every session counts, bar or no bar
                self.assertIsNotNone(after[-1])                         # an exit needs a bar
            seen.add(o.exit_kind)
            self.assertLessEqual(o.exit_raw, 23.00)
            if o.exit_kind == F.EXIT_TIME:
                self.assertGreaterEqual(o.sessions_held, 41)
                self.assertTrue(all(b is None for b in after[40:-1]))   # delayed only by missing bars
            else:
                self.assertLessEqual(o.sessions_held, 41 + sum(b is None for b in after))
            self.assertLess(F.r_multiple(o), 3.0)
            if o.exit_kind in (F.EXIT_STOP, F.EXIT_GAP_STOP):
                self.assertLess(F.r_multiple(o), -1.0)
        self.assertTrue({F.CANCEL_BREADTH, F.CANCEL_TRIGGERED_UNFILLED, F.EXPIRED,
                         F.EXIT_STOP, F.EXIT_GAP_STOP, F.EXIT_TARGET} <= seen)


class ParamsTests(unittest.TestCase):
    # Every number below is typed from specs/phase2_spec.md (the section is named on each line),
    # not copied from params.py. A value that changes there has to change here, and in the spec.
    SPEC = dict(
        # 3.1
        price_min=5.0, price_max=100.0, adv_min_shares=500_000, adv_window=30, min_history_sessions=60,
        bars_present_min=58, bars_present_window=60, bars_start="2021-01-04",
        # 3.2
        levels_window=120, trigger_offset=0.01, ceiling_atr=0.25, stop_buffer_atr=0.2, touch_atr=0.25,
        m1_min_rr=3.0, m1_window=3, m2_window=5, m2_gap_pct=0.03, m2_gap_atr=1.0, m2_volume_mult=3.0,
        m2_close_range_min=0.5, m2_spy_gap_max=0.01, m2_cadence_sessions=40,
        edgar_window_start_et="16:00", edgar_window_end_et="16:00",
        # 3.3
        breadth_sma=50, breadth_min=0.50,
        # 3.4 and 3.6
        stop_k=(1.0, 1.5, 2.0), default_k=1.5, default_breadth_on=True, target_r=3.0, time_exit_session=41,
        trade_through=0.01, cost_tiers=((100e6, 5.0), (25e6, 10.0), (5e6, 20.0), (0.0, 40.0)),
        cost_dollar_volume_window=30, min_half_spread=0.005, open_fill_cost_mult=2.0, stop_exit_cost_mult=4.0,
        cost_mult=1.0, cost_sensitivity_mult=2.0, crash_bar_bound=False, crash_bar_atr=1.0,
        # 1 and 4: paper sizing
        basis=1500.0, risk_pct=0.01, position_cap_pct=0.175, deployment_cap_pct=0.70, open_risk_cap_pct=0.04,
        max_positions=4, max_per_method=2, max_per_sector=2, min_shares=3,
        # 3.7 and 3.8
        is_start="2022-01-03", is_end="2024-12-31", oos_start="2025-01-02", oos_end="2026-10-30",
        oos_seal_close="2026-12-30", p1_min_trades=300, p2_min_avg_r=0.20, pick_min_is_fills=187,
        pick_tie_r=0.005, pick_tie_breadth_on_first=True, pick_tie_k_order=(1.5, 1.0, 2.0),
        p4_remove_trades=3, p4_remove_months=3, p5_runs=1000, p5_beat_pct=95.0, p5_redraws=20,
        a2_min_oos_trades=100, a3_exclude_start="2026-04-24", a3_exclude_end="2026-09-22",
        a6_spread_excess=0.50, a6_min_obs=30, random_seed=20261110,
        # 3.8 and 3.9 report-only rows
        bootstrap_level_pct=90.0, bootstrap_block_months=3, survivorship_stress_r=-1.0, sim_tie_orders=200,
        # 6
        decision_date="2027-01-15", m2_extension_date="2027-03-12", band_lo_pct=5.0, band_hi_pct=95.0,
        min_forward_trades_floor=10, check3_placements=10, go_live_target="2026-11-23",
        feasibility_spans=(("2022-11-23", "2023-01-13"), ("2023-11-23", "2024-01-12")),
        # 4
        nightly_run_et="17:30", nightly_retry_et=("19:30", "21:00", "06:30"), bar_final_cutoff_et=None,
        completeness_min=0.99, token_min_hours=3.0, request_limit_per_min=100, refresh_overlap_sessions=15,
        missing_bar_cusip_sessions=2, sector_map_min_agreement=0.90, ticket_deadline_et="09:25",
        live_balance_baseline=1.01,
    )

    def test_every_parameter_matches_the_spec_and_none_is_unlisted(self):
        actual = {f.name: getattr(PARAMS, f.name) for f in dataclasses.fields(PARAMS)}
        self.assertEqual(sorted(actual), sorted(self.SPEC))
        for name, want in self.SPEC.items():
            self.assertEqual(actual[name], want, name)

    def test_only_the_bar_final_cutoff_is_still_unset(self):
        self.assertEqual(unset(), ["bar_final_cutoff_et"])

    def test_paper_sizing_numbers_match_the_approved_rules(self):
        p = PARAMS
        self.assertEqual(round(p.basis * p.risk_pct, 2), 15.00)
        self.assertEqual(round(p.basis * p.position_cap_pct, 2), 262.50)
        self.assertEqual(round(p.basis * p.deployment_cap_pct, 2), 1050.00)
        self.assertEqual(round(p.basis * p.open_risk_cap_pct, 2), 60.00)
        self.assertEqual(p.max_positions * p.basis * p.position_cap_pct, p.basis * p.deployment_cap_pct)
        self.assertEqual(round(p.basis * p.position_cap_pct / p.min_shares, 2), 87.50)   # highest sizable ceiling
        self.assertEqual(round(p.basis * p.risk_pct / p.min_shares, 2), 5.00)            # widest sizable risk per share

    def test_the_pick_minimum_is_the_in_sample_share_of_300_trades(self):
        self.assertEqual(-(-PARAMS.p1_min_trades * 753 // 1212), PARAMS.pick_min_is_fills)   # 300 x 753/1,212, rounded up

    def test_the_hash_tracks_every_change(self):
        self.assertEqual(params_hash(), params_hash(replace(PARAMS)))
        self.assertNotEqual(params_hash(), params_hash(replace(PARAMS, target_r=2.9)))
        self.assertNotEqual(params_hash(), params_hash(X2))



class Rule2Boundary(unittest.TestCase):
    """3.4 later sessions: '2. open >= P + 0.01: target at P (no gap bonus); 3. low <= S: stopped at S'.
    At an open of exactly P + 0.01 rule 2 fires, so nothing later in the bar matters."""

    def test_open_exactly_one_cent_through_p_is_rule_2_even_if_the_bar_then_trades_down_to_s(self):   # E01 E03
        o = feed(held(), [bar(2, 23.01, 23.50, 18.90, 19.50)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TARGET, 23.00))
        self.assertAlmostEqual(o.exit_cost, 0.046)                       # a limit fill pays h = 0.002 x 23.00
        self.assertAlmostEqual(F.r_multiple(o), 2.914)                   # (23.00 - 0.046 - 20.04) / 1.00

    def test_session_41_open_exactly_one_cent_through_p_is_the_target_not_the_time_exit(self):        # E01 E03
        # 'A trade still open after session 40 is sold at the open of session 41, with the OCO rules applied first'
        o = feed(after_40_sessions(), [bar(42, 23.01, 23.50, 22.90, 23.40)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TARGET, 23.00))
        self.assertAlmostEqual(o.exit_cost, 0.046)                       # h at P, not 2h at the open
        self.assertAlmostEqual(F.r_multiple(o), 2.914)

    def test_rule_2_is_exact_where_binary_floats_are_not(self):                                       # E05
        # T 20.08, S 19.00 -> P = T + 3(T - S) = 23.32; in binary floating point 23.32 + 0.01 > 23.33.
        lv = dict(trigger=20.08, ceiling=20.24, stop=19.00, target=23.32, atr=0.64)
        o = feed(order(**lv), [bar(1, 19.90, 20.10, 19.80, 20.05), bar(2, 23.33, 23.50, 18.90, 19.50)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TARGET, 23.32))
        # entry at T pays 0.002 x 20.08 = 0.04016; target pays 0.002 x 23.32 = 0.04664; planned risk 1.08
        self.assertAlmostEqual(F.r_multiple(o), (23.32 - 0.04664 - 20.08 - 0.04016) / 1.08)
        o = feed(order(**lv), [bar(1, 19.90, 20.10, 19.80, 20.05)] + [bar(n, 20.10, 20.50, 19.50, 20.10) for n in range(2, 42)]
                 + [bar(42, 23.33, 23.50, 23.00, 23.40)])
        self.assertEqual((o.exit_kind, o.exit_raw, o.sessions_held), (F.EXIT_TARGET, 23.32, 41))


class CostsTimesTwoEveryPath(unittest.TestCase):
    """3.4 sensitivity rows: 'costs x 2: every cost doubles, the 4h of stop exits included'.
    'Limit-price fills (C, P) pay h' -> 2h under the row."""

    def test_the_target_fill_doubles(self):                                                           # D08
        o = feed(held(params=X2), [bar(2, 22.00, 23.01, 21.90, 22.50)], params=X2)       # rule 4: target at P
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TARGET, 23.00))
        self.assertAlmostEqual(o.exit_cost, 2 * 0.046)
        self.assertAlmostEqual(F.r_multiple(o), (23.00 - 0.092) - (20.00 + 0.08))        # 2.828
        o = feed(held(params=X2), [bar(2, 24.00, 24.50, 23.80, 24.20)], params=X2)       # rule 2: gap past P
        self.assertAlmostEqual(o.exit_cost, 2 * 0.046)

    def test_the_fill_at_the_ceiling_doubles(self):                                                   # D11
        o = held(CEILING_ENTRY, params=X2)
        self.assertEqual((o.entry_kind, o.entry_raw), (F.ENTRY_CEILING, 20.25))
        self.assertAlmostEqual(o.entry_cost, 2 * 0.002 * 20.25)                          # 0.081

    def test_the_row_doubles_costs_and_moves_no_fill_price(self):                                     # G21 G22
        # 3.4: 'There is no separate slippage term, so "at the open" holds literally for opening entries,
        # gap-through stops and time exits.' The row doubles the costs; R follows from 3.5.
        o = feed(held(OPEN_ENTRY, params=X2), [bar(2, 18.80, 18.90, 18.50, 18.60)], params=X2)
        self.assertEqual((o.entry_kind, o.entry_raw, o.exit_kind, o.exit_raw), (F.ENTRY_OPEN, 20.20, F.EXIT_GAP_STOP, 18.80))
        self.assertAlmostEqual(F.r_multiple(o), (18.80 - 8 * 0.0376) - (20.20 + 4 * 0.0404))     # -1.8624
        o = feed(after_40_sessions(params=X2), [bar(42, 20.30, 20.40, 20.20, 20.35)], params=X2)
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TIME, 20.30))
        self.assertAlmostEqual(F.r_multiple(o), (20.30 - 4 * 0.0406) - (20.00 + 2 * 0.04))       # 0.0576


class OpeningMultipleIsReadFromParams(unittest.TestCase):
    """Section 2: params.py holds 'every number in this spec'. 3.4: 'Opening fills pay 2h: gap-up entries
    and time exits'. The suite pins this for the stop multiple (4) only."""

    def test_two_is_the_opening_multiple_and_it_is_read_from_params(self):                            # A09 B16
        self.assertEqual(PARAMS.open_fill_cost_mult, 2.0)
        three = replace(P0, open_fill_cost_mult=3.0)
        o = held(OPEN_ENTRY, params=three)
        self.assertAlmostEqual(o.entry_cost, 3 * 0.002 * 20.20)
        o = feed(after_40_sessions(params=three), [bar(42, 20.30, 20.40, 20.20, 20.35)], params=three)
        self.assertEqual(o.exit_kind, F.EXIT_TIME)
        self.assertAlmostEqual(o.exit_cost, 3 * 0.002 * 20.30)


class TradeThroughIsReadFromParams(unittest.TestCase):
    """Section 2: params.py holds 'every number in this spec'; 3.4: 'Resting limits need a 1-cent trade-through,
    at the open as well as intraday'. With the parameter set to two cents, rule 2 has to follow it."""

    def test_rule_2_uses_the_trade_through_parameter(self):                                           # E14
        self.assertEqual(PARAMS.trade_through, 0.01)
        two = replace(P0, trade_through=0.02)
        o = feed(held(params=two), [bar(2, 23.01, 23.01, 22.50, 22.80)], params=two)     # one cent through: not enough now
        self.assertEqual(o.state, F.OPEN)
        o = feed(held(params=two), [bar(2, 23.02, 23.50, 18.90, 19.50)], params=two)     # two cents through at the open: rule 2
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TARGET, 23.00))


class TimeExitAtTheOpen(unittest.TestCase):
    """3.4 Time exit: 'A session-41 open at P, or less than a cent above it, is not a gap past the target,
    so it is sold at that open. Net of its 2h it is below P.'"""

    def test_session_41_open_a_fraction_of_a_cent_above_p_is_sold_at_that_open(self):                 # G08
        o = feed(after_40_sessions(), [bar(42, 23.005, 23.50, 22.90, 23.40)])
        self.assertEqual((o.exit_kind, o.exit_raw), (F.EXIT_TIME, 23.005))
        self.assertAlmostEqual(o.exit_cost, 2 * 0.002 * 23.005)                          # 0.09202
        self.assertAlmostEqual(F.r_multiple(o), (23.005 - 0.09202) - 20.04)              # 2.87298
        self.assertLess(o.exit_raw - o.exit_cost, 23.00)                                 # net of its 2h, below P


class SealExemptionScope(unittest.TestCase):
    """3.7 step 2 (ruling 2026-11-11): 'the 14 real fill records and the bars those trades need, entry day
    through exit day ... Under this exemption any other ticker, date, entry price or stop inside the
    window is still refused.' Records used (known_answer.py / the fixture):
        CXM      2026-06-09 .. 06-18   entry 5.33   stop 5.00
        TASK #1  2026-05-07            entry 6.37   stop 6.27
        TASK #2  2026-05-08            entry 6.31   stop 6.20
        F        2026-09-01 .. 09-09   entry 13.98  stop 13.68
        FRO      2026-07-30 .. 08-11   entry 37.00  stop 35.74 (bar basis)
    """

    def known(self, ticker, signal, session, trigger, stop, ceiling=None, seal=F.KNOWN_ANSWER_REPLAY):
        o = F.Order(ticker=ticker, signal_date=signal, trigger=trigger, ceiling=trigger if ceiling is None else ceiling,
                    stop=stop, target=3 * trigger, window=1, atr=0.5, tier_bps=20.0)
        b = F.Bar(session, trigger, trigger + 0.05, trigger - 0.05, trigger)
        return F.step(o, session, b, breadth_ok=True, params=P0, seal=seal)

    def refused(self, *args, **kw):
        with self.assertRaises(F.SealedSessionError):
            self.known(*args, **kw)

    def test_the_real_records_themselves_run(self):                      # positive controls for the cases below
        d = dt.date
        self.assertEqual(self.known("CXM", d(2026, 6, 8), d(2026, 6, 9), 5.33, 5.00).state, F.OPEN)
        self.assertEqual(self.known("TASK", d(2026, 5, 6), d(2026, 5, 7), 6.37, 6.27).state, F.OPEN)
        self.assertEqual(self.known("TASK", d(2026, 5, 7), d(2026, 5, 8), 6.31, 6.20).state, F.OPEN)
        self.assertEqual(self.known("F", d(2026, 8, 31), d(2026, 9, 1), 13.98, 13.68).state, F.OPEN)
        self.assertEqual(self.known("FRO", d(2026, 7, 29), d(2026, 7, 30), 37.00, 35.74).state, F.OPEN)

    def test_a_ticker_that_only_starts_like_a_record_ticker_is_refused(self):                         # H02
        self.refused("FRO", dt.date(2026, 8, 31), dt.date(2026, 9, 1), 13.98, 13.68)     # F's numbers under FRO
        self.refused("FORD", dt.date(2026, 8, 31), dt.date(2026, 9, 1), 13.98, 13.68)

    def test_a_ticker_that_is_a_prefix_of_a_record_ticker_is_refused(self):                           # H03
        self.refused("F", dt.date(2026, 7, 29), dt.date(2026, 7, 30), 37.00, 35.74)      # FRO's numbers under F
        self.refused("CX", dt.date(2026, 6, 8), dt.date(2026, 6, 9), 5.33, 5.00)

    def test_a_lower_case_ticker_is_another_ticker(self):                                             # H32
        self.refused("cxm", dt.date(2026, 6, 8), dt.date(2026, 6, 9), 5.33, 5.00)

    def test_an_entry_price_a_fraction_of_a_cent_off_is_refused(self):                                # H06 H33
        self.refused("CXM", dt.date(2026, 6, 8), dt.date(2026, 6, 9), 5.334, 5.00)
        self.refused("CXM", dt.date(2026, 6, 8), dt.date(2026, 6, 9), 5.326, 5.00)

    def test_a_stop_above_the_real_stop_is_refused(self):                                             # H11
        self.refused("CXM", dt.date(2026, 6, 8), dt.date(2026, 6, 9), 5.33, 5.01)

    def test_a_stop_a_fraction_of_a_cent_off_is_refused(self):                                        # H13
        self.refused("CXM", dt.date(2026, 6, 8), dt.date(2026, 6, 9), 5.33, 5.004)
        self.refused("CXM", dt.date(2026, 6, 8), dt.date(2026, 6, 9), 5.33, 4.996)

    def test_the_real_entry_has_to_be_the_trigger_not_just_the_ceiling(self):                         # H09
        self.refused("CXM", dt.date(2026, 6, 8), dt.date(2026, 6, 9), 5.20, 5.00, ceiling=5.33)

    def test_a_record_is_refused_on_another_records_dates(self):                                      # H22
        self.refused("CXM", dt.date(2026, 7, 31), dt.date(2026, 8, 3), 5.33, 5.00)       # inside FRO's and AEO's spans

    def test_task_one_is_refused_on_task_twos_day_and_the_reverse(self):                              # H23
        self.refused("TASK", dt.date(2026, 5, 7), dt.date(2026, 5, 8), 6.37, 6.27)
        self.refused("TASK", dt.date(2026, 5, 6), dt.date(2026, 5, 7), 6.31, 6.20)

    def test_the_entry_of_one_record_with_the_stop_of_another_is_refused(self):                       # H24
        self.refused("TASK", dt.date(2026, 5, 6), dt.date(2026, 5, 7), 6.37, 6.20)
        self.refused("TASK", dt.date(2026, 5, 7), dt.date(2026, 5, 8), 6.31, 6.27)

    def test_a_record_still_open_is_refused_the_session_after_its_real_exit_day(self):                # H29
        # CXM entered for real on 2026-06-09; if the replay has not exited by 06-18 it may not run on.
        o = F.Order(ticker="CXM", signal_date=dt.date(2026, 6, 8), trigger=5.33, ceiling=5.33, stop=5.00, target=15.99,
                    window=1, atr=0.2829, tier_bps=20.0)
        d = dt.date(2026, 6, 9)
        o = F.step(o, d, F.Bar(d, 5.33, 5.48, 5.26, 5.40), breadth_ok=True, params=P0, seal=F.KNOWN_ANSWER_REPLAY)
        self.assertEqual((o.state, o.entry_date), (F.OPEN, d))
        for dd in (10, 11, 12, 15, 16, 17, 18):                           # no bars: the trade stays open
            o = F.step(o, dt.date(2026, 6, dd), None, breadth_ok=True, params=P0, seal=F.KNOWN_ANSWER_REPLAY)
        self.assertEqual((o.state, o.last_session), (F.OPEN, dt.date(2026, 6, 18)))
        with self.assertRaises(F.SealedSessionError):
            F.step(o, dt.date(2026, 6, 19), None, breadth_ok=True, params=P0, seal=F.KNOWN_ANSWER_REPLAY)


if __name__ == "__main__":
    unittest.main()
