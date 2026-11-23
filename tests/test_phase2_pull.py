"""B3 pulls (spec 8 B3, 3.1, 2 "bars.py"): parsing and the resumable runner, no network, no token.

Run:  python -m unittest tests.test_phase2_pull
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "loops"))

import phase2_pull as P  # noqa: E402
from phase2 import bars as B  # noqa: E402
from phase2 import sample_bars as SB  # noqa: E402

NY, CH = ZoneInfo("America/New_York"), ZoneInfo("America/Chicago")
ACC = "0000320193-24-000067"


def candle(day, zone=CH, o=10.0, h=11.0, l=9.0, c=10.5, v=100):
    ms = int(dt.datetime.combine(dt.date.fromisoformat(day), dt.time(0), zone).timestamp() * 1000)
    return dict(datetime=ms, open=o, high=h, low=l, close=c, volume=v)


def drow(sym, name, etf="N", test="N"):
    return dict(symbol=sym, nasdaq_symbol=sym, name=name, etf=etf, test=test, source="x", exchange="N", financial_status="")


class Bars(unittest.TestCase):
    def test_the_final_candle_wins_whatever_the_order_and_a_provisional_one_is_never_stored(self):
        fin, prov = candle("2024-01-03", c=10.1), candle("2024-01-03", NY, c=10.9)
        for raw in ([candle("2024-01-02"), fin, prov], [candle("2024-01-02"), prov, fin]):
            bars, aside = B.clean(raw)
            self.assertEqual([(b["d"], b["c"]) for b in bars], [("2024-01-02", 10.5), ("2024-01-03", 10.1)])
            self.assertEqual(aside["not_final"], [])
        bars, aside = B.clean([candle("2024-01-02"), candle("2024-01-03", NY)])
        self.assertEqual([b["d"] for b in bars], ["2024-01-02"])
        self.assertEqual(aside["not_final"], ["2024-01-03"])

    def test_dates_are_new_york_dates_on_both_sides_of_the_clock_change(self):
        days = ["2024-03-08", "2024-03-11", "2024-11-01", "2024-11-04"]
        self.assertEqual([b["d"] for b in B.clean([candle(d) for d in days])[0]], days)

    def test_impossible_bars_are_dropped_and_listed(self):
        for bad in (dict(l=12.0), dict(c=11.5), dict(c=8.5), dict(v=0), dict(l=0.0, c=5.0), dict(h=float("nan")),
                    dict(o=None)):
            bars, aside = B.clean([candle("2024-01-02"), candle("2024-01-03", **bad)])
            self.assertEqual([b["d"] for b in bars], ["2024-01-02"], bad)
            self.assertEqual([x[0] for x in aside["impossible"]], ["2024-01-03"], bad)

    def test_two_different_final_candles_for_a_date_are_listed(self):
        _, aside = B.clean([candle("2024-01-02"), candle("2024-01-02", c=10.6)])
        self.assertEqual(aside["duplicate"], ["2024-01-02"])

    def test_response_class_reads_final_bars_only(self):
        def cls(raw):
            return B.response_class(B.clean(raw)[0], "2024-01-02", "2024-01-04")
        a, b, c = candle("2024-01-02"), candle("2024-01-03"), candle("2024-01-04")
        today = candle("2024-01-05", NY)
        for raw, want in (([], B.EMPTY), ([today], B.EMPTY), ([c, today], B.TRUNCATED), ([c], B.TRUNCATED),
                          ([a, b, today], B.STALE), ([b, c, today], B.LATE_START), ([a, b, c, today], B.OK)):
            self.assertEqual(cls(raw), want)


class Names(unittest.TestCase):
    def test_only_the_names_b4_rules_on_are_added_back(self):
        rows = [drow("AAA", "Aaa Inc. - Common Stock"), drow("HESM", "Hess Midstream LP Class A Share"),
                drow("MSIF", "MSC Income Fund, Inc. Common Stock"), drow("ETFX", "Some ETF", etf="Y"),
                drow("TST", "Test", test="Y"), drow("SPAC", "Foo Acquisition Corp Class A"),
                drow("WAR", "Bar Inc Warrants"), drow("SUNC", "SunocoCorp LLC Common Units"),
                drow("KOF", "Coca Cola Femsa American Depositary Shares, each 10 Units"), drow("UNI", "Foo Corp Units, each one share and one warrant"),
                drow("PFD", "Foo Inc Depositary Shares each 1/1000th of a share of Series A Preferred Stock"),
                drow("ITUB", "Itau Unibanco American Depositary Shares (each repstg 1 Preferred share)"), drow("BF.B", "Brown Forman Inc Class B Common Stock")]
        keep, left = B.pull_list(iter(rows))
        self.assertEqual([k["symbol"] for k in keep], ["AAA", "BF.B", "HESM", "ITUB", "KOF", "MSIF", "SUNC"])
        self.assertEqual({k["symbol"] for k in keep if k["b4"]}, {"HESM", "ITUB", "KOF", "MSIF", "SUNC"})
        self.assertEqual({x["symbol"] for x in left}, {"ETFX", "TST", "SPAC", "WAR", "UNI", "PFD"})
        self.assertEqual(len(keep) + len(left), len(rows))


class Splits(unittest.TestCase):
    def test_good_and_flagged_rows(self):
        d, e = dt.date(2024, 6, 10), dt.date(2023, 8, 24)
        self.assertEqual(B.split_rows([(d, 10.0), (e, 0.1)]), ([["2023-08-24", 0.1], ["2024-06-10", 10.0]], []))
        for bad in (0.0, -2.0, 1.0, float("inf"), float("nan")):
            good, flagged = B.split_rows([(d, bad), (e, 2.0)])
            self.assertEqual((good, [f[0] for f in flagged]), ([["2023-08-24", 2.0]], ["2024-06-10"]), bad)
            json.dumps(flagged, allow_nan=False)
        self.assertEqual(B.split_rows([(d, 2.0), (d, 3.0)]), ([], [["2024-06-10", 2.0], ["2024-06-10", 3.0]]))
        self.assertEqual(B.yahoo_symbol("BF.B"), "BF-B")

    def test_an_empty_history_is_not_no_splits(self):
        row = P.split_work(lambda s: ([], dict(n=0, first="", last="")), lambda _: None)("X")
        self.assertEqual(row["cls"], B.EMPTY)
        row = P.split_work(lambda s: ([], dict(n=5, first="a", last="b")), lambda _: None)("X")
        self.assertEqual((row["cls"], row["splits"], row["n"]), (B.OK, [], 5))


def block(rows):
    names = ("accessionNumber", "filingDate", "acceptanceDateTime", "form", "items", "fileNumber")
    return {n: [r[i] for r in rows] for i, n in enumerate(names)}


class Edgar(unittest.TestCase):
    DOC = dict(cik="320193", name="X", sic="3571", sicDescription="c", entityType="operating", tickers=["X"], filings=dict(
        recent=block([("a-1", "2024-05-02", "t", "8-K", "2.02,9.01", "001-1"), ("a-2", "2024-05-03", "t", "8-K", "8.01", "001-1"),
                      ("a-3", "2024-05-04", "t", "8-K/A", "2.02", "001-1"), ("a-4", "2024-02-01", "t", "10-K", "", "814-0001"),
                      ("a-5", "2021-11-30", "t", "8-K", "2.02", "001-1"), ("a-6", "2024-05-05", "t", "8-K", "12.02", "001-1")]),
        files=[dict(name="f1.json", filingTo="2022-01-01"), dict(name="f0.json", filingTo="2021-11-30")]))

    def test_submissions(self):
        old = block([("b-1", "2021-12-15", "t", "8-K", "2.02", ""), ("a-1", "2024-05-02", "t", "8-K", "2.02", "")])
        r = B.submissions_record(self.DOC, [old])
        self.assertEqual([a["acc"] for a in r["earnings"]], ["b-1", "a-1", "a-3"])
        self.assertEqual((r["sic"], r["bdc_files"], r["forms"]["10-K"]), ("3571", ["814-0001"], ["2024-02-01"]))
        self.assertEqual(r["first_filing"], "2021-11-30")
        succ = dict(self.DOC, formerNames=[dict(name="Old")], filings=dict(recent=block([("s", "2024-10-01", "t", "8-K12B", "", "")])))
        self.assertEqual((B.submissions_record(succ)["successor"], B.submissions_record(succ)["former_names"]),
                         ([["2024-10-01", "8-K12B"]], [dict(name="Old")]))
        self.assertEqual(B.older_files(self.DOC), ["f1.json"])
        broken = block([("a", "2024-01-01", "t", "8-K", "2.02", "")])
        broken["items"] = []                      # an absent column is blanks; a short one is refused
        broken["form"] = ["8-K", "8-K"]
        with self.assertRaises(ValueError):
            B.submissions_record(dict(self.DOC, filings=dict(recent=broken)))

    def test_header(self):
        tag = (f"<SEC-HEADER>\n<ACCEPTANCE-DATETIME>20240502163045\n<ACCESSION-NUMBER>{ACC}\n<TYPE>8-K\n<ITEMS>2.02\n<ITEMS>9.01\n")
        long = (f"<SEC-HEADER>{ACC}.hdr.sgml : 20240502\n<ACCEPTANCE-DATETIME>20240502163045\nACCESSION NUMBER:\t\t{ACC}\n"
                "CONFORMED SUBMISSION TYPE:\t8-K\nITEM INFORMATION:\t\tResults of Operations and Financial Condition\n"
                "ITEM INFORMATION:\t\tFinancial Statements and Exhibits\n")
        for text, second in ((tag, "9.01"), (long, "Financial Statements and Exhibits")):
            h = B.parse_header(text, ACC)
            self.assertEqual((h["accepted_et"], h["type"], h["items"], h["match"]), ("2024-05-02T16:30:45", "8-K", ["2.02", second], True))
        self.assertFalse(B.parse_header(tag.replace("2.02", "8.01"), ACC)["match"])
        self.assertFalse(B.parse_header(tag.replace("8-K", "10-Q"), ACC)["match"])
        for bad in ("", f"<ACCESSION-NUMBER>{ACC}\n", "<ACCEPTANCE-DATETIME>20240502163045\n<ACCESSION-NUMBER>0000000001-24-000001\n",
                    f"<ACCEPTANCE-DATETIME>2024\n{ACC}", "<ACCEPTANCE-DATETIME>20240502163045\n"):
            with self.assertRaises(ValueError):
                B.parse_header(bad, ACC)

    def test_urls_and_ciks(self):
        self.assertEqual(B.header_url(320193, ACC), f"https://www.sec.gov/Archives/edgar/data/320193/000032019324000067/{ACC}.hdr.sgml")
        with self.assertRaises(ValueError):
            B.header_url(1, "../x")
        doc = dict(fields=["cik", "name", "ticker", "exchange"], data=[[1, "a", "BF-B", "N"], [2, "b", "X", "N"], [3, "c", None, ""]])
        self.assertEqual(B.cik_table(doc), {"BF.B": 1, "X": 2})
        more = {"0": dict(cik_str=9, ticker="X"), "1": dict(cik_str=7, ticker="Y")}
        self.assertEqual(B.cik_table(doc, more), {"BF.B": 1, "X": 2, "Y": 7})


class Runner(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.out = Path(t.name)

    def run_step(self, todo, work, **kw):
        return P.step("bars", self.out, todo, str, work, log=lambda *_: None, sleep=lambda *_: None, **kw)

    def test_a_rerun_skips_what_is_done_and_retries_errors_and_a_cut_off_line(self):
        calls, down = [], [True]

        def work(s):
            calls.append(s)
            if s == "B" and down[0]:
                raise RuntimeError("x")
            return dict(cls=B.OK, bars=[])
        self.run_step(["A", "B"], work)
        self.assertEqual(calls, ["A", "B", "B", "B"])
        with open(self.out / "bars.jsonl", "a") as fh:
            fh.write('{"symbol":"C","cls":"O')
        calls.clear()
        down[0] = False
        self.run_step(["A", "B", "C"], work)
        self.assertEqual(calls, ["C", "B"])                                # never-tried first
        self.assertEqual(P.last_by(self.out / "bars.jsonl"), {"A": "OK", "B": "OK", "C": "OK"})

    def test_a_doubtful_answer_is_believed_only_when_enough_answers_agree(self):
        for cls, need in B.AGREE.items():
            n = []
            self.run_step([cls], lambda s: n.append(s) or dict(cls=cls, sig=(1,)))
            self.assertEqual((len(n), P.last_by(self.out / "bars.jsonl")[cls]), (need, cls))
            m = []
            self.run_step(["ok" + cls], lambda s: m.append(s) or (dict(cls=cls, sig=(1,)) if len(m) < 2 else dict(cls=B.OK)))
            self.assertEqual(P.last_by(self.out / "bars.jsonl")["ok" + cls], B.OK)
            k = []
            self.run_step(["x" + cls], lambda s: k.append(s) or dict(cls=cls, sig=(len(k),)))
            self.assertEqual(P.last_by(self.out / "bars.jsonl")["x" + cls], B.UNSETTLED)
            self.assertNotIn(B.UNSETTLED, P.DONE["bars"])

    def test_the_rounds_are_a_minute_apart(self):
        naps = []
        P.step("bars", self.out, ["A"], str, lambda s: dict(cls=B.EMPTY), log=lambda *_: None, sleep=naps.append)
        self.assertEqual(naps, [60.0, 60.0])

    def test_a_run_of_failures_or_empty_answers_stops_the_step_and_stores_nothing(self):
        def error(s):
            raise RuntimeError("down")
        for work in (error, lambda s: dict(cls=B.EMPTY, sig=()), lambda s: dict(cls=B.TRUNCATED, sig=())):
            with self.assertRaises(P.Stop):
                self.run_step([str(i) for i in range(100)], work)
            self.assertEqual(list(P.rows(self.out / "bars.jsonl")), [])

    def test_an_interrupted_run_never_makes_failed_names_look_untried(self):
        todo = [f"{'bad' if i % 4 == 0 else 'ok'}{i:03d}" for i in range(100)]
        n = [0]

        def work(s):
            n[0] += 1
            if n[0] == 100:
                raise P.Stop("16:45")
            if s.startswith("bad"):
                raise RuntimeError("x")
            return dict(cls=B.OK)
        with self.assertRaises(P.Stop):
            self.run_step(todo, work)
        n[0] = 1000
        self.run_step(todo, work)
        got = P.last_by(self.out / "bars.jsonl")
        self.assertEqual((len(got), got["ok099"], got["bad000"]), (100, "OK", "ERROR"))

    def test_an_outage_leaves_its_names_never_tried(self):
        def down(s):
            if s > "03":
                raise RuntimeError("x")
            return dict(cls=B.OK)
        with self.assertRaises(P.Stop):
            self.run_step([f"{i:02d}" for i in range(60)], down)
        self.assertEqual(set(P.last_by(self.out / "bars.jsonl")), {"00", "01", "02", "03"})

    def test_empty_answers_wait_for_the_control_name(self):
        for b in ("A", "C"):
            P.append(self.out / "bars.jsonl", dict(symbol=b, cls=B.ERROR))

        def bad():
            P.control_ok("bars", dict(cls=B.EMPTY), B.OK)
        with self.assertRaises(P.Stop):
            self.run_step(["A", "C"], lambda s: dict(cls=B.EMPTY), control=bad)
        self.assertEqual(P.last_by(self.out / "bars.jsonl"), {"A": B.ERROR, "C": B.ERROR})
        self.run_step(["A", "C"], lambda s: dict(cls=B.EMPTY), control=lambda: P.control_ok("bars", dict(cls=B.OK), B.OK))
        self.assertEqual(P.last_by(self.out / "bars.jsonl"), {"A": B.EMPTY, "C": B.EMPTY})

    def test_the_batch_end_is_the_session_before_its_first_day_and_stays(self):
        at = lambda *a: lambda: dt.datetime(2026, 11, *a, tzinfo=NY)               # noqa: E731
        for now, want in ((at(23, 16, 10), "2026-11-20"), (at(27, 13, 30), "2026-11-25"), (at(28, 9, 0), "2026-11-27"),
                          (at(24, 9, 0), "2026-11-23")):
            with tempfile.TemporaryDirectory() as t:
                self.assertEqual(P.batch_end(Path(t), now), want)
                self.assertEqual(P.batch_end(Path(t), at(30, 9, 0)), want)

    def test_bars_after_the_batch_end_are_cut(self):
        days = ["2024-01-02", "2024-01-03", "2024-01-04"]
        row = P.bar_work(lambda *_: [candle(d) for d in days] + [candle("2024-01-05", NY)], {"X": ["X"]},
                         dt.datetime(2024, 1, 2, tzinfo=NY), "2024-01-03", lambda: None)("X")
        self.assertEqual((row["cls"], [b[0] for b in row["bars"]], row["not_final"]), (B.OK, days[:2], []))

    def test_names_that_always_fail_never_block_the_untried_ones(self):
        bad = [f"a{i}" for i in range(25)]
        for b in bad:
            P.append(self.out / "bars.jsonl", dict(symbol=b, cls=B.ERROR))

        def work(s):
            if s in bad:
                raise RuntimeError("gone")
            return dict(cls=B.OK)
        self.run_step(bad + ["z1", "z2"], work)
        got = P.last_by(self.out / "bars.jsonl")
        self.assertEqual((got["z1"], got["z2"], got["a0"]), ("OK", "OK", "ERROR"))

    def test_a_stop_inside_the_work_is_not_retried_or_recorded(self):
        def work(s):
            raise P.Stop("SEC answered 429")
        with self.assertRaises(P.Stop):
            self.run_step(["A"], work)
        self.assertEqual(list(P.rows(self.out / "bars.jsonl")), [])

    def test_the_schwab_window_and_token(self):
        at = lambda h, m, d=23: dt.datetime(2026, 11, d, h, m, tzinfo=NY)          # noqa: E731  Mon 11-23
        for now, want in ((at(8, 29), False), (at(8, 30), True), (at(16, 44), True), (at(16, 45), False),
                          (at(1, 0), False),
                          (at(1, 0, 28), False), (at(8, 30, 28), True), (at(20, 0, 28), True)):
            self.assertEqual(P.schwab_open(now), want, now)
        for hours in (None, 2.9, -18.0):
            with self.assertRaises(P.Stop):
                P.schwab_gate(lambda: (hours, None), lambda: at(10, 0))()
        P.schwab_gate(lambda: (4.0, None), lambda: at(10, 0))()

    def test_a_class_share_falls_back_to_its_other_form_on_an_empty_answer_or_an_error(self):
        now = lambda: dt.datetime(2024, 1, 4, 10, 0, tzinfo=NY)                    # noqa: E731
        start = dt.datetime(2024, 1, 2, tzinfo=NY)
        for fail in (False, True):
            def daily(sym, *_):
                if sym == "BF.B":
                    return [candle("2024-01-02"), candle("2024-01-03")]
                if fail:
                    raise RuntimeError("HTTP 400")
                return []
            row = P.bar_work(daily, {"BF.B": ["BF/B", "BF.B"]}, start, "2024-01-03", now)("BF.B")
            self.assertEqual((row["form"], row["cls"], row["n"]), ("BF.B", B.OK, 2))

        def dead(*_):
            raise RuntimeError("HTTP 500")
        with self.assertRaises(RuntimeError):
            P.bar_work(dead, {"X": ["X"]}, start, "2024-01-03", now)("X")

    def test_the_client_is_rebuilt_when_the_token_moves_or_the_client_is_old(self):
        built, t, exp = [], [0.0], ["2026-11-22T16:36:15-05:00"]
        build = lambda: built.append(1) or SB.MarketData(lambda *a: [], lambda *a: [], lambda *a: {})   # noqa: E731
        f = P.FreshClient(build, lambda: (9.0, exp[0]), lambda: t[0])
        f.daily("A")
        f.daily("A")
        self.assertEqual(len(built), 1)
        exp[0] = "2026-11-30T11:07:35-05:00"
        f.quotes(["A"])
        self.assertEqual(len(built), 2)
        t[0] = P.CLIENT_LIFE + 1
        f.daily("A")
        self.assertEqual(len(built), 3)

    def test_quotes_list_the_missing_and_never_replace_a_fuller_file(self):
        SB.atomic_write_json(self.out / "names.json", [dict(symbol=s, forms=SB.schwab_forms(s)) for s in ("AAA", "BF.B", "ZZZ")])
        full = {"AAA": dict(quote={}), "BF/B": dict(quote={}), "SPY": dict(quote={})}
        P.quote_step(self.out, lambda part: full, lambda *_: None, lambda *_: None)
        self.assertEqual([r["symbol"] for r in P.rows(self.out / "quotes.jsonl")], ["AAA", "BF.B", "SPY"])
        self.assertEqual(json.loads((self.out / "quotes_missing.json").read_text()), ["ZZZ"])
        self.assertEqual(P.bar_names(self.out)["BF.B"], ["BF/B", "BF.B"])
        for worse in (lambda part: {"AAA": dict(quote={})}, self.boom):
            with self.assertRaises(P.Stop):
                P.quote_step(self.out, worse, lambda *_: None, lambda *_: None)
            self.assertEqual(len(list(P.rows(self.out / "quotes.jsonl"))), 3)

    @staticmethod
    def boom(part):
        raise RuntimeError("HTTP 500")

    def test_the_canary(self):
        accs = [f"0000320193-24-00000{i}" for i in range(4)]
        P.append(self.out / "submissions.jsonl", dict(symbol="AAPL", cls=B.OK, cik=320193, earnings=[dict(acc=a) for a in accs]))

        def get(hour):
            return lambda url: f"<ACCEPTANCE-DATETIME>20240502{hour}45\n<ACCESSION-NUMBER>{url.split('/')[-1][:20]}\n<TYPE>8-K\n<ITEMS>2.02\n"
        P.canary(self.out, get("1630"))
        for wrong in ("2030", "1230"):
            with self.assertRaises(P.Stop):
                P.canary(self.out, get(wrong))

    def test_no_cik_is_asked_again_and_an_unlisted_ticker_is_flagged(self):
        self.assertNotIn(B.NO_CIK, P.DONE["submissions"])
        self.assertEqual(P.submissions_work(None, {})("X"), dict(cls=B.NO_CIK))
        row = P.submissions_work(lambda u: json.dumps(dict(Edgar.DOC, filings=dict(recent=block([])))), {"Q": 320193})("Q")
        self.assertEqual((row["cls"], row["ticker_listed"]), (B.OK, False))

    def test_the_directory_is_refused_when_cut_off_and_fixed_once_stored(self):
        body = b"Symbol|Security Name|Test Issue|ETF\nAAA|Aaa Common Stock|N|N\n"
        with self.assertRaises(P.Stop):
            P.directory(self.out, lambda u: body, lambda *_: None)
        self.assertFalse((self.out / "names.json").exists())
        P.directory(self.out, lambda u: body + b"File Creation Time: x|||\n", lambda *_: None)
        self.assertEqual([n["symbol"] for n in P.names(self.out)], ["AAA"])
        P.directory(self.out, lambda u: self.fail("fetched again"), lambda *_: None)

    def test_the_header_list_takes_each_filing_once(self):
        for s in ("GOOG", "GOOGL"):
            P.append(self.out / "submissions.jsonl", dict(symbol=s, cls=B.OK, cik=1, earnings=[dict(acc=ACC)]))
        self.assertEqual(P.header_list(self.out), [(1, ACC)])

    def test_the_sec_reader_refuses_other_hosts(self):
        src = (ROOT / "loops" / "phase2_pull.py").read_text()
        self.assertEqual(P.EDGAR_HOSTS, ("https://www.sec.gov/", "https://data.sec.gov/"))
        self.assertIn("follow_redirects=False", src)

    def test_no_contact_is_in_the_code(self):
        for f in ("loops/phase2_pull.py", "loops/phase2/bars.py"):
            self.assertNotIn("@gmail", (ROOT / f).read_text())


if __name__ == "__main__":
    unittest.main()
