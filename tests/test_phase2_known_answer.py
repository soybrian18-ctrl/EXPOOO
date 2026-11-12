"""Known-answer contract for the Phase 2 fill model (spec section 2, 3.4; build step B1b).

The experiment's 14 real stop-outs are replayed through loops/phase2/fills.py on
the Schwab daily bars recorded in tests/fixtures/phase2_known_answer.json. No
network.

For each trade the model starts from a pending order whose trigger and ceiling
both equal the real entry fill, so the model enters at the real price on the
real entry day, then runs the real stop. Two contracts:

  1. Structure: the model enters on the real entry day at the real fill, exits
     on the real exit day, and classifies the exit from the bars -- 12 intraday
     stops and 2 gap-throughs (AR, RRC).
  2. Non-optimism: the model's net exit price is never above the real exit
     fill. Every stop exit pays 4 half-spreads (ruling 2026-11-11); 4 is the
     smallest whole number that passes, and it ties CXM's real fill exactly.

Real prices are first moved onto the bar basis (``basis_shift``): Schwab rebased
FRO's history by $1.60 for its 2026-09-18 special distribution.

These are April-September 2026 sessions, inside the sealed out-of-sample window
(spec 3.7 step 2). The replay is the one exemption from the seal
(``fills.KNOWN_ANSWER_REPLAY``), scoped to these 14 real fill records and the
bars those trades need: loops/phase2/known_answer.py lists them, and a test
below compares that list with the fixture record by record.

Run:  python -m unittest tests.test_phase2_known_answer
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import unittest
from dataclasses import replace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "loops"))

from phase2 import fills as F  # noqa: E402
from phase2 import known_answer  # noqa: E402
from phase2.params import PARAMS  # noqa: E402

with open(os.path.join(HERE, "fixtures", "phase2_known_answer.json")) as fh:
    TRADES = json.load(fh)["trades"]

GAP_THROUGHS = {"AR", "RRC"}                 # classified from the bars: open <= stop on the exit day
FAR_TARGET = known_answer.REPLAY_TARGET_MULT  # target at 3x the entry price: never reached in these replays


def replay(trade: dict, params, seal: str = F.KNOWN_ANSWER_REPLAY) -> F.Order:
    shift = trade["basis_shift"]
    entry, stop = trade["entry_fill"] + shift, trade["stop"] + shift
    entry_date = dt.date.fromisoformat(trade["entry_date"])
    order = F.Order(ticker=trade["ticker"], signal_date=entry_date - dt.timedelta(days=1),
                    trigger=entry, ceiling=entry, stop=stop, target=entry * FAR_TARGET, window=1,
                    atr=trade["atr"], tier_bps=trade["tier_bps"])
    for d, o, h, lo, c in trade["bars"]:
        day = dt.date.fromisoformat(d)
        order = F.step(order, day, F.Bar(day, o, h, lo, c), breadth_ok=True, params=params, seal=seal)
    return order


class KnownAnswerStructure(unittest.TestCase):
    """Dates, entry price and gap/intraday classification."""

    P0 = PARAMS

    def test_fourteen_real_stop_outs(self):
        self.assertEqual(len(TRADES), 14)

    def test_the_replay_needs_the_named_exemption_from_the_oos_seal(self):
        for t in TRADES:
            with self.subTest(t["label"]):
                with self.assertRaises(F.SealedSessionError):
                    replay(t, self.P0, seal=F.SEALED)

    def test_real_fills_lie_inside_their_bars_once_on_the_bar_basis(self):
        for t in TRADES:
            first, last = t["bars"][0], t["bars"][-1]
            entry, exit_ = t["entry_fill"] + t["basis_shift"], t["real_exit"] + t["basis_shift"]
            with self.subTest(t["label"]):
                self.assertTrue(first[3] <= entry <= first[2], "entry fill outside its bar")
                self.assertTrue(last[3] <= exit_ <= last[2], "exit fill outside its bar")

    def test_model_enters_at_the_real_fill_on_the_real_day(self):
        for t in TRADES:
            o = replay(t, self.P0)
            with self.subTest(t["label"]):
                self.assertEqual(o.entry_date, dt.date.fromisoformat(t["entry_date"]))
                self.assertAlmostEqual(o.entry_raw, t["entry_fill"] + t["basis_shift"])

    def test_model_stops_out_on_the_real_exit_day(self):
        for t in TRADES:
            o = replay(t, self.P0)
            with self.subTest(t["label"]):
                self.assertEqual(o.state, F.CLOSED)
                self.assertEqual(o.exit_date, dt.date.fromisoformat(t["exit_date"]))

    def test_exit_classification_comes_from_the_bars(self):
        for t in TRADES:
            o = replay(t, self.P0)
            with self.subTest(t["label"]):
                expected = F.EXIT_GAP_STOP if t["label"] in GAP_THROUGHS else F.EXIT_STOP
                self.assertEqual(o.exit_kind, expected)



def optimistic_on(params) -> list[str]:
    """Trades where the model's net exit is above the real exit fill."""
    return sorted(t["label"] for t in TRADES
                  if (lambda o: o.exit_raw - o.exit_cost)(replay(t, params)) > t["real_exit"] + t["basis_shift"] + 1e-9)


