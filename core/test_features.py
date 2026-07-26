#!/usr/bin/env python3

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from features import compute_features


def _candle(open_, close, high=None, low=None, vol=100.0):
    high = high if high is not None else max(open_, close) + 1
    low = low if low is not None else min(open_, close) - 1
    return {
        "ts": 1,
        "open": open_,
        "close": close,
        "high": high,
        "low": low,
        "vol": vol,
        "amount": 1.0,
        "count": 10,
    }


class FeaturesTests(unittest.TestCase):
    def test_doji_zero_body_ratio(self):
        c = _candle(100, 100)
        f = compute_features(c, [])
        self.assertAlmostEqual(f["body_ratio"], 0.0)

    def test_first_candle_zero_returns(self):
        c = _candle(100, 101)
        f = compute_features(c, [])
        self.assertAlmostEqual(f["return"], 0.0)
        self.assertAlmostEqual(f["log_return"], 0.0)

    def test_buy_ratio_equals_conviction(self):
        c = _candle(100, 105)
        f = compute_features(c, [])
        self.assertAlmostEqual(f["buy_ratio"], f["conviction"])


if __name__ == "__main__":
    unittest.main()
