#!/usr/bin/env python3

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from data_fetcher import HuobiData, _best_bid_ask, compute_features


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

    def test_fetch_cycle_preserves_trades_when_ticker_fails(self):
        provider = HuobiData()
        provider.fetch_ticker = lambda symbol: None
        provider.fetch_depth = lambda symbol, depth=20: {
            "bids": [[99.0, 1.0]],
            "asks": [[101.0, 1.0]],
            "ts": 1000,
        }
        provider.fetch_trades = lambda symbol, size=50: [
            {
                "trade_id": "t1",
                "direction": "buy",
                "amount": 1.0,
                "price": 100.0,
                "ts": 1000,
            }
        ]
        provider.fetch_klines = lambda symbol, period="1min", limit=5: []

        cycle = provider.fetch_cycle("btcusdt")

        self.assertIsNone(cycle.features)
        self.assertEqual(len(cycle.trades), 1)
        self.assertFalse(cycle.endpoint_ok["ticker"])
        self.assertIn("ticker", cycle.endpoint_errors)


if __name__ == "__main__":
    unittest.main()
