"""Unit tests for Phase 2 order construction and paper sizing (loops/phase2/orders.py), no network.

Every expected value is typed from the spec text, never taken from the implementation: specs/phase2_spec.md
3.2, 3.4 "Order" and section 4 "Paper book", and the PHASE 2 RULES block of references/trading-rules.md
("sized on the ceiling price"):

    T = high(t) + 0.01, rounded UP to the cent      (the 3.4 sentence, ruled 2026-11-12)
    C = floor(T + 0.25 ATR);  S = floor(min(S0, T - k ATR));  P = ceil(T + 3 (T - S))
    N = floor(min($15 / (C - S), $262.50 / C)), at least 3 or unsizable

The 2026-11-12 review found that every sizing test of the draft had T = C, so sizing on the trigger passed.
Here the brackets have T < C wherever that matters, plus sub-cent highs and stops, float-noise inputs, and an
integer-cent oracle (``oracle``) for the sweeps. The fill model is called only on in-sample (2023) sessions,
with its default seal.

Run:  python -m unittest tests.test_phase2_orders
"""

from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import inspect
import math
import os
import random
import sys
import unittest
from decimal import ROUND_UP, Decimal as D, localcontext
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "loops"))

from phase2 import fills as F  # noqa: E402
from phase2 import orders as O  # noqa: E402
from phase2.params import PARAMS  # noqa: E402

ORDERS_PY = os.path.join(ROOT, "loops", "phase2", "orders.py")
ATR_ONLY = O.ATR_ONLY
SIGNAL_DAY = dt.date(2023, 1, 9)            # a Monday, in-sample (outside the sealed 2025-01-02..2026-10-30)


def cents(v: int) -> D:
    """A whole number of cents as a two-place Decimal: 2015 -> 20.15."""
    return D(v).scaleb(-2)


def money(v: int) -> str:
    """A whole number of cents as the ticket prints it: 2000 -> '20.00'."""
    return f"{v // 100}.{v % 100:02d}"


