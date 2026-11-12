"""Spec-derived synthetic scenarios S01-S29 for loops/phase2/sample_bars.py and compare_bars.py.

Adopted from the 2026-11-12 verification of the flip tools (its checks/test_verify_flips.py). Independent of the
builder's tests: own history builders, own oracles written from spec 3.1-3.4 text (tests/phase2_flip_helpers.py).
Synthetic data only; sessions are post-go-live (2026-11-23 on) or 2024. fills.step is wrapped for the whole
module: it refuses any session inside 2025-01-02..2026-10-30 and any seal argument, so no scenario can evaluate a
fill there. No network: the market data is scripted, and nothing here opens a socket.

compare_bars records go-live in its reviewed constant GO_LIVE_ACTUAL, unset until go-live (review D2), and the
owner's ruling of 2026-11-12 (spec 3.7: sealed bars may be read as look-back for any session after 2026-10-30) in
PRE_GO_LIVE_LOOKBACK_RULED, True. The scenarios' nights stand for post-go-live nights, so setUpModule records
go-live at the target date, 2026-11-23, as the go-live edit will; S13 checks the unset default, go-live deciding
alone (the ruling set False) and the ruling itself.

Run:  python -m unittest tests.test_phase2_flips_scenarios
"""
from __future__ import annotations

import collections
import contextlib
import datetime as dt
import io
import json
import random
import tempfile
import unittest
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from unittest import mock

try:
    from . import phase2_flip_helpers as H
except ImportError:                          # run as a script from tests/
    import phase2_flip_helpers as H

CB, D, F, PARAMS, SB, at, bar, cdl, flat, q = H.CB, H.D, H.F, H.PARAMS, H.SB, H.at, H.bar, H.cdl, H.flat, H.q

_REAL_STEP = F.step
STEPPED: list = []


def _guarded_step(order, session, b, **kw):
    if "seal" in kw:
        raise AssertionError("a seal argument was passed to fills.step")
    if H.SEAL[0] <= session <= H.SEAL[1] or H.SEAL[0] <= order.signal_date <= H.SEAL[1]:
        raise AssertionError(f"fills.step called on a sealed-window date: session {session}, signal {order.signal_date}")
    STEPPED.append(session)
    return _REAL_STEP(order, session, b, **kw)


GO_LIVE_FOR_TESTS = D(2026, 11, 23)          # params.go_live_target; recorded here only, never in the source
_PATCHES = (mock.patch.object(F, "step", _guarded_step), mock.patch.object(CB, "GO_LIVE_ACTUAL", GO_LIVE_FOR_TESTS))


def setUpModule():
    for p in _PATCHES:
        p.start()


def tearDownModule():
    for p in reversed(_PATCHES):
        p.stop()