class KnownAnswerNonOptimism(unittest.TestCase):
    """The contract itself (spec section 2): never more optimistic than Schwab's real fills."""

    def test_model_is_never_more_optimistic_than_the_real_fill(self):
        for t in TRADES:
            o = replay(t, PARAMS)
            with self.subTest(t["label"]):
                self.assertLessEqual(o.exit_raw - o.exit_cost, t["real_exit"] + t["basis_shift"] + 1e-9)
        self.assertEqual(optimistic_on(PARAMS), [])

    def test_every_stop_exit_pays_four_half_spreads_on_its_fill_price(self):
        for t in TRADES:
            o = replay(t, PARAMS)
            with self.subTest(t["label"]):
                h = max(t["tier_bps"] * 1e-4 * o.exit_raw, 0.005)
                self.assertAlmostEqual(o.exit_cost, 4 * h)

    def test_cxm_is_the_binding_case_and_the_model_ties_it(self):
        # stop 5.00 in the 20 bps tier: h = 0.01, so 5.00 - 4 x 0.01 = 4.96, the real fill
        cxm = next(t for t in TRADES if t["label"] == "CXM")
        o = replay(cxm, PARAMS)
        self.assertAlmostEqual(o.exit_raw - o.exit_cost, 4.96)
        self.assertAlmostEqual(cxm["real_exit"], 4.96)

    def test_four_is_the_smallest_whole_number_of_half_spreads_that_passes(self):
        # CXM: 5.00 - 3 x 0.01 = 4.97, one cent above its real 4.96.
        self.assertEqual(optimistic_on(replace(PARAMS, stop_exit_cost_mult=3.0)), ["CXM"])
        # RRC (gap-through at 38.00, 10 bps): 38.00 - 2 x 0.038 = 37.924, above its real 37.90; 3 x gives 37.886.
        self.assertEqual(optimistic_on(replace(PARAMS, stop_exit_cost_mult=2.0)), ["CXM", "RRC"])
        self.assertEqual(optimistic_on(replace(PARAMS, stop_exit_cost_mult=1.0)), ["CXM", "RRC"])


