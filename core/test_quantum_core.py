#!/usr/bin/env python3

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from delta_adaptive import compute_delta, compute_delta_from_kline_features
from quantum_core import born_rule_predict


class QuantumCoreTests(unittest.TestCase):
    def test_orderbook_delta_is_constructive_for_strong_clean_imbalance(self):
        history = [{"buy_ratio": 0.7, "imbalance": 0.9, "volatility": 0.001} for _ in range(10)]
        delta, confidence = compute_delta(history)
        self.assertLess(delta, math.pi / 2)
        self.assertGreaterEqual(confidence, 0.0)

    def test_kline_proxy_delta_is_valid_without_imbalance(self):
        history = [
            {"open": 100, "close": 102, "high": 103, "low": 99, "volatility": 0.04, "body_ratio": 0.5},
            {"open": 102, "close": 103, "high": 104, "low": 101, "volatility": 0.03, "body_ratio": 0.33},
            {"open": 103, "close": 101, "high": 105, "low": 100, "volatility": 0.05, "body_ratio": 0.4},
            {"open": 101, "close": 104, "high": 105, "low": 100, "volatility": 0.05, "body_ratio": 0.6},
        ]
        delta, confidence = compute_delta_from_kline_features(history)
        self.assertGreaterEqual(delta, 0.0)
        self.assertLessEqual(delta, math.pi)
        self.assertGreaterEqual(confidence, 0.0)

    def test_kline_proxy_wins_over_synthetic_imbalance(self):
        history = [
            {"buy_ratio": 0.2, "conviction": 0.2, "imbalance": -0.6, "open": 100, "close": 99, "high": 101, "low": 98},
            {"buy_ratio": 0.8, "conviction": 0.8, "imbalance": 0.6, "open": 99, "close": 101, "high": 102, "low": 98},
            {"buy_ratio": 0.3, "conviction": 0.3, "imbalance": -0.4, "open": 101, "close": 100, "high": 102, "low": 99},
            {"buy_ratio": 0.7, "conviction": 0.7, "imbalance": 0.4, "open": 100, "close": 102, "high": 103, "low": 99},
        ]
        _, meta = born_rule_predict(history)
        self.assertEqual(meta["delta_source"], "kline_proxy")

    def test_flat_history_has_delta_and_fallback_reason(self):
        history = [{"buy_ratio": 0.5667, "imbalance": 0.0, "volatility": 0.01} for _ in range(15)]
        pred, meta = born_rule_predict(history)
        self.assertAlmostEqual(pred, 0.5667)
        self.assertIsNotNone(meta["delta"])
        self.assertEqual(meta["fallback_reason"], "flat_history")
        self.assertEqual(meta["delta_source"], "orderbook")

    def test_two_bucket_prediction_reports_interference(self):
        history = [
            {"buy_ratio": 0.2, "imbalance": 0.7, "volatility": 0.001},
            {"buy_ratio": 0.25, "imbalance": 0.7, "volatility": 0.001},
            {"buy_ratio": 0.75, "imbalance": 0.7, "volatility": 0.001},
            {"buy_ratio": 0.8, "imbalance": 0.7, "volatility": 0.001},
        ]
        pred, meta = born_rule_predict(history)
        self.assertGreaterEqual(pred, 0.0)
        self.assertLessEqual(pred, 1.0)
        self.assertEqual(meta["fallback_reason"], "none")
        self.assertIsNotNone(meta["classical_part"])
        self.assertIsNotNone(meta["interference_term"])

    def test_null_buy_ratio_treated_as_zero(self):
        history = [
            {"buy_ratio": None, "conviction": 0.4, "imbalance": 0.5, "volatility": 0.001},
            {"buy_ratio": 0.8, "imbalance": 0.5, "volatility": 0.001},
            {"buy_ratio": 0.2, "imbalance": 0.5, "volatility": 0.001},
            {"buy_ratio": 0.75, "imbalance": 0.5, "volatility": 0.001},
        ]
        pred, meta = born_rule_predict(history)
        self.assertGreaterEqual(pred, 0.0)
        self.assertLessEqual(pred, 1.0)
        self.assertEqual(meta["fallback_reason"], "none")

    def test_insufficient_history_fallback(self):
        pred, meta = born_rule_predict([{"buy_ratio": 0.6}])
        self.assertEqual(meta["fallback_reason"], "insufficient_history")

    def test_uniform_history_uses_flat_fallback(self):
        history = [{"buy_ratio": 0.5, "imbalance": 0.1, "volatility": 0.001} for _ in range(6)]
        pred, meta = born_rule_predict(history)
        self.assertEqual(meta["fallback_reason"], "flat_history")
        self.assertAlmostEqual(pred, 0.5)


if __name__ == "__main__":
    unittest.main()
