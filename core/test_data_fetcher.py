#!/usr/bin/env python3

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from data_fetcher import _best_bid_ask, compute_features


class DataFetcherTests(unittest.TestCase):
    def test_empty_bid_ask_returns_none(self):
        ticker = {"close": 100.0, "high": 101, "low": 99, "bid": [], "ask": []}
        self.assertIsNone(_best_bid_ask(ticker))
        self.assertIsNone(compute_features(ticker, {"bids": [], "asks": []}, [], []))

    def test_compute_features_with_valid_ticker(self):
        ticker = {
            "close": 100.0,
            "high": 101,
            "low": 99,
            "bid": [99.5, 1.0],
            "ask": [100.5, 1.0],
            "ts": 12345,
        }
        depth = {"bids": [[99.5, 2.0]], "asks": [[100.5, 1.0]]}
        trades = [
            {"direction": "buy", "amount": 1.0, "ts": 1},
            {"direction": "sell", "amount": 1.0, "ts": 2},
        ]
        f = compute_features(ticker, depth, trades, [])
        self.assertIsNotNone(f)
        self.assertIn("buy_ratio", f)
        self.assertIn("imbalance", f)
        self.assertAlmostEqual(f["conviction"], f["buy_ratio"])

    def test_endpoint_skew_flag(self):
        ticker = {
            "close": 100.0,
            "high": 101,
            "low": 99,
            "bid": [99.5, 1.0],
            "ask": [100.5, 1.0],
            "ts": 100_000,
        }
        depth = {"bids": [[99.5, 2.0]], "asks": [[100.5, 1.0]], "ts": 200_000}
        trades = [{"direction": "buy", "amount": 1.0, "ts": 100_000}]
        f = compute_features(ticker, depth, trades, [])
        self.assertIn("endpoint_skew", f["quality_flags"])


if __name__ == "__main__":
    unittest.main()
