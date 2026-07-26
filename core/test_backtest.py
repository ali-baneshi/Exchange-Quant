#!/usr/bin/env python3

import os
import sys
import json
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from backtest import classical_ensemble_klines, run_backtest


FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "tests", "fixtures", "btcusdt_60min_slice.json")
GOLDEN_MAE = 0.43628347807596873


def _candles(n=25):
    out = []
    for i in range(n):
        close = 100.0 + (i % 5) - 2
        out.append({
            "ts": i,
            "open": close - 0.5,
            "close": close,
            "high": close + 1,
            "low": close - 1,
            "vol": 100.0 + i,
            "amount": 10.0,
            "count": 5,
        })
    return out


class BacktestTests(unittest.TestCase):
    def test_classical_ensemble_bounded(self):
        history = [{"conviction": 0.6, "volatility": 0.01, "direction": 1.0}] * 5
        pred = classical_ensemble_klines(history)
        self.assertGreaterEqual(pred, 0.0)
        self.assertLessEqual(pred, 1.0)

    def test_run_backtest_produces_errors(self):
        candles = _candles(30)
        errs = run_backtest(candles, window=5)
        self.assertGreater(len(errs), 0)
        for e in errs:
            self.assertGreaterEqual(e, 0.0)
            self.assertLessEqual(e, 1.0)

    def test_run_backtest_deterministic(self):
        candles = _candles(30)
        e1 = run_backtest(candles, window=5)
        e2 = run_backtest(candles, window=5)
        self.assertEqual(e1, e2)

    def test_golden_fixture_mae(self):
        with open(FIXTURE_PATH) as f:
            candles = json.load(f)
        errs = run_backtest(candles, window=5)
        self.assertGreater(len(errs), 0)
        import statistics
        mae = statistics.mean(errs)
        self.assertAlmostEqual(mae, GOLDEN_MAE, delta=0.001)


if __name__ == "__main__":
    unittest.main()
