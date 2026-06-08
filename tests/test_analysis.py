"""Unit tests for the pure analysis logic.

Run either of:

    python -m unittest tests.test_analysis
    python tests/test_analysis.py

No network or credentials required -- everything operates on representative
Schwab Trader API payloads.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analysis  # noqa: E402


def _long(symbol: str, qty: float, avg: float, mark: float) -> dict:
    return {
        "longQuantity": qty,
        "shortQuantity": 0,
        "averagePrice": avg,
        "marketValue": mark * qty,
        "instrument": {"assetType": "EQUITY", "symbol": symbol},
    }


def _short(symbol: str, qty: float, avg: float, mark: float) -> dict:
    # Short market value is reported negative by Schwab.
    return {
        "longQuantity": 0,
        "shortQuantity": qty,
        "averagePrice": avg,
        "marketValue": -mark * qty,
        "instrument": {"assetType": "EQUITY", "symbol": symbol},
    }


def _stop(symbol: str, stop_price: float, *, tif: str, instruction: str = "SELL",
          status: str = "WORKING", order_id: int = 1, order_type: str = "STOP") -> dict:
    return {
        "orderId": order_id,
        "status": status,
        "duration": tif,
        "orderType": order_type,
        "stopPrice": stop_price,
        "quantity": 10,
        "orderLegCollection": [
            {"instruction": instruction, "quantity": 10,
             "instrument": {"assetType": "EQUITY", "symbol": symbol}}
        ],
    }


class PositionMath(unittest.TestCase):
    def test_long_gain(self) -> None:
        row = analysis.position_row(_long("AAPL", 10, 100.0, 110.0))
        assert row is not None
        self.assertEqual(row.symbol, "AAPL")
        self.assertEqual(row.quantity, 10)
        self.assertAlmostEqual(row.mark, 110.0)
        self.assertAlmostEqual(row.pl_dollars, 100.0)
        self.assertAlmostEqual(row.pl_pct, 10.0)
        self.assertFalse(row.is_short)

    def test_long_loss(self) -> None:
        row = analysis.position_row(_long("MSFT", 10, 200.0, 180.0))
        assert row is not None
        self.assertAlmostEqual(row.pl_dollars, -200.0)
        self.assertAlmostEqual(row.pl_pct, -10.0)

    def test_short_gain_when_price_falls(self) -> None:
        row = analysis.position_row(_short("TSLA", 5, 250.0, 240.0))
        assert row is not None
        self.assertEqual(row.quantity, -5)
        self.assertTrue(row.is_short)
        self.assertAlmostEqual(row.mark, 240.0)
        self.assertAlmostEqual(row.pl_dollars, 50.0)  # profit: sold high, mark lower
        self.assertAlmostEqual(row.pl_pct, 4.0)

    def test_zero_quantity_skipped(self) -> None:
        pos = _long("DEAD", 0, 100.0, 100.0)
        self.assertIsNone(analysis.position_row(pos))

    def test_zero_cost_basis_pct_is_none(self) -> None:
        row = analysis.position_row(_long("FREE", 10, 0.0, 5.0))
        assert row is not None
        self.assertIsNone(row.pl_pct)


class Balances(unittest.TestCase):
    def test_margin_account(self) -> None:
        sa = {"currentBalances": {"liquidationValue": 50000, "cashBalance": 20000,
                                  "buyingPower": 40000, "longMarketValue": 30000}}
        s = analysis.account_summary(sa)
        self.assertEqual(s.net_liquidating_value, 50000)
        self.assertEqual(s.buying_power, 40000)

    def test_cash_account_falls_back_to_cash_available(self) -> None:
        sa = {"currentBalances": {"liquidationValue": 10000, "cashBalance": 5000,
                                  "cashAvailableForTrading": 5000}}
        s = analysis.account_summary(sa)
        self.assertEqual(s.buying_power, 5000)

    def test_deployed_capital_and_pct(self) -> None:
        rows = analysis.position_rows([
            _long("AAPL", 10, 100.0, 110.0),   # mv 1100
            _long("MSFT", 10, 200.0, 180.0),   # mv 1800
            _short("TSLA", 5, 250.0, 240.0),   # mv -1200 -> abs 1200
        ])
        deployed = analysis.deployed_capital(rows)
        self.assertAlmostEqual(deployed, 4100.0)
        self.assertAlmostEqual(analysis.deployed_pct(deployed, 50000), 8.2)
        self.assertIsNone(analysis.deployed_pct(deployed, None))


class OrderFlattening(unittest.TestCase):
    def test_oco_bracket_flattened(self) -> None:
        oco = {
            "orderStrategyType": "OCO",
            "orderId": 1,
            "childOrderStrategies": [
                {"orderId": 2, "status": "WORKING", "duration": "GOOD_TILL_CANCEL",
                 "orderType": "LIMIT", "price": 130,
                 "orderLegCollection": [{"instruction": "SELL", "quantity": 10,
                                         "instrument": {"symbol": "AAPL"}}]},
                _stop("AAPL", 95, tif="DAY", order_id=3),
            ],
        }
        flat = analysis.flatten_orders([oco])
        # OCO container has no legs and is dropped; both children remain.
        self.assertEqual(len(flat), 2)
        rows = analysis.working_order_rows([oco])
        self.assertEqual(len(rows), 2)
        stop_rows = [r for r in rows if r.is_stop]
        self.assertEqual(len(stop_rows), 1)
        self.assertTrue(stop_rows[0].is_day)

    def test_terminal_status_filtered_out(self) -> None:
        filled = _stop("AAPL", 95, tif="GOOD_TILL_CANCEL", status="FILLED")
        self.assertEqual(analysis.working_order_rows([filled]), [])


class StopAnalysis(unittest.TestCase):
    def test_proximity_long_and_short(self) -> None:
        self.assertAlmostEqual(
            analysis.stop_proximity_pct(103, 100, is_short=False), 2.91262, places=4
        )
        self.assertAlmostEqual(
            analysis.stop_proximity_pct(100, 103, is_short=True), 3.0, places=4
        )
        self.assertEqual(analysis.stop_proximity_pct(0, 100, is_short=False), 0.0)

    def test_near_day_and_unprotected(self) -> None:
        positions = [
            _long("NVDA", 10, 100.0, 103.0),   # near its 100 stop (2.9%)
            _long("AAPL", 10, 100.0, 110.0),   # stop far (95) but DAY tif
            _long("AMZN", 5, 120.0, 130.0),    # no stop at all
        ]
        orders = [
            _stop("NVDA", 100.0, tif="GOOD_TILL_CANCEL", order_id=10),
            _stop("AAPL", 95.0, tif="DAY", order_id=11),
        ]
        report = analysis.analyze_stops(positions, orders, threshold_pct=5.0)
        self.assertEqual(len(report.evaluations), 2)
        flagged = {e.symbol for e in report.red_flags}
        self.assertEqual(flagged, {"NVDA", "AAPL"})
        self.assertFalse(report.all_clear)
        self.assertEqual(report.positions_without_stop, ["AMZN"])

        nvda = next(e for e in report.evaluations if e.symbol == "NVDA")
        self.assertTrue(nvda.near_flag)
        self.assertFalse(nvda.day_flag)

        aapl = next(e for e in report.evaluations if e.symbol == "AAPL")
        self.assertFalse(aapl.near_flag)
        self.assertTrue(aapl.day_flag)

    def test_all_clear(self) -> None:
        positions = [_long("GOOG", 10, 150.0, 200.0)]
        orders = [_stop("GOOG", 150.0, tif="GOOD_TILL_CANCEL")]  # 25% away, GTC
        report = analysis.analyze_stops(positions, orders, threshold_pct=5.0)
        self.assertTrue(report.all_clear)
        self.assertEqual(report.red_flags, [])
        self.assertEqual(report.positions_without_stop, [])

    def test_breached_stop_is_flagged(self) -> None:
        positions = [_long("XYZ", 10, 100.0, 90.0)]  # mark below the 95 stop
        orders = [_stop("XYZ", 95.0, tif="GOOD_TILL_CANCEL")]
        report = analysis.analyze_stops(positions, orders, threshold_pct=5.0)
        ev = report.evaluations[0]
        self.assertTrue(ev.near_flag)
        self.assertLess(ev.proximity_pct, 0)  # negative == breached

    def test_orphan_stop_no_position(self) -> None:
        orders = [_stop("ORPH", 50.0, tif="DAY", order_id=99)]
        report = analysis.analyze_stops([], orders, threshold_pct=5.0)
        ev = report.evaluations[0]
        self.assertFalse(ev.has_position)
        self.assertIsNone(ev.mark)
        self.assertFalse(ev.near_flag)   # cannot assess proximity without a mark
        self.assertTrue(ev.day_flag)     # but DAY TIF is still flagged


if __name__ == "__main__":
    unittest.main(verbosity=2)