def hand(c: str, s: str) -> O.Bracket:
    """A bracket with ceiling c and stop s, its trigger halfway between them (so T < C) and a 3R target."""
    cc, ss = int(D(c) * 100), int(D(s) * 100)
    t = ss + max(1, (cc - ss) // 2)
    return O.Bracket(cents(t), cents(cc), cents(ss), cents(t + 3 * (t - ss)))


def oracle(t_c: int, atr4: int, k2: int, s0_u: Optional[int] = None) -> tuple[int, int, int, int, int]:
    """(T, C, S, P, N) from the spec text, in integers. T in cents; ATR in ten-thousandths of a dollar (the
    four places compute_levels rounds it to); k2 = 2k; the structural stop S0 in millionths (None: no S0)."""
    c = (400 * t_c + atr4) // 400                  # C = floor(T + ATR / 4), in cents
    s = (200 * t_c - k2 * atr4) // 200             # floor(T - k ATR)
    if s0_u is not None:
        s = min(s, s0_u // 10_000)                 # floor(min(S0, .)) = min(floor(S0), floor(.))
    p = t_c + 3 * (t_c - s)                        # T + 3 (T - S) is already whole cents
    n = min(1500 // (c - s), 26250 // c) if 0 < s < c else 0     # $15 and $262.50 in cents, at the CEILING
    return t_c, c, s, p, n


def built(trigger, atr, k, params=PARAMS, structural_stop=ATR_ONLY) -> O.Bracket:
    return O.build_bracket(trigger, atr, k, params, structural_stop=structural_stop)


class TriggerFromTheHigh(unittest.TestCase):
    """3.2 / 3.4: T = high(t) + 0.01. Rounded up to the cent: the sentence ruled 2026-11-12 (review finding 0)."""

    def t(self, high, params=PARAMS) -> D:
        return O.trigger_from_high(high, params)

    def test_a_whole_cent_high_gets_exactly_one_cent_more(self):
        self.assertEqual(self.t(12.95), D("12.96"))
        self.assertEqual(self.t(50.84), D("50.85"))
        self.assertEqual(self.t(64.12), D("64.13"))     # 64.12 + 0.01 is 64.13000000000001 in floats
        self.assertEqual(self.t(20), D("20.01"))
        self.assertEqual(self.t(D("64.12")), D("64.13"))

    def test_a_sub_cent_high_rounds_up_to_the_cent(self):
        # highs with three and four places, the kind the review found on about one signal day in four
        self.assertEqual(self.t(49.183), D("49.20"))    # ceil(49.193)
        self.assertEqual(self.t(41.315), D("41.33"))    # ceil(41.325)
        self.assertEqual(self.t(79.9299), D("79.94"))   # ceil(79.9399)
        self.assertEqual(self.t(12.952), D("12.97"))    # ceil(12.962)
        self.assertEqual(self.t(9.000001), D("9.02"))   # ceil(9.010001): a millionth over a cent rounds up
        self.assertEqual(self.t(D("49.183")), D("49.20"))

    def test_float_noise_either_side_of_a_cent_is_that_cent(self):
        for high in (math.nextafter(49.19, math.inf), math.nextafter(49.19, 0.0), 49.19):
            self.assertEqual(self.t(high), D("49.20"), repr(high))

    def test_the_trigger_is_one_to_two_cents_above_the_high(self):
        # high + 0.01 <= T < high + 0.02, and T = high + 0.01 exactly for a whole-cent high (six-place highs)
        rng = random.Random(20261112)
        for _ in range(5000):
            h_u = rng.randint(4_000_000, 120_000_000)                 # the high in millionths
            if rng.random() < 0.3:
                h_u -= h_u % 10_000                                    # a whole-cent high
            t = self.t(h_u / 1_000_000)
            self.assertEqual(t, cents(-(-(h_u + 10_000) // 10_000)), h_u)   # ceil((high + 0.01) in cents)
            self.assertTrue(D(h_u).scaleb(-6) + D("0.01") <= t < D(h_u).scaleb(-6) + D("0.02"), h_u)

    def test_the_trigger_is_a_two_place_decimal(self):
        for high, text in ((49.183, "49.20"), (20, "20.01"), (D("5E+1"), "50.01"), (64.12, "64.13")):
            self.assertEqual(str(self.t(high)), text)

    def test_bad_highs_are_refused(self):
        for bad in (0, 0.0, -1.0, D("-49.18"), float("nan"), float("inf"), D("NaN"), 1e70):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.t(bad)
        for bad in (None, "49.18", True):
            with self.assertRaises(TypeError, msg=repr(bad)):
                self.t(bad)

    def test_the_offset_is_params_trigger_offset_not_the_trade_through(self):
        self.assertEqual(self.t(49.183, dataclasses.replace(PARAMS, trigger_offset=0.02)), D("49.21"))
        self.assertEqual(self.t(64.12, dataclasses.replace(PARAMS, trigger_offset=0.02)), D("64.14"))
        # trade_through is fills.py's resting-limit rule, a different spec number
        self.assertEqual(self.t(49.183, dataclasses.replace(PARAMS, trade_through=0.05)), D("49.20"))

    def test_params_are_required(self):
        with self.assertRaises(TypeError):
            O.trigger_from_high(49.183)                                # no params: an error, never a default
        with self.assertRaises(TypeError):
            O.trigger_from_high(49.183, {"trigger_offset": 0.01})


class BracketLevels(unittest.TestCase):
    """3.4: C = floor(T + 0.25 ATR); S = floor(min(S0, T - k ATR)); P = ceil(T + 3 (T - S))."""

    def test_levels_and_rounding_directions(self):
        # T 20.00, ATR 0.6133, k 1.5: C = floor(20.153325) = 20.15; S = floor(19.08005) = 19.08;
        # P = 20.00 + 3 x 0.92 = 22.76
        b = built(20.00, 0.6133, 1.5)
        self.assertEqual(tuple(b), (D("20.00"), D("20.15"), D("19.08"), D("22.76")))
        self.assertEqual(b.planned_risk, D("0.92"))

    def test_the_ceiling_and_the_stop_round_down(self):
        # T 30.00, ATR 1.0396: C = floor(30.2599) = 30.25 (nearest would be 30.26); S = floor(28.4406) = 28.44
        b = built(30.00, 1.0396, 1.5)
        self.assertEqual((b.ceiling, b.stop, b.target), (D("30.25"), D("28.44"), D("34.68")))
        # a stop a hair below a cent still rounds down a whole cent: 30 - 1.5 x 1.04001 = 28.439985
        self.assertEqual(built(30.00, 1.04001, 1.5).stop, D("28.43"))
        # a ceiling a hair below a cent: 20 + 0.25 x 0.6396 = 20.1599 -> 20.15
        self.assertEqual(built(20.00, 0.6396, 1.5).ceiling, D("20.15"))

    def test_the_target_rounds_up(self):
        # Whole-cent T and S with a 3R target never need rounding, so other multiples exercise the direction.
        # 2.5R (review): T 20.00, ATR 1.49, k 1.0: S = 18.51; P = ceil(20.00 + 2.5 x 1.49) = ceil(23.725) = 23.73
        self.assertEqual(built(20.00, 1.49, 1.0, dataclasses.replace(PARAMS, target_r=2.5)).target, D("23.73"))
        # 2.3R: S = 18.59; P = ceil(20.00 + 2.3 x 1.41) = ceil(23.243) = 23.25 (nearest would be 23.24)
        self.assertEqual(built(20.00, 1.41, 1.0, dataclasses.replace(PARAMS, target_r=2.3)).target, D("23.25"))

    def test_exact_cents_stay_exact(self):
        # T 64.13, ATR 3.30: C = floor(64.955) = 64.95; S = 64.13 - 4.95 = 59.18; P = 64.13 + 14.85 = 78.98
        self.assertEqual(tuple(built(64.13, 3.30, 1.5)), (D("64.13"), D("64.95"), D("59.18"), D("78.98")))

    def test_the_stop_is_the_lower_of_the_structural_stop_and_the_atr_stop(self):
        # 3.4 (D2): S = floor(min(S0, T - k x ATR)). T 20.00, ATR 1.00, k 1.5 -> ATR stop 18.50
        self.assertEqual(built(20.00, 1.00, 1.5, structural_stop=18.20).stop, D("18.20"))     # S0 lower
        self.assertEqual(built(20.00, 1.00, 1.5, structural_stop=19.10).stop, D("18.50"))     # ATR stop lower
        self.assertEqual(built(20.00, 1.00, 1.5, structural_stop=18.207).stop, D("18.20"))    # rounds down
        self.assertEqual(built(20.00, 1.00, 1.5, structural_stop=ATR_ONLY).stop, D("18.50"))
        # a wider structural stop widens the target too: P = 20.00 + 3 x 1.80 = 25.40
        self.assertEqual(built(20.00, 1.00, 1.5, structural_stop=18.20).target, D("25.40"))

    def test_each_stop_width(self):
        for k, stop, target in ((1.0, "19.00", "23.00"), (1.5, "18.50", "24.50"), (2.0, "18.00", "26.00")):
            b = built(20.00, 1.00, k)
            self.assertEqual((b.stop, b.target), (D(stop), D(target)))

    def test_a_ceiling_equal_to_the_trigger_is_allowed(self):
        # ATR 0.03: C = floor(20.0075) = 20.00 = T (3.4 allows T <= C); S = floor(19.97) = 19.97; P = 20.09
        self.assertEqual(tuple(built(20.00, 0.03, 1.0)), (D("20.00"), D("20.00"), D("19.97"), D("20.09")))

    def test_a_stop_at_or_below_zero_is_refused(self):
        with self.assertRaises(ValueError):
            built(1.50, 1.00, 1.5)              # S = floor(0.00) = 0.00 exactly
        with self.assertRaises(ValueError):
            built(1.00, 1.00, 1.5)              # S = -0.50
        with self.assertRaises(ValueError):
            built(20.00, 1.00, 1.5, structural_stop=-1.00)

    def test_the_drill_ticket_of_2026_11_11(self):
        # close 50.67, after-hours last 50.72, ATR14 1.2133: T = ceil(50.72 + 0.12133) = 50.85 (the drill's own
        # trigger rule); C = floor(51.153325) = 51.15; S = floor(49.03005) = 49.03; P = 50.85 + 3 x 1.82 = 56.31
        b = built(50.85, 1.2133, 1.5)
        self.assertEqual(tuple(b), (D("50.85"), D("51.15"), D("49.03"), D("56.31")))
        self.assertEqual(O.paper_shares(b, PARAMS).shares, 5)

    def test_a_sub_cent_high_becomes_a_bracket(self):
        # review finding 0: high 49.183 used to give a trigger of 49.193 that build_bracket refused
        b = built(O.trigger_from_high(49.183, PARAMS), 1.2133, 1.5)
        # T 49.20: C = floor(49.503325) = 49.50; S = floor(47.38005) = 47.38; P = 49.20 + 3 x 1.82 = 54.66
        self.assertEqual(tuple(b), (D("49.20"), D("49.50"), D("47.38"), D("54.66")))

    def test_brackets_and_counts_match_the_integer_oracle(self):
        # Realistic inputs: T $5-100 (whole cents, or from a six-place high), ATR 1-12% of the price to four
        # places, every k, S0 absent, whole cents (M1) or low(t) - 0.2 ATR to six places in floats (M2).
        rng = random.Random(20261113)
        bad = []
        for _ in range(8000):
            mode = rng.randrange(4)
            if mode == 3:
                h_u = rng.randint(4_990_000, 99_990_000)
                t_c = -(-(h_u + 10_000) // 10_000)
                t_in = O.trigger_from_high(h_u / 1_000_000, PARAMS)
            else:
                t_c = rng.randint(500, 10_000)
                t_in = t_c / 100
            atr4 = rng.randint(t_c, 12 * t_c)
            k2 = rng.choice((2, 3, 4))
            s0_u, s0_in = None, ATR_ONLY
            if mode == 1:
                s0_c = t_c - rng.randint(1, max(1, 3 * atr4 // 100))
                s0_u, s0_in = s0_c * 10_000, s0_c / 100
            elif mode == 2:
                low_u = t_c * 10_000 - 10_000 - rng.randint(0, 150 * atr4)
                low_u -= low_u % rng.choice((10_000, 1_000, 100, 1))
                s0_u, s0_in = low_u - 20 * atr4, low_u / 1_000_000 - 0.2 * (atr4 / 10_000)
            want = oracle(t_c, atr4, k2, s0_u)
            b = O.build_bracket(t_in, atr4 / 10_000, k2 / 2, PARAMS, structural_stop=s0_in)
            got = tuple(b) + (O.paper_shares(b, PARAMS).shares,)
            if got != tuple(cents(v) for v in want[:4]) + (want[4],):
                bad.append((t_in, atr4, k2, s0_in, got, want))
        self.assertEqual(bad, [])


class BracketInputs(unittest.TestCase):
    """No silent defaults or inputs (spec 8): bad input is an error, never a plausible order (review finding 4)."""

    def test_the_trigger_must_be_a_positive_whole_cent_price(self):
        for bad in (20.005, 49.183 + 0.01, D("20.001"), 0, 0.0, -1.0, D("-20.00")):
            with self.assertRaises(ValueError, msg=repr(bad)):
                built(bad, 1.0, 1.5)
        with self.assertRaisesRegex(ValueError, "trigger_from_high"):
            built(49.193, 1.0, 1.5)

    def test_a_float_noise_trigger_is_the_cent_it_means(self):
        t = 64.12 + 0.01                                   # 64.13000000000001
        self.assertEqual(built(t, 3.30, 1.5), built(64.13, 3.30, 1.5))
        self.assertEqual(built(t, 3.30, 1.5).trigger, D("64.13"))

    def test_every_number_type_gives_the_same_bracket(self):
        want = (D("20.00"), D("20.25"), D("18.50"), D("24.50"))
        for t in (20, 20.0, D("20"), D("20.000"), D("2E+1")):
            for atr in (1, 1.0, D("1.00")):
                for k in (1.5, D("1.5"), D("1.50")):
                    self.assertEqual(tuple(built(t, atr, k)), want, (t, atr, k))

    def test_non_numbers_are_refused(self):
        for args in (("20.00", 1.0, 1.5), (True, 1.0, 1.5), (None, 1.0, 1.5), (20.0, "1.0", 1.5), (20.0, 1.0, None),
                     (20.0, 1.0, True)):
            with self.assertRaises(TypeError, msg=repr(args)):
                built(*args)
        with self.assertRaises(TypeError):
            built(20.0, 1.0, 1.5, structural_stop="18.20")

    def test_non_finite_inputs_raise_value_error(self):
        nan, inf = float("nan"), float("inf")
        for args, s0 in (((inf, 1.0, 1.5), ATR_ONLY), ((20.0, inf, 1.5), ATR_ONLY), ((20.0, 1.0, inf), ATR_ONLY),
                         ((20.0, nan, 1.5), ATR_ONLY), ((D("NaN"), 1.0, 1.5), ATR_ONLY), ((20.0, 1.0, 1.5), nan),
                         ((20.0, 1.0, 1.5), -inf), ((20.0, 1.0, 1.5), D("-Infinity"))):
            with self.assertRaisesRegex(ValueError, "finite", msg=repr((args, s0))):
                built(*args, structural_stop=s0)

    def test_the_atr_must_be_positive(self):
        for bad in (0, 0.0, -1.0, 0.0000004):            # the last reads as 0.000000 at the millionth
            with self.assertRaises(ValueError, msg=repr(bad)):
                built(20.00, bad, 1.5)

    def test_k_must_be_a_spec_variant(self):
        for bad in (1.7, 0.5, 2.5, 1.25, 0, -1.5):
            with self.assertRaises(ValueError, msg=repr(bad)):
                built(20.00, 1.00, bad)
        self.assertEqual(built(20.00, 1.00, 1).stop, D("19.00"))
        self.assertEqual(built(20.00, 1.00, 2).stop, D("18.00"))

    def test_a_structural_stop_at_or_above_the_trigger_is_refused(self):
        for s0 in (20.00, 20.0000001, 25.00, D("20.000"), D("20.01"), float("inf")):
            with self.assertRaises(ValueError, msg=repr(s0)):
                built(20.00, 1.00, 1.5, structural_stop=s0)
        self.assertEqual(built(20.00, 1.00, 1.5, structural_stop=19.99).stop, D("18.50"))   # just below: allowed

    def test_the_structural_stop_is_required_and_keyword_only(self):
        parameter = inspect.signature(O.build_bracket).parameters["structural_stop"]
        self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(parameter.default, inspect.Parameter.empty)
        with self.assertRaises(TypeError):
            O.build_bracket(20.00, 1.00, 1.5, PARAMS)                          # forgotten
        with self.assertRaisesRegex(TypeError, "ATR_ONLY"):
            O.build_bracket(20.00, 1.00, 1.5, PARAMS, structural_stop=None)    # None is not "no stop"
        with self.assertRaises(TypeError):
            O.build_bracket(20.00, 1.00, 1.5, PARAMS, 18.20)                   # positional

    def test_params_are_required(self):
        with self.assertRaises(TypeError):
            O.build_bracket(20.00, 1.00, 1.5, structural_stop=ATR_ONLY)        # no params: an error
        with self.assertRaises(TypeError):
            O.build_bracket(20.00, 1.00, 1.5, dataclasses.asdict(PARAMS), structural_stop=ATR_ONLY)

    def test_inputs_finer_than_a_millionth_are_read_at_the_millionth(self):
        # Review note 7: the millionth is the price resolution, as in fills.py. An input with genuine digits
        # beyond the sixth is read at its nearest millionth, whatever its type, so ATR 1.0000004 is 1.000000
        # (S = 19.00 at T 20, k 1.0; the unrounded value would give 18.99) and S0 18.1999996 is 18.200000.
        for atr in (1.0000004, D("1.0000004")):
            self.assertEqual(built(20.00, atr, 1.0).stop, D("19.00"))
        for s0 in (18.1999996, D("18.1999996")):
            self.assertEqual(built(20.00, 1.00, 1.5, structural_stop=s0).stop, D("18.20"))
        self.assertEqual(built(20.00, D("0.6133000004"), 1.5), built(20.00, 0.6133000004, 1.5))

    def test_a_level_a_millionth_below_a_cent_still_rounds_down(self):
        self.assertEqual(built(20.00, 1.00, 1.0, structural_stop=D("18.199999")).stop, D("18.19"))
        self.assertEqual(built(20.00, 1.2345, 1.0, structural_stop=18.446899 - 0.2 * 1.2345).stop, D("18.19"))
        self.assertEqual(built(20.00, D("0.639996"), 1.0).ceiling, D("20.15"))
        self.assertEqual(built(20.00, D("1.000001"), 1.0, structural_stop=19.50).stop, D("18.99"))
        self.assertEqual(built(20.00, D("0.666667"), 1.5).stop, D("18.99"))

    def test_the_atr_only_marker_survives_copy_and_pickle(self):
        import copy
        import pickle
        for f in (copy.copy, copy.deepcopy, lambda m: pickle.loads(pickle.dumps(m))):
            self.assertIs(f(O.ATR_ONLY), O.ATR_ONLY)

    def test_a_tie_at_half_a_millionth_goes_to_the_even_millionth(self):
        # as Python's round() breaks ties. T 20.00, k 1.0: ATR 1.0000005 reads as 1.000000, so S = 19.00;
        # ATR 1.0000015 reads as 1.000002, so S = floor(18.999998) = 18.99
        self.assertEqual(built(20.00, D("1.0000005"), 1.0).stop, D("19.00"))
        self.assertEqual(built(20.00, D("1.0000015"), 1.0).stop, D("18.99"))

    def test_numbers_too_large_to_hold_exactly_raise_value_error(self):
        for args in ((1e70, 1.0, 1.5), (20.0, 1e70, 1.5), (D("1E+70"), 1.0, 1.5)):
            with self.assertRaises(ValueError, msg=repr(args)):
                built(*args)

    def test_the_callers_decimal_context_changes_nothing(self):
        b = built(50.85, 1.2133, 1.5)
        lines = O.ticket_lines("BAC", b, PARAMS)
        with localcontext() as ctx:
            ctx.prec, ctx.rounding = 3, ROUND_UP
            self.assertEqual(O.trigger_from_high(49.183, PARAMS), D("49.20"))
            self.assertEqual(built(50.85, 1.2133, 1.5), b)
            self.assertEqual(built(64.13, 3.30, 1.5).ceiling, D("64.95"))
            self.assertEqual(O.paper_shares(b, PARAMS).shares, 5)
            self.assertEqual(O.ticket_lines("BAC", b, PARAMS), lines)
            self.assertEqual(b.planned_risk, D("1.82"))


class TheBracketRecord(unittest.TestCase):
    """A Bracket is two-place whole cents with 0 < S < T <= C < P, or it cannot be made (review findings 2, 4)."""

    def test_every_level_is_a_two_place_decimal(self):
        for t in (20.0, 20, D("20"), D("20.000"), 50.1, D("50.10"), D("5E+1")):
            b = built(t, 1.00, 1.0)
            for v in b:
                self.assertIsInstance(v, D)
                self.assertEqual(v.as_tuple().exponent, -2, (t, v))
        self.assertEqual(str(built(50.10, 1.2133, 1.5).trigger), "50.10")
        self.assertEqual(str(built(D("5E+1"), 1.00, 1.0).trigger), "50.00")

    def test_a_bracket_out_of_order_cannot_be_made(self):
        for t, c, s, p in (("20.00", "20.25", "20.00", "23.00"),     # S = T
                           ("20.00", "20.25", "20.10", "23.00"),     # S > T
                           ("20.30", "20.25", "19.00", "23.00"),     # T > C
                           ("20.00", "23.00", "19.00", "23.00"),     # C = P
                           ("1.50", "1.75", "0.00", "6.00"),         # S = 0
                           ("1.50", "1.75", "-0.50", "7.50")):       # S < 0
            with self.assertRaises(ValueError, msg=(t, c, s, p)):
                O.Bracket(D(t), D(c), D(s), D(p))

    def test_a_level_that_is_not_two_place_cents_cannot_be_made(self):
        good = dict(trigger=D("20.00"), ceiling=D("20.25"), stop=D("18.50"), target=D("24.50"))
        for name in good:
            for bad in (D("20.0"), D("20"), D("20.005"), D("NaN"), D("Infinity")):
                with self.assertRaises(ValueError, msg=(name, bad)):
                    O.Bracket(**dict(good, **{name: bad}))
            for bad in (20.0, 20, "20.00", None):
                with self.assertRaises(TypeError, msg=(name, bad)):
                    O.Bracket(**dict(good, **{name: bad}))

    def test_a_bracket_cannot_be_changed_or_replaced_into_a_bad_one(self):
        b = built(20.00, 1.00, 1.5)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            b.stop = D("19.99")                                    # type: ignore[misc]
        with self.assertRaises(ValueError):
            dataclasses.replace(b, stop=D("20.00"))

    def test_the_levels_for_the_fill_model(self):
        b = built(50.85, 1.2133, 1.5)
        self.assertEqual(b.for_fills(), {"trigger": 50.85, "ceiling": 51.15, "stop": 49.03, "target": 56.31})
        self.assertEqual(b.planned_risk, D("1.82"))


class SizingOnTheCeiling(unittest.TestCase):
    """Section 4 and trading-rules Phase 2: N = floor(min($15 / (C - S), $262.50 / C)), sized on the CEILING."""

    def sized(self, c: str, s: str, params=PARAMS) -> O.Sizing:
        return O.paper_shares(hand(c, s), params)

    def test_the_spec_example_a_40_dollar_name_with_a_3_5_percent_stop(self):
        # section 4: "A $40 name with a 3.5% stop gets 6 shares and risks $8.40, or 0.56% of the basis."
        z = self.sized("40.00", "38.60")                   # $15 / 1.40 = 10.7; $262.50 / 40 = 6.56
        self.assertEqual((z.shares, z.sizable), (6, True))
        self.assertEqual((z.risk_at_ceiling, z.cost_at_ceiling), (D("8.40"), D("240.00")))

    def test_risk_sets_the_size_when_the_stop_is_wide(self):
        z = self.sized("20.00", "18.00")                   # $15 / 2.00 = 7.5; $262.50 / 20 = 13.1
        self.assertEqual((z.shares, z.risk_at_ceiling), (7, D("14.00")))      # on T 19.00 it would be 13

    def test_the_cap_binds_on_the_ceiling_not_the_trigger(self):
        # T 43.75, ATR 1.20, k 1.5: C = 44.05; S = 41.95; P = 43.75 + 3 x 1.80 = 49.15
        # 15 / 2.10 = 7.14; 262.50 / 44.05 = 5.96 -> N = 5 (on T: 262.50 / 43.75 = 6, costing 264.30 at C)
        b = built(43.75, 1.20, 1.5)
        self.assertEqual(tuple(b), (D("43.75"), D("44.05"), D("41.95"), D("49.15")))
        z = O.paper_shares(b, PARAMS)
        self.assertEqual((z.shares, z.cost_at_ceiling, z.risk_at_ceiling), (5, D("220.25"), D("10.50")))

    def test_the_risk_limit_binds_on_the_ceiling_not_the_trigger(self):
        # T 20.00, ATR 1.40, k 1.0: C = 20.35; S = 18.60; 15 / 1.75 = 8.57 -> 8 (on T: 15 / 1.40 = 10.7 -> 10,
        # risking 17.50 at C)
        z = O.paper_shares(built(20.00, 1.40, 1.0), PARAMS)
        self.assertEqual((z.shares, z.risk_at_ceiling, z.cost_at_ceiling), (8, D("14.00"), D("162.80")))

    def test_exact_whole_number_quotients_are_not_cut(self):
        for c, s, n, risk, cost in (("26.25", "25.25", 10, "10.00", "262.50"),   # 262.50 / 26.25 = 10 exactly
                                    ("30.00", "27.50", 6, "15.00", "180.00"),    # 15 / 2.50 = 6 exactly
                                    ("52.50", "51.50", 5, "5.00", "262.50")):    # 262.50 / 52.50 = 5 exactly
            z = self.sized(c, s)
            self.assertEqual((z.shares, z.risk_at_ceiling, z.cost_at_ceiling), (n, D(risk), D(cost)), c)

    def test_the_three_share_minimum_and_its_two_boundaries(self):
        # section 4: unsizable when the ceiling is above $87.50 or the risk per share above $5.00
        for c, s, n, sizable in (("87.50", "82.50", 3, True),      # $15.00 risk and $262.50 cost exactly
                                 ("87.51", "82.51", 2, False),     # ceiling a cent too high
                                 ("50.00", "44.99", 2, False),     # risk a cent too wide
                                 ("50.00", "45.00", 3, True)):
            z = self.sized(c, s)
            self.assertEqual((z.shares, z.sizable), (n, sizable), (c, s))

    def test_shares_are_never_rounded_up(self):
        z = self.sized("10.00", "6.24")                    # $15 / 3.76 = 3.989
        self.assertEqual(z.shares, 3)
        self.assertLessEqual(z.risk_at_ceiling, D("15.00"))
        self.assertLessEqual(z.cost_at_ceiling, D("262.50"))

    def test_the_count_is_floor_min_on_the_ceiling_across_a_cent_grid(self):
        # N == min(1500 // risk cents, 26250 // ceiling cents); N x (C - S) <= 15 and N x C <= 262.50; N + 1
        # breaks one of the two; sizable exactly when C <= 87.50 and C - S <= 5.00. T sits between S and C.
        rng = random.Random(20261114)
        pairs = [(c, r) for c in range(2, 10_001, 13) for r in range(1, min(c, 601), 7)]
        pairs += [(c, r) for c in range(8_740, 8_761) for r in range(490, 511)]          # the 87.50 / 5.00 corner
        pairs += [(c, rng.randint(1, min(c - 1, 3_000))) for c in (rng.randint(2, 20_000) for _ in range(10_000))]
        bad = []
        for c, r in pairs:
            s = c - r
            t = s + max(1, r // 2)
            z = O.paper_shares(O.Bracket(cents(t), cents(c), cents(s), cents(t + 3 * (t - s))), PARAMS)
            n, C, R = z.shares, cents(c), cents(r)
            ok = (n == min(1500 // r, 26250 // c) and n * R <= 15 and n * C <= D("262.50")
                  and ((n + 1) * R > 15 or (n + 1) * C > D("262.50"))
                  and (z.risk_at_ceiling, z.cost_at_ceiling) == (n * R, n * C)
                  and z.sizable == (c <= 8_750 and r <= 500))
            if not ok:
                bad.append((c, r, n))
        self.assertEqual(bad, [])

    def test_the_limits_are_cut_to_the_hundredth_never_rounded_up(self):
        z = self.sized("16.41", "15.91")                   # 262.50 / 16.41 = 15.996; 15 / 0.50 = 30
        self.assertEqual((z.cap_limit, z.risk_limit, z.shares), (D("15.99"), D("30.00"), 15))
        z = self.sized("51.15", "49.03")                   # 15 / 2.12 = 7.075; 262.50 / 51.15 = 5.132
        self.assertEqual((z.risk_limit, z.cap_limit, z.risk_per_share), (D("7.07"), D("5.13"), D("2.12")))

    def test_the_budgets_come_from_the_basis(self):
        self.assertEqual(PARAMS.basis * PARAMS.risk_pct, 15.0)
        self.assertEqual(PARAMS.basis * PARAMS.position_cap_pct, 262.5)
        z = self.sized("40.00", "38.60")
        self.assertEqual((z.basis, z.risk_budget, z.cap, z.min_shares), (D("1500.00"), D("15.00"), D("262.50"), 3))
        self.assertEqual(str(z.cap), "262.50")

    def test_only_a_bracket_is_sized(self):
        for bad in ((D("20.00"), D("20.25"), D("18.50"), D("24.50")), None, "BAC"):
            with self.assertRaises(TypeError, msg=repr(bad)):
                O.paper_shares(bad, PARAMS)
        with self.assertRaises(TypeError):
            O.paper_shares(hand("40.00", "38.60"))                         # no params: an error


class ParamsAreRead(unittest.TestCase):
    """Every number comes from params (review finding 1's fix list and the task): change one, the result moves."""

    def test_ceiling_atr(self):
        self.assertEqual(built(20.00, 1.00, 1.5).ceiling, D("20.25"))
        self.assertEqual(built(20.00, 1.00, 1.5, dataclasses.replace(PARAMS, ceiling_atr=0.5)).ceiling, D("20.50"))

    def test_target_r(self):
        self.assertEqual(built(20.00, 1.00, 1.5, dataclasses.replace(PARAMS, target_r=2.0)).target, D("23.00"))

    def test_stop_k(self):
        p = dataclasses.replace(PARAMS, stop_k=(1.0, 1.7))
        self.assertEqual(built(20.00, 1.00, 1.7, p).stop, D("18.30"))
        with self.assertRaises(ValueError):
            built(20.00, 1.00, 1.5, p)

    def test_basis(self):
        z = O.paper_shares(hand("40.00", "38.60"), dataclasses.replace(PARAMS, basis=3000.0))
        self.assertEqual((z.risk_budget, z.cap, z.shares), (D("30.00"), D("525.00"), 13))   # 21.4 and 13.1

    def test_risk_pct(self):
        z = O.paper_shares(hand("20.00", "18.00"), dataclasses.replace(PARAMS, risk_pct=0.02))
        self.assertEqual(z.shares, 13)                                     # $30 / 2.00 = 15; $262.50 / 20 = 13.1

    def test_position_cap_pct(self):
        z = O.paper_shares(hand("40.00", "38.60"), dataclasses.replace(PARAMS, position_cap_pct=0.25))
        self.assertEqual(z.shares, 9)                                      # $15 / 1.40 = 10.7; $375 / 40 = 9.4

    def test_min_shares(self):
        z = O.paper_shares(hand("87.51", "82.51"), dataclasses.replace(PARAMS, min_shares=2))
        self.assertEqual((z.shares, z.sizable), (2, True))
        for bad in (0, -3, 2.5, True):
            with self.assertRaises(ValueError, msg=repr(bad)):
                O.paper_shares(hand("40.00", "38.60"), dataclasses.replace(PARAMS, min_shares=bad))

    def test_trigger_offset(self):
        self.assertEqual(O.trigger_from_high(49.183, dataclasses.replace(PARAMS, trigger_offset=0.02)), D("49.21"))

    def test_spec_numbers_outside_this_module_change_nothing(self):
        # the trade-through, the cost model and the windows are fills.py's and signals.py's numbers
        other = dataclasses.replace(PARAMS, trade_through=0.05, stop_buffer_atr=0.5, cost_mult=2.0, m1_window=5)
        b = built(43.75, 1.20, 1.5)
        self.assertEqual(built(43.75, 1.20, 1.5, other), b)
        self.assertEqual(O.paper_shares(b, other), O.paper_shares(b, PARAMS))
        self.assertEqual(O.trigger_from_high(49.183, other), D("49.20"))


class TicketLines(unittest.TestCase):
    """Section 4: every ticket is printed exactly as entered, N being the $1,500-basis count (8-check item 1)."""

    def test_the_order_lines_are_exactly_the_spec_format(self):
        self.assertEqual(O.ticket_lines("BAC", built(50.85, 1.2133, 1.5), PARAMS),
                         ["BUY +5 BAC STP 50.85 LMT 51.15 GTC  (trigger: STD)",
                          "   1st trgs OCO:  SELL -5 BAC LMT 56.31 GTC  /  SELL -5 BAC STP 49.03 GTC  (trigger: STD)"])

    def test_every_trigger_prints_two_decimals(self):
        # review finding 2: a trigger ending in a zero cent printed as STP 20.0 / STP 50.1
        for t_c in range(5_000, 5_100):
            t, c, s, p, n = oracle(t_c, 12_133, 3)
            self.assertEqual(O.ticket_lines("BAC", built(t_c / 100, 1.2133, 1.5), PARAMS),
                             [f"BUY +{n} BAC STP {money(t)} LMT {money(c)} GTC  (trigger: STD)",
                              f"   1st trgs OCO:  SELL -{n} BAC LMT {money(p)} GTC  /  SELL -{n} BAC STP {money(s)} GTC  (trigger: STD)"])

    def test_a_trigger_of_any_number_type_prints_two_decimals(self):
        for t, text in ((D("50.850"), "50.85"), (D("5E+1"), "50.00"), (50, "50.00"), (50.0, "50.00"),
                        (50.1, "50.10"), (D("50.1"), "50.10")):
            line = O.ticket_lines("BAC", built(t, 1.2133, 1.5), PARAMS)[0]
            self.assertTrue(line.startswith(f"BUY +5 BAC STP {text} LMT "), (t, line))

    def test_the_share_count_is_the_sizing_never_an_argument(self):
        self.assertEqual(list(inspect.signature(O.ticket_lines).parameters), ["symbol", "bracket", "params"])
        b = built(20.00, 1.40, 1.0)                        # N = 8 (the risk limit on the ceiling)
        self.assertEqual(O.ticket_lines("XYZ", b, PARAMS),
                         ["BUY +8 XYZ STP 20.00 LMT 20.35 GTC  (trigger: STD)",
                          "   1st trgs OCO:  SELL -8 XYZ LMT 24.20 GTC  /  SELL -8 XYZ STP 18.60 GTC  (trigger: STD)"])
        with self.assertRaises(TypeError):
            O.ticket_lines("XYZ", 8, b)                   # the old (symbol, shares, bracket) call

    def test_an_unsizable_bracket_gets_no_ticket(self):
        with self.assertRaisesRegex(ValueError, "unsizable"):
            O.ticket_lines("XYZ", hand("87.51", "82.51"), PARAMS)       # 2 shares
        with self.assertRaisesRegex(ValueError, "unsizable"):
            O.ticket_lines("XYZ", built(99.00, 1.00, 1.5), PARAMS)      # C 99.25: 262.50 / 99.25 = 2.6
        self.assertEqual(len(O.ticket_lines("XYZ", hand("87.50", "82.50"), PARAMS)), 2)    # 3 shares: a ticket

    def test_the_symbol_must_be_an_upper_case_ticker(self):
        b = built(50.85, 1.2133, 1.5)
        for bad in ("", "bac", "Bac", " BAC", "BAC ", "BA C", "B\tAC", "BAC\n", "5BAC"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                O.ticket_lines(bad, b, PARAMS)
        for bad in (None, 5, b"BAC"):
            with self.assertRaises(TypeError, msg=repr(bad)):
                O.ticket_lines(bad, b, PARAMS)
        self.assertTrue(O.ticket_lines("BRK.B", b, PARAMS)[0].startswith("BUY +5 BRK.B STP 50.85"))


class SizingLines(unittest.TestCase):
    """Section 4: "It shows the sizing math" (the format ruled 2026-11-12). Limits never print above their value."""

    def test_the_drill_sizing_math(self):
        self.assertEqual(O.sizing_lines(built(50.85, 1.2133, 1.5), PARAMS), [
            "Sizing on the $1,500.00 basis, at the ceiling: C 51.15, S 49.03, C - S 2.12 a share",
            "  risk limit  $15.00 / 2.12 = 7.07 shares",
            "  cap limit   $262.50 / 51.15 = 5.13 shares",
            "  N = floor(min(7.07, 5.13)) = 5 shares: risk at C $10.60 (limit $15.00), cost at C $255.75 (cap $262.50)"])

    def test_a_limit_just_below_a_whole_number_prints_below_it(self):
        # review finding 6: 262.50 / 16.41 = 15.996 printed as 16.00 above N = 15
        lines = O.sizing_lines(hand("16.41", "15.91"), PARAMS)
        self.assertEqual(lines[2], "  cap limit   $262.50 / 16.41 = 15.99 shares")
        self.assertTrue(lines[3].startswith("  N = floor(min(30.00, 15.99)) = 15 shares: "), lines[3])

    def test_an_unsizable_bracket_says_so(self):
        lines = O.sizing_lines(hand("87.51", "82.51"), PARAMS)
        self.assertEqual(lines[3], "  N = floor(min(3.00, 2.99)) = 2 shares: under the 3-share minimum: unsizable, "
                                   "skipped and logged, no ticket")


class TheFillModelRunsTheTicketLevels(unittest.TestCase):
    """'What is paper-traded is what is tested': the Order handed to fills.py carries the ticket's cents
    (review finding 0: the tracker could have carried 49.193 while the ticket carried 49.20).
    In-sample sessions only, with the default seal."""

    def order(self, b: O.Bracket) -> F.Order:
        return F.Order(ticker="TEST", signal_date=SIGNAL_DAY, window=3, atr=1.2133, tier_bps=20.0, **b.for_fills())

    def test_the_fill_model_reads_the_same_cents(self):
        for high in (49.183, 41.315, 12.952, 79.9299, 64.12, 20.0, 5.004):
            b = built(O.trigger_from_high(high, PARAMS), 1.2133 if high > 10 else 0.2133, 1.5)
            o = self.order(b)
            for name in ("trigger", "ceiling", "stop", "target"):
                self.assertEqual(round(getattr(o, name) * 1_000_000), int(getattr(b, name) * 1_000_000), (high, name))

    def test_an_intraday_trigger_fills_at_exactly_the_ticket_trigger(self):
        b = built(O.trigger_from_high(49.183, PARAMS), 1.2133, 1.5)        # T 49.20, not 49.193
        session = dt.date(2023, 1, 10)
        o = F.step(self.order(b), session, F.Bar(session, 49.10, 49.30, 49.05, 49.25), breadth_ok=True, params=PARAMS)
        self.assertEqual((o.state, o.entry_kind, o.entry_raw), (F.OPEN, F.ENTRY_TRIGGER, 49.20))


class OrdersIsPure(unittest.TestCase):
    """Section 2: everything that decides an order is a pure function; every number comes from params."""

    ALLOWED_IMPORTS = {"__future__", "dataclasses", "decimal", "functools", "math", "re", "typing", "params"}

    def setUp(self):
        with open(ORDERS_PY, encoding="utf-8") as fh:
            self.tree = ast.parse(fh.read())

    def test_orders_imports_nothing_that_reaches_a_clock_a_file_the_network_or_the_fill_model(self):
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertLessEqual(imported, self.ALLOWED_IMPORTS)
        self.assertIn("params", imported)

    def test_orders_never_reads_the_clock_or_touches_a_file(self):
        called = {n.func.id for n in ast.walk(self.tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        attributes = {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(called & {"open", "print", "input", "exec", "eval", "__import__"})
        self.assertFalse(attributes & {"now", "today", "utcnow", "time", "environ", "system", "popen"})

    def test_no_spec_number_is_typed_in_the_module(self):
        # 0 and 1 in comparisons and 60 digits of decimal precision; the cent grid and the millionth. Every
        # spec number ($0.01 offset, 0.25, 3, $1,500, 1%, 17.5%, 3 shares, k) must come from params.
        numbers = {n.value for n in ast.walk(self.tree)
                   if isinstance(n, ast.Constant) and type(n.value) in (int, float, complex)}
        self.assertLessEqual(numbers, {0, 1, 60})
        decimals = {n.args[0].value for n in ast.walk(self.tree)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "Decimal"
                    and n.args and isinstance(n.args[0], ast.Constant)}
        self.assertEqual(decimals, {"0.01", "0.000001"})


if __name__ == "__main__":
    unittest.main()
