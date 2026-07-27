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

    def test_feature_lookback_excludes_old_trades(self):
        ticker = {
            "close": 100.0,
            "high": 101,
            "low": 99,
            "bid": [99.5, 1.0],
            "ask": [100.5, 1.0],
            "ts": 200_000,
        }
        depth = {"bids": [[99.5, 2.0]], "asks": [[100.5, 1.0]], "ts": 200_000}
        trades = [
            {"direction": "sell", "amount": 1.0, "ts": 10_000},  # outside 60s
            {"direction": "sell", "amount": 1.0, "ts": 20_000},  # outside 60s
            {"direction": "buy", "amount": 1.0, "ts": 150_000},
            {"direction": "buy", "amount": 1.0, "ts": 180_000},
            {"direction": "buy", "amount": 1.0, "ts": 200_000},
        ]
        f = compute_features(ticker, depth, trades, [], feature_lookback_s=60)
        self.assertIsNotNone(f)
        self.assertEqual(f["trade_count"], 3)
        self.assertAlmostEqual(f["buy_ratio"], 1.0)
        self.assertEqual(f["feature_lookback_s"], 60)
        self.assertLessEqual(f["trade_window_span_ms"], 60_000)

    def test_default_lookback_floor_is_sixty_seconds(self):
        from config import feature_lookback_s
        self.assertEqual(feature_lookback_s(None), 60.0)
        self.assertEqual(feature_lookback_s(60), 60.0)
        self.assertEqual(feature_lookback_s(3600), 3600.0)


if __name__ == "__main__":
    unittest.main()