class Tmp(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.root = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()


def prior60_of(hist):
    return {c["d"] for c in hist[-60:]}


T0 = D(2026, 11, 30)                     # a Monday after go-live
EV0, FI0 = at(2026, 11, 30, 17, 35), at(2026, 12, 1, 1, 30)


# =========================================================================================================
# S01-S06: the threshold tests of spec 3.1-3.2, one rule at a time, on compare_bars.evaluate
# =========================================================================================================

class ThresholdRules(unittest.TestCase):
    def test_S01_m2_gap_is_max_of_3pct_and_atr_at_t_minus_1(self):
        h40 = flat(T0, c=40.0, r=0.5)                                   # ATR(t-1) 1.00; 3% of 40 = 1.20 binds
        p = prior60_of(h40)
        self.assertTrue(CB.evaluate(h40, bar(41.20, 41.9, 41.1, 41.8, 5_000_000), p)["m2"]["gap"])
        self.assertFalse(CB.evaluate(h40, bar(41.19, 41.9, 41.1, 41.8, 5_000_000), p)["m2"]["gap"])
        h20 = flat(T0, c=20.0, r=0.5)                                   # 3% of 20 = 0.60; ATR(t-1) 1.00 binds
        p = prior60_of(h20)
        big_range = bar(21.05, 24.0, 20.5, 23.9, 5_000_000)             # ATR(t) = 1.25 > ATR(t-1): must not be used
        e = CB.evaluate(h20, big_range, p)
        self.assertAlmostEqual(e["atr_prev"], 1.0)
        self.assertGreater(e["atr_t"], 1.2)
        self.assertTrue(e["m2"]["gap"])
        self.assertFalse(CB.evaluate(h20, bar(20.99, 21.9, 20.6, 21.8, 5_000_000), p)["m2"]["gap"])

    def test_S02_m2_volume_is_3x_the_30_sessions_ending_t_minus_1(self):
        h = flat(T0, c=20.0, r=0.5)
        h[-31] = dict(h[-31], v=31_000_000)                             # outside the 30-session window: no effect
        p = prior60_of(h)
        b = bar(21.2, 21.9, 21.0, 21.8, 3_000_000)
        self.assertTrue(CB.evaluate(h, b, p)["m2"]["volume"])
        self.assertFalse(CB.evaluate(h, dict(b, v=2_999_999), p)["m2"]["volume"])
        self.assertEqual(CB.evaluate(h, b, p)["adv30"], 1_000_000)

    def test_S03_m2_held_low_strict_close_at_midpoint_inclusive(self):
        h = flat(T0, c=20.0, r=0.5)
        p = prior60_of(h)
        self.assertFalse(CB.evaluate(h, bar(21.2, 22.0, 20.00, 21.9, 5_000_000), p)["m2"]["held"])    # low = prior close
        self.assertTrue(CB.evaluate(h, bar(21.2, 22.0, 20.01, 21.9, 5_000_000), p)["m2"]["held"])
        self.assertTrue(CB.evaluate(h, bar(21.2, 22.0, 21.0, 21.5, 5_000_000), p)["m2"]["held"])      # close = midpoint
        self.assertFalse(CB.evaluate(h, bar(21.2, 22.0, 21.0, 21.49, 5_000_000), p)["m2"]["held"])

    def test_S04_eligibility_band_volume_history_and_presence(self):
        h = flat(T0, c=50.0, r=0.5, v=500_000)
        p = prior60_of(h)
        ok = lambda hist, c, pr=p: CB.evaluate(hist, bar(c, c + 0.2, c - 0.2, c, 600_000), pr)["eligible"]  # noqa: E731
        self.assertTrue(ok(h, 100.00))
        self.assertFalse(ok(h, 100.01))
        self.assertTrue(ok(h, 5.00))
        self.assertFalse(ok(h, 4.99))
        low_v = [dict(c, v=499_999) if i == len(h) - 1 else c for i, c in enumerate(h)]   # ADV30 499,999.97
        self.assertFalse(ok(low_v, 50.0))
        self.assertTrue(ok(h[-60:], 50.0))                              # exactly 60 sessions of history
        self.assertFalse(ok(h[-59:], 50.0, prior60_of(h)))
        gaps2 = [c for i, c in enumerate(h) if i not in (len(h) - 3, len(h) - 10)]        # 58 of the prior 60
        gaps3 = [c for i, c in enumerate(h) if i not in (len(h) - 3, len(h) - 10, len(h) - 20)]
        self.assertTrue(ok(gaps2, 50.0, p))
        self.assertFalse(ok(gaps3, 50.0, p))

    def test_S05_close_above_the_50_session_average_is_strict_and_includes_t(self):
        h = flat(T0, c=20.0, r=0.5)
        p = prior60_of(h)
        self.assertFalse(CB.evaluate(h, bar(20.0, 20.4, 19.6, 20.0, 1_000_000), p)["above"])         # equal: not above
        self.assertTrue(CB.evaluate(h, bar(20.0, 20.4, 19.6, 20.01, 1_000_000), p)["above"])
        h2 = [dict(c, c=10.0) if i == len(h) - 50 else c for i, c in enumerate(h)]       # t-50: outside 50 closes
        self.assertFalse(CB.evaluate(h2, bar(20.0, 20.4, 19.6, 20.0, 1_000_000), p)["above"])

    def test_S06_evaluate_agrees_with_the_spec_oracle_on_random_bars(self):
        rnd = random.Random(1112)
        disagreements, checked = [], 0
        for case in range(600):
            n = rnd.choice([130, 130, 130, 80, 61])
            px = rnd.uniform(6, 95)
            hist = []
            for d in H.sessions_before(T0, n):
                drift = rnd.gauss(0, 0.015) * px
                o = round(px, 2)
                px = max(5.5, px + drift)
                c = round(px, 2)
                hi = round(max(o, c) + abs(rnd.gauss(0, 0.01)) * px, rnd.choice([2, 2, 3, 6]))
                lo = round(min(o, c) - abs(rnd.gauss(0, 0.01)) * px, 2)
                hist.append(cdl(d, "final", o, hi, lo, c, int(rnd.uniform(2e5, 3e6))))
            pc = hist[-1]["c"]
            g = rnd.choice([0.0, 0.02, 0.03, 0.05, -0.02]) * pc + rnd.choice([0, 0.01, -0.01])
            o = round(pc + g, 2)
            lo = round(o - abs(rnd.gauss(0, 0.01)) * pc, 2)
            hi = round(o + abs(rnd.gauss(0, 0.02)) * pc, 2)
            c = round(rnd.uniform(lo, hi), 2)
            v = int(rnd.choice([1, 2.9, 3.0, 3.1, 5]) * (sum(x["v"] for x in hist[-30:]) / 30))
            b = bar(o, hi, lo, c, v)
            p = prior60_of(hist)
            got, want = CB.evaluate(hist, b, p), H.spec_eval(hist, b, p)
            checked += 1
            ties = want.get("ties", {})
            for key in ("eligible", "above"):
                if key in want and got.get(key) != want[key] and not ties.get(key):
                    disagreements.append((case, key, got.get(key), want[key]))
            self.assertEqual(got["T"], want["T"])
            if "m2" in want and "m2" in got:
                for k2, v2 in want["m2"].items():
                    if got["m2"][k2] != v2 and not ties.get("m2." + k2):
                        disagreements.append((case, "m2." + k2, got["m2"][k2], v2))
            if "m1" in want and "m1" in got:
                for k1, v1 in want["m1"].items():
                    if got["m1"][k1] != v1 and not ties.get("m1." + k1):
                        disagreements.append((case, "m1." + k1, got["m1"][k1], v1))
            self.counts = getattr(self, "counts", collections.Counter())
            for side in ("m1", "m2"):
                if side in want:
                    self.counts[side + "_signal"] += all(want[side].values())
            self.counts["ties"] += any(ties.values())
        self.assertEqual(disagreements, [])
        self.assertEqual(checked, 600)
        print(f"\n  S06 oracle coverage: {dict(self.counts)}")

    def test_S07_exact_ties_follow_the_spec_text(self):
        """Spec 3.2 states exact thresholds. fills.py compares prices in integer millionths so ties are exact;
        compare_bars compares them at the millionth with Decimal (review D5). Two cent-exact ties that binary
        floats got wrong:"""
        h = flat(T0, c=30.0, r=0.25)                                    # ATR(t-1) 0.50, 3% of 30.00 = 0.90 binds
        p = prior60_of(h)
        gap_tie = CB.evaluate(h, bar(30.90, 31.5, 30.8, 31.4, 5_000_000), p)   # gap 0.90 >= 0.90: passes
        h2 = flat(T0, c=20.0, r=0.5)
        mid_tie = CB.evaluate(h2, bar(20.4, 20.60, 20.30, 20.45, 5_000_000), prior60_of(h2))  # close = midpoint
        self.assertEqual((gap_tie["m2"]["gap"], mid_tie["m2"]["held"]), (True, True))


# =========================================================================================================
# S08-S12: whole nights through analyze_night / build_report
# =========================================================================================================

def spy(n: H.NightW, t, ev_open, fin_open, pc=500.0, ev_at=EV0, fi_at=FI0):
    hs = flat(t, c=pc, r=2.5, v=50_000_000)
    hi = max(ev_open, fin_open, pc) + 4
    n.add("SPY", hs, bar(ev_open, hi, pc - 3, pc + 1, 40_000_000), pc + 1, bar(fin_open, hi, pc - 3, pc + 1, 41_000_000),
          ev_at, fi_at)


class Nights(Tmp):
    def test_S08_breadth_exactly_half_is_open_and_a_one_name_drop_closes_it(self):
        names = [f"N{i}" for i in range(10)]
        n = H.NightW(self.root, T0, names)
        spy(n, T0, 500.5, 500.5)
        for i, s in enumerate(names):
            hist = flat(T0)
            if i < 5:                        # above the average on both sides, except N0 on the final bar
                ev, qc = bar(20.0, 20.4, 19.8, 20.2, 1_000_000), 20.2
                fin = bar(20.0, 20.4, 19.8, 20.0 if i == 0 else 20.2, 1_000_000)
            else:                            # exactly at the average: not above
                ev, qc, fin = bar(20.0, 20.4, 19.8, 20.0, 1_000_000), 20.0, bar(20.0, 20.4, 19.8, 20.0, 1_000_000)
            n.add(s, hist, ev, qc, fin, EV0 + dt.timedelta(seconds=i), FI0 + dt.timedelta(seconds=i))
        night = CB.analyze_night(n.day)
        b = night["signals"]["breadth"]
        self.assertEqual((b["evening"]["above"], b["evening"]["eligible"], b["evening"]["gate_open"]), (5, 10, True))
        self.assertEqual((b["final"]["above"], b["final"]["eligible"], b["final"]["gate_open"]), (4, 10, False))
        self.assertTrue(b["gate_flip"])
        self.assertEqual(night["tally"]["sma_flip"], 1)
        self.assertEqual(night["tally"]["breadth_gate_flip"], 1)

    def test_S09_spy_gap_test_at_exactly_one_percent(self):
        n = H.NightW(self.root, T0, ["A"])
        spy(n, T0, 505.00, 504.95)                                      # 1.00% fails "< +1.0%"; 0.99% passes
        n.add("A", flat(T0), bar(20.0, 20.4, 19.8, 20.2, 1_000_000), 20.2, bar(20.0, 20.4, 19.8, 20.2, 1_000_000), EV0, FI0)
        g = CB.analyze_night(n.day)["signals"]["spy_gap"]
        self.assertEqual((g["ok_evening"], g["ok_final"], g["flip"]), (False, True, True))

    def test_S10_m2_flips_and_order_levels_follow_spec_3_4(self):
        names = ["GAPX", "VOLX", "HIGHX", "BIG", "UP1", "UP2", "UP3"]
        n = H.NightW(self.root, T0, names)
        spy(n, T0, 500.5, 500.5)
        hist = flat(T0)                                                 # close 20, ATR(t-1) 1.00, ADV30 1,000,000
        cases = {
            # evening passes the gap test (21.00 - 20.00 = 1.00 >= 1.00); the final open is 20.99: disappears
            "GAPX": (bar(21.00, 21.9, 20.8, 21.7, 5_000_000), 21.7, bar(20.99, 21.9, 20.8, 21.7, 5_000_000)),
            # evening volume 2,999,999 < 3,000,000; the final volume 3,000,000 passes: appears
            "VOLX": (bar(21.20, 21.9, 21.0, 21.7, 2_999_999), 21.7, bar(21.20, 21.9, 21.0, 21.7, 3_000_000)),
            # both pass; the final high is a cent higher: T, and with it C/S/P, change
            "HIGHX": (bar(21.20, 21.90, 21.0, 21.7, 5_000_000), 21.7, bar(21.20, 21.91, 21.0, 21.7, 5_000_000)),
        }
        for i, s in enumerate(["GAPX", "VOLX", "HIGHX"]):
            ev, qc, fin = cases[s]
            n.add(s, hist, ev, qc, fin, EV0 + dt.timedelta(seconds=i), FI0 + dt.timedelta(seconds=i))
        h90 = flat(T0, c=90.0, r=0.5)                                   # an M2 signal whose ceiling is above $87.50
        b90 = bar(92.80, 93.5, 92.6, 93.4, 5_000_000)
        n.add("BIG", h90, b90, 93.4, b90, EV0 + dt.timedelta(seconds=9), FI0 + dt.timedelta(seconds=9))
        for i, s in enumerate(["UP1", "UP2", "UP3"]):                    # keep breadth open on both sides
            n.add(s, flat(T0), bar(20.0, 20.4, 19.8, 20.3, 1_000_000), 20.3, bar(20.0, 20.4, 19.8, 20.3, 1_000_000),
                  EV0 + dt.timedelta(seconds=20 + i), FI0 + dt.timedelta(seconds=20 + i))
        night = CB.analyze_night(n.day)
        t = night["tally"]
        self.assertTrue(night["signals"]["breadth"]["evening"]["gate_open"])
        self.assertTrue(night["signals"]["breadth"]["final"]["gate_open"])
        self.assertEqual((t["m2_eve"], t["m2_fin"], t["m2_flip"], t["m2_both"]), (3, 3, 2, 2))
        self.assertEqual((t["m2_t_gap_flip"], t["m2_t_volume_flip"]), (1, 1))
        for k in PARAMS.stop_k:
            self.assertEqual(t[f"lv_m2_{k}_disappeared"], 1, k)
            self.assertEqual(t[f"lv_m2_{k}_appeared"], 1, k)
            self.assertEqual(t[f"lv_m2_{k}_changed"], 1, k)            # HIGHX
            self.assertEqual(t[f"lv_m2_{k}_confirmed"], 1, k)          # BIG: identical bars
            self.assertEqual(t.get(f"tk_m2_{k}_confirmed", 0), 0, k)   # BIG is unsizable: never a ticket
        # the levels, recomputed from the spec text (ATR at the signal close, S0 = low(t) - 0.2 ATR)
        for s, side in (("HIGHX", 0), ("HIGHX", 2)):
            b = cases[s][side]
            ev_bar = dict(b, c=cases[s][1]) if side == 0 else b
            e = H.spec_eval(hist, ev_bar, prior60_of(hist))
            for k in PARAMS.stop_k:
                want = H.spec_levels(e["T"], e["atr_t"], k, ev_bar["l"] - 0.2 * e["atr_t"])
                got = CB.levels(e["T"], e["atr_t"], k, ev_bar["l"] - PARAMS.stop_buffer_atr * e["atr_t"])
                self.assertEqual({f: got[f] for f in ("T", "C", "S", "P", "N", "sizable")}, want, (s, side, k))
        eb = H.spec_eval(h90, b90, prior60_of(h90))
        big = H.spec_levels(eb["T"], eb["atr_t"], 1.5, b90["l"] - 0.2 * eb["atr_t"])
        self.assertGreater(big["C"], Decimal("87.50"))
        self.assertFalse(big["sizable"])

    def test_S11_unconfirmed_and_excluded_classes_are_never_flips(self):
        names = ["NOTFIN", "TRUNCF", "ALRDY", "NOQ", "SPLIT", "SHIFT", "OK1", "OK2"]
        n = H.NightW(self.root, T0, names)
        spy(n, T0, 500.5, 500.5)
        hist = flat(T0)
        sig = bar(21.20, 21.9, 21.0, 21.7, 5_000_000)                     # an M2 signal on every evening bar
        n.add("NOTFIN", hist, sig, 21.7, sig, EV0, FI0, fin_kind="provisional")
        n.add("TRUNCF", hist, sig, 21.7, None, EV0, FI0,
              final_rows=[(FI0, [cdl(T0, "provisional", **sig)], dict(attempt=1))])
        n.add("ALRDY", hist, sig, 21.7, sig, EV0, FI0, ev_kind="final")
        n.add("NOQ", hist, sig, None, sig, EV0, FI0)
        split_prior = [dict(c, o=c["o"] * 2, h=c["h"] * 2, l=c["l"] * 2, c=c["c"] * 2) for c in hist[-4:]]
        n.add("SPLIT", hist, sig, 21.7, sig, EV0, FI0, eve_prior=split_prior)
        shift_prior = [dict(c, o=c["o"] + 1.6, h=c["h"] + 1.6, l=c["l"] + 1.6, c=c["c"] + 1.6) for c in hist[-4:]]
        n.add("SHIFT", hist, sig, 21.7, sig, EV0, FI0, eve_prior=shift_prior)
        for s in ("OK1", "OK2"):
            n.add(s, hist, bar(20.0, 20.4, 19.8, 20.3, 1_000_000), 20.3, bar(20.0, 20.4, 19.8, 20.3, 1_000_000), EV0, FI0)
        night = CB.analyze_night(n.day)
        t, cnt = night["tally"], night["names_count"]
        self.assertEqual(t["pairs"], 5)                                 # NOQ, SPLIT, SHIFT, OK1, OK2
        self.assertEqual(t["sig_pairs"], 2)                             # only OK1, OK2 reach the signal level
        self.assertEqual(t.get("m2_eve", 0) + t.get("m2_fin", 0) + t.get("m2_flip", 0), 0)
        self.assertFalse([k for k in t if k.startswith(("lv_", "tk_"))])
        self.assertEqual((cnt["not_final_yet"], cnt["final_truncated"], cnt["already_final"], cnt["no_quote_close"],
                          cnt["basis_change"]), (1, 1, 1, 1, 2))
        self.assertEqual(sorted(night["names"]["basis_change"]), ["SHIFT (shift $-1.60)", "SPLIT (split-like x0.5000)"])
        self.assertEqual(night["signals"]["breadth"]["missing_final"], 2)   # NOTFIN, TRUNCF bound the final B(t)

    def test_S12_final_record_most_history_then_latest_and_errors_never_win(self):
        hist = flat(T0)
        fin_a = cdl(T0, "final", 20.0, 20.4, 19.8, 20.2, 1_000_000)
        fin_b = dict(fin_a, v=1_000_777)
        rows = [dict(symbol="X", pulled=SB.iso(at(2026, 12, 1, 1, 30)), candles=hist + [fin_a]),
                dict(symbol="X", pulled=SB.iso(at(2026, 12, 1, 4, 30)), candles=hist + [fin_b]),      # same history: latest
                dict(symbol="X", pulled=SB.iso(at(2026, 12, 1, 6, 30)), candles=hist[-50:] + [dict(fin_a, v=9)]),
                dict(symbol="X", pulled=SB.iso(at(2026, 12, 1, 7, 30)), error="HTTP 500")]
        for r in rows:
            CB._fix_kinds(r)
        got = CB.pick_final(rows, T0.isoformat())
        self.assertEqual((got["cls"], got["cand"]["v"], len(got["hist"]), got["revised"], got["from_earlier"]),
                         (SB.FINAL, 1_000_777, 130, True, True))


# =========================================================================================================
# S13: the look-back guard and the seal
# =========================================================================================================

def quiet_night(root, session, ev_at, fi_at, names=("A", "B")):
    n = H.NightW(root, session, list(names))
    spy(n, session, 500.5, 500.5, ev_at=ev_at, fi_at=fi_at)
    for i, s in enumerate(names):
        n.add(s, flat(session), bar(20.3 if i == 0 else 20.0, 20.4, 19.8, 20.2, 1_000_000), 20.2,
              bar(20.0, 20.4, 19.8, 20.2, 1_000_100), ev_at, fi_at)
    return n


class Guard(Tmp):
    def test_S13_pre_go_live_runs_by_the_ruling_go_live_decides_without_it_sealed_never(self):
        quiet_night(self.root, D(2026, 11, 20), at(2026, 11, 20, 17, 30), at(2026, 11, 21, 1, 30))
        quiet_night(self.root, D(2026, 11, 23), at(2026, 11, 23, 17, 30), at(2026, 11, 24, 1, 30))
        quiet_night(self.root, D(2026, 10, 29), at(2026, 10, 29, 17, 30), at(2026, 10, 30, 1, 30))
        STEPPED.clear()
        with mock.patch.object(CB, "PRE_GO_LIVE_LOOKBACK_RULED", False):      # go-live alone decides
            # review D2: with go-live not recorded (the source default), even the target day is pre-go-live
            with mock.patch.object(CB, "GO_LIVE_ACTUAL", None), \
                    mock.patch.object(H.technicals, "compute_levels", wraps=H.technicals.compute_levels) as cl:
                unrecorded = CB.analyze_night(self.root / "2026-11-23")
                self.assertEqual(cl.call_count, 0)
            self.assertFalse(unrecorded["signals"]["run"])
            self.assertIn("go-live not recorded", unrecorded["signals"]["reason"])
            self.assertEqual(STEPPED, [])
            # go-live recorded at 2026-11-23 (this module's setUpModule): the original scenario
            with mock.patch.object(H.technicals, "compute_levels", wraps=H.technicals.compute_levels) as cl:
                pre = CB.analyze_night(self.root / "2026-11-20")
                self.assertEqual(cl.call_count, 0)
            self.assertFalse(pre["signals"]["run"])
            self.assertIn("pre-go-live", pre["signals"]["reason"])
            live = CB.analyze_night(self.root / "2026-11-23")
            self.assertTrue(live["signals"]["run"], live["signals"].get("reason"))
            self.assertTrue(STEPPED and all(s == D(2026, 11, 23) for s in STEPPED))
            later = CB.analyze_night(self.root / "2026-11-23", go_live=D(2026, 11, 24))
            self.assertFalse(later["signals"]["run"])
            rep = CB.build_report(self.root)
            self.assertEqual([n["session"] for n in rep["nights"] if (n["signals"] or {}).get("run")], ["2026-11-23"])
        # the owner's ruling of 2026-11-12 (spec 3.7), the source's PRE_GO_LIVE_LOOKBACK_RULED: the pre-go-live night
        # reads its sealed look-back too, go-live recorded or not; a sealed session never runs
        for go_live in (None, D(2026, 11, 23)):
            with mock.patch.object(CB, "GO_LIVE_ACTUAL", go_live):
                ruled = CB.analyze_night(self.root / "2026-11-20")
            self.assertTrue(ruled["signals"]["run"], (go_live, ruled["signals"].get("reason")))
        sealed = CB.analyze_night(self.root / "2026-10-29")
        self.assertFalse(sealed["signals"]["run"])
        self.assertIn("sealed", sealed["signals"]["reason"])
        rep = CB.build_report(self.root)                                  # the pooled report never steps a sealed day
        self.assertTrue(all(not (H.SEAL[0] <= s <= H.SEAL[1]) for s in STEPPED))
        self.assertEqual([n["session"] for n in rep["nights"] if (n["signals"] or {}).get("run")],
                         ["2026-11-20", "2026-11-23"])
        self.assertEqual(rep["meta"]["ignored"], [dict(folder="2026-10-29", reason="not after 2026-10-30")])   # safety S9


# =========================================================================================================
# S14: the day-t fill path against an independent spec 3.4 oracle
# =========================================================================================================

def oracle_fill_counts(fin_open, atr, eve, fin):
    a = q(atr)
    out = collections.Counter()
    ok_bar = lambda b: 0 < b["l"] and b["l"] <= b["o"] <= b["h"] and b["l"] <= b["c"] <= b["h"]  # noqa: E731
    if not (ok_bar(eve) and ok_bar(fin)):
        return None
    tup = lambda b: (q(b["o"]), q(b["h"]), q(b["l"]), q(b["c"]))  # noqa: E731
    be, bf = tup(eve), tup(fin)
    same = be == bf
    for i in range(21):
        off = Fraction(round((-0.5 + 0.05 * i) * 100), 100)
        x = q(fin_open) + off * a
        for k in PARAMS.stop_k:
            T = H.ceil_cent(x)
            lv = H.spec_levels(T, atr, k, None)
            if lv is None:
                continue
            out["pending: orders"] += 1
            if same:
                continue
            args = [H.frac(lv[f]) for f in ("T", "C", "S", "P")]
            if H.spec_entry_session(*args, be) != H.spec_entry_session(*args, bf):
                out["pending: changed"] += 1
        kk = Fraction(3, 2)
        for fam, s in (("open, stop near the open", H.floor_cent(x)),
                       ("open, target near the open", H.floor_cent(H.frac(H.ceil_cent(x)) - 4 * kk * a))):
            sf = H.frac(s)
            t = H.ceil_cent(sf + kk * a)
            c = H.floor_cent(H.frac(t) + Fraction(1, 4) * a)
            p = H.ceil_cent(H.frac(t) + 3 * (H.frac(t) - sf))
            if not (0 < s < t <= c < p):
                continue
            out[f"{fam}: orders"] += 1
            if same:
                continue
            if H.spec_held_session(sf, H.frac(p), be) != H.spec_held_session(sf, H.frac(p), bf):
                out[f"{fam}: changed"] += 1
    return out


class FillPath(unittest.TestCase):
    def test_S14_replay_matches_the_spec_oracle_on_random_bar_pairs(self):
        rnd = random.Random(20261112)
        hist = flat(T0)
        mismatches, compared = [], 0
        for case in range(400):
            atr = round(rnd.uniform(0.2, 2.0), 4)
            o = round(rnd.uniform(10, 60), 2)
            hi = round(o + rnd.uniform(0, 2 * atr), rnd.choice([2, 3]))
            lo = round(o - rnd.uniform(0, 2 * atr), 2)
            c = round(rnd.uniform(lo, hi), 2)
            fin = bar(o, hi, lo, c, 1)
            eve = dict(fin)
            for f in rnd.sample(["o", "h", "l", "c"], rnd.choice([1, 1, 2])):
                eve[f] = round(fin[f] + rnd.choice([-1, 1]) * rnd.choice([0.01, 0.05, 0.2, 0.5]) * atr, 2)
            want = oracle_fill_counts(fin["o"], atr, eve, fin)
            try:
                got = CB.replay_fill_paths("Z", T0, eve, fin, atr, 20.0, hist)["counts"]
            except ValueError:
                got = None
            if want is None:
                self.assertTrue(got is None or got.get("impossible_bar") == 1, (case, got))
                continue
            compared += 1
            g = {k: v for k, v in got.items() if k.endswith((": orders", ": changed"))}
            w = {k: v for k, v in want.items() if v}
            if g != w:
                mismatches.append((case, eve, fin, atr, g, w))
        self.assertGreater(compared, 300)
        self.assertEqual(mismatches[:3], [])


# =========================================================================================================
# S15: statistics
# =========================================================================================================

def exact_upper(x, n, conf=0.95):
    """Clopper-Pearson one-sided upper bound by bisection on an exact binomial CDF (Fractions)."""
    from math import comb
    alpha = Fraction(1) - Fraction(conf).limit_denominator(1000)
    lo, hi = Fraction(x, n), Fraction(1)
    for _ in range(60):
        mid = (lo + hi) / 2
        cdf = sum(comb(n, i) * mid ** i * (1 - mid) ** (n - i) for i in range(x + 1))
        lo, hi = (mid, hi) if cdf > alpha else (lo, mid)
    return float(hi)


class Stats(unittest.TestCase):
    def test_S15_clopper_pearson_matches_an_exact_computation(self):
        for x, n in ((0, 1), (0, 7), (1, 7), (2, 20), (3, 31), (5, 200), (1, 1907), (11, 1907), (0, 1907), (9, 10)):
            self.assertAlmostEqual(CB.upper_bound(x, n), exact_upper(x, n), places=6, msg=(x, n))


# =========================================================================================================
# S16-S18: pooling and night states
# =========================================================================================================

class Pooling(Tmp):
    def test_S16_late_excluded_missed_night_and_not_sampled(self):
        quiet_night(self.root, D(2026, 11, 30), at(2026, 11, 30, 17, 30), at(2026, 12, 1, 1, 30))
        quiet_night(self.root, D(2026, 12, 1), at(2026, 12, 1, 21, 5), at(2026, 12, 2, 1, 30))        # LATE
        SB.RunStatus(self.root, D(2026, 12, 2), "final", at(2026, 12, 3, 1, 30)).finish(
            at(2026, 12, 3, 1, 30), "MISSED-NIGHT", reason="no evening sample")
        quiet_night(self.root, D(2026, 12, 4), at(2026, 12, 4, 17, 30), at(2026, 12, 5, 1, 30))
        rep = CB.build_report(self.root)
        states = {n["session"]: n["state"] for n in rep["nights"]}
        self.assertEqual(states, {"2026-11-30": "OK", "2026-12-01": "LATE", "2026-12-02": "MISSED-NIGHT",
                                  "2026-12-04": "OK"})
        self.assertEqual(rep["not_sampled"], ["2026-12-03"])
        self.assertEqual(rep["contributing"], ["2026-11-30", "2026-12-04"])
        self.assertEqual(rep["pooled"]["tally"]["diff_o"], 2)
        self.assertEqual(CB.build_report(self.root, include_late=True)["pooled"]["tally"]["diff_o"], 3)


# =========================================================================================================
# S17-S20: the sampler (scripted market data; no network)
# =========================================================================================================

class Clock:
    def __init__(self, start):
        self.t, self.slept = start, 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept += s
        self.t += dt.timedelta(seconds=s)


class Sampler(Tmp):
    def run_night_mode(self, start):
        """main(['night']) with the clock and both pulls stubbed; records when each pull runs. The market data, the
        token reader (a token with 150 hours left), the notifier and the power assertion are handed in as
        loops/phase2_sample.py does (review D7, safety S5)."""
        clock, calls = Clock(start), []

        def fake_evening(md, **kw):
            calls.append(("evening", clock.now(), SB.last_completed_session(clock.now())))
            return 0

        def fake_final(md, *, session, **kw):
            calls.append(("final", clock.now(), session))
            return 0
        stub = lambda: SB.MarketData(lambda *a: [], lambda *a: [], lambda *a: {})  # noqa: E731
        with mock.patch.object(SB, "now_et", clock.now), mock.patch.object(SB.time, "sleep", clock.sleep), \
                mock.patch.object(SB, "log_line", lambda m: None), \
                mock.patch.object(SB, "run_evening", fake_evening), mock.patch.object(SB, "run_final", fake_final):
            SB.main(["night", "--root", str(self.root)], market_data=stub,
                    token_hours=lambda: (150.0, "2026-12-07T12:00:00-05:00"), notify=None, awake=None)
        return calls

    def test_S17_night_mode_on_time(self):
        calls = self.run_night_mode(at(2026, 11, 30, 17, 25))
        self.assertEqual(calls[0][:1] + calls[0][2:], ("evening", D(2026, 11, 30)))
        self.assertEqual(calls[0][1], at(2026, 11, 30, 17, 30))
        self.assertEqual([c[2] for c in calls[1:]], [D(2026, 11, 30)] * 6)     # 00:30 .. 07:30 (review SVC-04)
        self.assertEqual([c[1] for c in calls[1:]], [at(2026, 12, 1, h, m) for h, m in
                                                     ((0, 30), (1, 0), (1, 30), (4, 30), (6, 30), (7, 30))])

    def test_S18_night_mode_started_after_midnight_samples_the_previous_session_now(self):
        """launchd runs a job missed during sleep when the Mac wakes. Woken at 00:40, the night's session is the
        previous day's, and a LATE evening sample is still allowed until 04:00 (sample_bars docstring)."""
        calls = self.run_night_mode(at(2026, 12, 1, 0, 40))
        first = calls[0]
        self.assertEqual(first[0], "evening")
        self.assertEqual(first[2], D(2026, 11, 30), f"evening sample keyed to {first[2]} at {first[1]}")
        self.assertLess(first[1], at(2026, 12, 1, 4, 0), f"evening sample only at {first[1]}")

    def test_S19_evening_timing_weekend_and_holiday(self):
        self.assertEqual(SB.evening_timing(at(2026, 12, 5, 0, 30), D(2026, 12, 4))[0], "LATE")      # Sat for Fri
        self.assertEqual(SB.evening_timing(at(2026, 12, 7, 0, 30), D(2026, 12, 4))[0], "TOO_LATE")  # Mon for Fri
        self.assertEqual(SB.last_completed_session(at(2026, 11, 27, 13, 0)), D(2026, 11, 27))       # half day
        self.assertEqual(SB.evening_timing(at(2026, 11, 26, 18, 0), D(2026, 11, 25))[0], "TOO_LATE")  # Thanksgiving

    def test_S20_final_without_this_sessions_evening_is_missed_night_once_and_pulls_nothing(self):
        prev = self.root / "2026-11-30"                      # the PREVIOUS session has a full evening sample
        quiet_night(self.root, D(2026, 11, 30), at(2026, 11, 30, 17, 30), at(2026, 12, 1, 1, 30))
        pulled = []
        md = SB.MarketData(lambda *a: pulled.append(a) or [], lambda *a: pulled.append(a) or [],
                           lambda *a: pulled.append(a) or {})
        for when in (at(2026, 12, 2, 1, 30), at(2026, 12, 2, 4, 30)):
            rc = SB.run_final(md, root=self.root, clock=lambda w=when: w, sleep=lambda s: None, log=lambda m: None)
            self.assertEqual(rc, 3)
        self.assertEqual(pulled, [])
        sts = SB.statuses(self.root / "2026-12-01", "final")
        self.assertEqual([s["state"] for s in sts], ["MISSED-NIGHT"])
        self.assertTrue(prev.exists())
        self.assertFalse(list(prev.glob("final_20261202*")))


# =========================================================================================================
# S21-S29: targeted scenarios for the mutants the first round left alive
# =========================================================================================================

def shelf(t, n=130):
    """A 24.52 high inside the last 40 sessions, a tested shelf at 20.00 (15 and 20 sessions back), and 14 quiet
    sessions with true range 0.80 before t, so ATR(t-1) = 0.8000 exactly."""
    out = []
    for i, d in enumerate(H.sessions_before(t, n)):
        j = i - n
        if j <= -21:
            c, h, l = 24.12, 24.52, 23.72
        elif j in (-20, -15):
            c, h, l = 21.0, 21.4, 20.0
        else:
            c, h, l = 21.0, 21.4, 20.6
        out.append(cdl(d, "final", c, h, l, c, 1_000_000))
    return out


class M1Boundaries(unittest.TestCase):
    def test_S21_touch_uses_atr_at_t_and_is_inclusive_rr_3_is_inclusive(self):
        h = shelf(T0)
        p = prior60_of(h)
        wide = CB.evaluate(h, bar(20.6, 21.9, 20.21, 20.9, 1_000_000), p)      # ATR(t) 0.8636 > ATR(t-1) 0.80
        self.assertEqual((wide["atr_t"], wide["atr_prev"], wide["L"]["support_anchor"]), (0.8636, 0.8, 20.0))
        self.assertTrue(wide["m1"]["touch"])                                     # 20.21 <= 20.00 + 0.25 x 0.8636
        exact = CB.evaluate(h, bar(20.6, 21.0, 20.20, 20.9, 1_000_000), p)     # ATR(t) 0.80: touch line 20.20
        self.assertEqual((exact["L"]["rr_to_resistance"], exact["atr_t"]), (3.0, 0.8))
        self.assertEqual(exact["m1"], dict(valid_setup=True, atr_floor_ok=True, rr=True, touch=True, eligible=True))
        self.assertTrue(exact["m1_signal"])


class LevelsAsReported(Tmp):
    def test_S22_reported_levels_and_tickets_match_the_spec(self):
        names = ["GAPX", "VOLX", "HIGHX", "BIG", "UP1", "UP2", "UP3"]
        n = H.NightW(self.root, T0, names)
        spy(n, T0, 500.5, 500.5)
        hist = flat(T0)
        rows = {"GAPX": (bar(21.00, 21.9, 20.8, 21.7, 5_000_000), bar(20.99, 21.9, 20.8, 21.7, 5_000_000)),
                "VOLX": (bar(21.20, 21.9, 21.0, 21.7, 2_999_999), bar(21.20, 21.9, 21.0, 21.7, 3_000_000)),
                "HIGHX": (bar(21.20, 21.90, 21.0, 21.7, 5_000_000), bar(21.20, 21.91, 21.0, 21.7, 5_000_000))}
        for s, (ev, fin) in rows.items():
            n.add(s, hist, ev, ev["c"], fin, EV0, FI0)
        h90 = flat(T0, c=90.0, r=0.5)
        b90 = bar(92.80, 93.5, 92.6, 93.4, 5_000_000)
        n.add("BIG", h90, b90, 93.4, b90, EV0, FI0)
        for s in ("UP1", "UP2", "UP3"):
            n.add(s, flat(T0), bar(20.0, 20.4, 19.8, 20.3, 1_000_000), 20.3, bar(20.0, 20.4, 19.8, 20.3, 1_000_000), EV0, FI0)
        night = CB.analyze_night(n.day, examples=50)
        t = night["tally"]
        for k in PARAMS.stop_k:
            self.assertEqual((t.get(f"tk_m2_{k}_disappeared"), t.get(f"tk_m2_{k}_appeared"), t.get(f"tk_m2_{k}_changed"),
                              t.get(f"tk_m2_{k}_confirmed", 0)), (1, 1, 1, 0), k)          # BIG: never a ticket
            sides = []
            for b in rows["HIGHX"]:
                e = H.spec_eval(hist, b, prior60_of(hist))
                sides.append(H.spec_levels(e["T"], e["atr_t"], k, b["l"] - 0.2 * e["atr_t"]))
            la, lb = sides
            want = f"HIGHX M2 k={k}: " + ", ".join(f"{f} {la[f]}->{lb[f]}" for f in ("T", "C", "S", "P", "N") if la[f] != lb[f])
            self.assertIn(want, night["lists"]["x_levels"])


class RecordChoice(Tmp):
    def test_S23_the_earliest_usable_evening_row_and_quote_are_the_scan(self):
        n = H.NightW(self.root, T0, ["A"])
        spy(n, T0, 500.5, 500.5)
        hist = flat(T0)
        n.add("A", hist, bar(20.0, 20.4, 19.8, 20.2, 1_000_000), 20.2, bar(20.0, 20.4, 19.8, 20.2, 1_000_000), EV0, FI0)
        late = at(2026, 11, 30, 22, 5)                       # a second, later evening row and quote (a re-run)
        n._app(f"evening_{SB.stamp(late)}.jsonl", dict(symbol="A", pulled=SB.iso(late),
                                                        candles=hist[-4:] + [cdl(T0, "provisional", 20.3, 20.4, 19.8, 20.2, 1_000_000)]))
        n._app(f"quotes_{SB.stamp(late)}.jsonl", dict(symbol="A", pulled=SB.iso(late), regular_last=20.25, open=20.3))
        t = CB.analyze_night(n.day)["tally"]
        self.assertEqual((t.get("diff_o", 0), t.get("diff_c_scan", 0)), (0, 0))

    def test_S24_the_scan_close_is_the_quote_close_not_the_candle_close(self):
        n = H.NightW(self.root, T0, ["HUND", "UP1"])
        spy(n, T0, 500.5, 500.5)
        h = flat(T0, c=99.0, r=0.5)
        n.add("HUND", h, bar(99.5, 100.2, 99.4, 100.05, 1_000_000), 100.00, bar(99.5, 100.2, 99.4, 100.00, 1_000_000), EV0, FI0)
        n.add("UP1", flat(T0), bar(20.0, 20.4, 19.8, 20.3, 1_000_000), 20.3, bar(20.0, 20.4, 19.8, 20.3, 1_000_000), EV0, FI0)
        t = CB.analyze_night(n.day)["tally"]
        self.assertEqual((t["diff_c_candle"], t.get("diff_c_scan", 0), t.get("elig_flip", 0), t["elig_eve"]), (1, 0, 0, 2))

    def test_S25_not_final_then_truncated_reads_unconfirmed_not_truncated(self):
        n = H.NightW(self.root, T0, ["X", "Y"])
        spy(n, T0, 500.5, 500.5)
        hist = flat(T0)
        ev = bar(20.0, 20.4, 19.8, 20.2, 1_000_000)
        n.add("X", hist, ev, 20.2, None, EV0, FI0, final_rows=[
            (at(2026, 11, 30, 22, 0), hist + [cdl(T0, "provisional", **ev)], {}),
            (at(2026, 12, 1, 1, 50), [cdl(T0, "provisional", **ev)], {})])          # the night-1 pattern
        n.add("Y", hist, ev, 20.2, ev, EV0, FI0)
        night = CB.analyze_night(n.day)
        self.assertEqual(night["names"]["not_final_yet"], ["X"])
        self.assertEqual(night["names_count"]["final_truncated"], 0)

    def test_S26_a_99_percent_gate_at_exactly_99_percent_passes(self):
        names = [f"N{i:03d}" for i in range(100)]
        n = H.NightW(self.root, T0, names)
        spy(n, T0, 500.5, 500.5)
        hist = flat(T0, n=60)
        ev = bar(20.0, 20.4, 19.8, 20.2, 1_000_000)
        for i, s in enumerate(names):
            n.add(s, hist, ev, 20.2, ev, EV0, FI0, fin_kind="provisional" if i == 0 else "final")
        tl = CB.analyze_night(n.day)["timeline"][-1]
        self.assertEqual((round(tl["coverage"], 6), tl["gate_99_names_only"], tl["gate_99"], tl["unfinished"]), (0.99, True, True, 1))


class SamplerMore(Tmp):
    def test_S27_blank_test_issue_is_not_N(self):
        row = dict(symbol="ABCD", nasdaq_symbol="ABCD", name="Abcd Inc. - Common Stock", etf="N", test="", source="x",
                   exchange="Q", financial_status="N")
        keep, why, _ = SB.directory_decision(row)
        self.assertFalse(keep)
        self.assertTrue(why.startswith("test issue"))

    def test_S28_a_rerun_after_a_failure_pulls_only_names_without_a_usable_row(self):
        day = self.root / T0.isoformat()
        day.mkdir(parents=True)
        with open(day / "candidates.json", "w") as fh:
            json.dump(dict(session=T0.isoformat(), symbols=["A", "B"], reference=["SPY"], counts={}), fh)
        hist = flat(T0)
        with open(day / f"evening_{SB.stamp(EV0)}.jsonl", "w") as fh:
            fh.write(json.dumps(dict(symbol="A", pulled=SB.iso(EV0), attempt=1, mode="evening", session=T0.isoformat(),
                                     cls="PROVISIONAL", candles=hist[-4:] + [cdl(T0, "provisional", 20, 20.4, 19.8, 20.2, 1)])) + "\n")
        SB.RunStatus(self.root, T0, "evening", EV0).finish(EV0, "FAILED", error="RuntimeError: crash")
        asked = []

        def daily(sym, start, end):
            asked.append(sym)
            return [{"datetime": H.ms(c_d, "final"), "open": 20, "high": 20.4, "low": 19.8, "close": 20.2, "volume": 1}
                    for c_d in H.sessions_before(T0, 5)] + [{"datetime": H.ms(T0, "provisional"), "open": 20, "high": 20.4,
                                                              "low": 19.8, "close": 20.2, "volume": 1}]
        md = SB.MarketData(daily, lambda *a: [], lambda syms: {s: dict(quote=dict(openPrice=20), regular={}, fundamental={})
                                                                for s in syms})
        clock = iter(at(2026, 11, 30, 18, 0) + dt.timedelta(seconds=i) for i in range(10_000))
        rc = SB.run_evening(md, root=self.root, clock=lambda: next(clock), sleep=lambda s: None,
                            fetch=lambda u: b"", log=lambda m: None)
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(asked), ["B", "SPY"])

    def test_S29_clustered_interval_formula(self):
        lo, hi = CB.clustered_ci([3, 5], [20, 20])                # p 0.2, se = sqrt(2 x 2 / 1600) = 0.05
        self.assertAlmostEqual(lo, 0.2 - 1.96 * 0.05)
        self.assertAlmostEqual(hi, 0.2 + 1.96 * 0.05)


if __name__ == "__main__":
    unittest.main()