class KnownAnswerScope(unittest.TestCase):
    """Ruling 2026-11-11: the seal exemption covers the 14 real fill records and the bars they need."""

    def test_the_package_table_is_the_fixture_record_for_record(self):
        want = [(t["label"], t["ticker"], dt.date.fromisoformat(t["entry_date"]), dt.date.fromisoformat(t["exit_date"]),
                 round(t["entry_fill"] + t["basis_shift"], 6), round(t["stop"] + t["basis_shift"], 6)) for t in TRADES]
        self.assertEqual([tuple(r) for r in known_answer.RECORDS], want)       # fills are not rounded to the cent
        self.assertEqual(len(known_answer.RECORDS), 14)

    def test_the_bars_each_trade_needs_run_from_its_entry_day_to_its_exit_day(self):
        for t in TRADES:
            with self.subTest(t["label"]):
                self.assertEqual((t["bars"][0][0], t["bars"][-1][0]), (t["entry_date"], t["exit_date"]))
        self.assertEqual(sum(len(t["bars"]) for t in TRADES), 62)

    def test_a_real_trade_with_one_number_changed_is_refused(self):
        for t in TRADES:
            for field in ("entry_fill", "stop"):
                with self.subTest(t["label"], field=field):
                    with self.assertRaises(F.SealedSessionError):
                        replay(dict(t, **{field: round(t[field] - 0.01, 2)}), PARAMS)

    def test_a_replay_with_any_other_order_field_changed_is_refused(self):
        # The exemption covers exact replays only: trigger = ceiling = real entry, real stop, the far target,
        # a one-session window on the real entry day.
        t = next(x for x in TRADES if x["label"] == "CCL")
        entry_day = dt.date.fromisoformat(t["entry_date"])
        base = dict(ticker=t["ticker"], signal_date=entry_day - dt.timedelta(days=1), trigger=t["entry_fill"],
                    ceiling=t["entry_fill"], stop=t["stop"], target=t["entry_fill"] * FAR_TARGET, window=1,
                    atr=t["atr"], tier_bps=t["tier_bps"])
        first = F.Bar(entry_day, *t["bars"][0][1:])
        self.assertEqual(F.step(F.Order(**base), entry_day, first, breadth_ok=True, params=PARAMS,
                                seal=F.KNOWN_ANSWER_REPLAY).state, F.OPEN)
        for change in (dict(ceiling=t["entry_fill"] + 0.50), dict(target=28.40), dict(window=2)):
            with self.subTest(change=change):
                with self.assertRaises(F.SealedSessionError):
                    F.step(F.Order(**dict(base, **change)), entry_day, first, breadth_ok=True, params=PARAMS,
                           seal=F.KNOWN_ANSWER_REPLAY)
        # a pending replay may act only on the real entry day
        later = dt.date.fromisoformat(t["bars"][1][0])
        with self.assertRaises(F.SealedSessionError):
            F.step(F.Order(**dict(base, signal_date=entry_day)), later, F.Bar(later, *t["bars"][1][1:]),
                   breadth_ok=True, params=PARAMS, seal=F.KNOWN_ANSWER_REPLAY)

    def test_marking_a_replay_on_a_sealed_session_needs_the_exemption_too(self):
        t = next(x for x in TRADES if x["label"] == "CCL")
        entry_day = dt.date.fromisoformat(t["entry_date"])
        o = F.step(F.Order(ticker=t["ticker"], signal_date=entry_day - dt.timedelta(days=1), trigger=t["entry_fill"],
                           ceiling=t["entry_fill"], stop=t["stop"], target=t["entry_fill"] * FAR_TARGET, window=1,
                           atr=t["atr"], tier_bps=t["tier_bps"]),
                   entry_day, F.Bar(entry_day, *t["bars"][0][1:]), breadth_ok=True, params=PARAMS,
                   seal=F.KNOWN_ANSWER_REPLAY)
        close = t["bars"][0][4]
        with self.assertRaises(F.SealedSessionError):
            F.evaluate_at_cutoff(o, entry_day, close, PARAMS)
        with self.assertRaises(F.SealedSessionError):
            F.close_at_mark(o, entry_day, close, PARAMS)
        self.assertEqual(F.evaluate_at_cutoff(o, entry_day, close, PARAMS, seal=F.KNOWN_ANSWER_REPLAY).status, "marked")

    def test_a_real_trade_under_another_ticker_is_refused(self):
        for t in TRADES:
            with self.subTest(t["label"]):
                with self.assertRaises(F.SealedSessionError):
                    replay(dict(t, ticker="ZZZZ"), PARAMS)


if __name__ == "__main__":
    unittest.main()
