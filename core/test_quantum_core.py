#!/usr/bin/env python3

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from delta_adaptive import compute_delta, compute_delta_from_kline_features, compute_delta_from_orderbook_features
from quantum_core import born_rule_predict


class QuantumCoreTests(unittest.TestCase):
    def test_buckets_preserve_probability_mass(self):
        history = [
            {"buy_ratio": value, "imbalance": 0.5, "volatility": 0.0}
            for value in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
        ]
        _, meta = born_rule_predict(history)
        self.assertAlmostEqual(meta["p_high"] + meta["p_low"], 1.0)

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
        self.assertIn(meta["fallback_reason"], ("none", "saturation_gate"))
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
        self.assertIn(meta["fallback_reason"], ("none", "saturation_gate"))

    def test_insufficient_history_fallback(self):
        pred, meta = born_rule_predict([{"buy_ratio": 0.6}])
        self.assertEqual(meta["fallback_reason"], "insufficient_history")

    def test_uniform_history_uses_flat_fallback(self):
        history = [{"buy_ratio": 0.5, "imbalance": 0.1, "volatility": 0.001} for _ in range(6)]
        pred, meta = born_rule_predict(history)
        self.assertEqual(meta["fallback_reason"], "flat_history")
        self.assertAlmostEqual(pred, 0.5)

    def test_bullish_history_saturation_gate(self):
        history = [
            {"buy_ratio": v, "imbalance": 0.6, "volatility": 0.001}
            for v in [0.65, 0.68, 0.70, 0.72, 0.71, 0.69, 0.70, 0.73, 0.67, 0.71, 0.70, 0.72, 0.68, 0.69, 0.71]
        ]
        pred, meta = born_rule_predict(history, skip_volume_bucket=True)
        self.assertLess(pred, 0.99)
        self.assertEqual(meta["fallback_reason"], "saturation_gate")
        self.assertAlmostEqual(pred, meta["classical_part"], places=4)

    def test_live_skips_volume_bucket_by_default_in_ensemble(self):
        history = [
            {"buy_ratio": 0.5, "buy_ratio_volume": v, "imbalance": 0.2, "volatility": 0.001}
            for v in [0.1, 0.2, 0.8, 0.9, 0.15, 0.85, 0.3, 0.7, 0.4, 0.6, 0.25, 0.75, 0.35, 0.65, 0.45]
        ]
        pred, meta = born_rule_predict(history, skip_volume_bucket=True)
        self.assertNotEqual(meta["bucket_feature"], "buy_ratio_volume")

    def test_flat_buy_ratio_uses_volume_buckets(self):
        history = [
            {"buy_ratio": 0.5, "buy_ratio_volume": v, "imbalance": 0.2, "volatility": 0.001}
            for v in [0.1, 0.2, 0.8, 0.9, 0.15, 0.85, 0.3, 0.7, 0.4, 0.6, 0.25, 0.75, 0.35, 0.65, 0.45]
        ]
        pred, meta = born_rule_predict(history, skip_volume_bucket=False)
        self.assertEqual(meta["fallback_reason"], "none")
        self.assertEqual(meta["bucket_feature"], "buy_ratio_volume")
        self.assertIsNotNone(meta["interference_term"])

    def test_flat_buy_ratio_and_volume_use_imbalance_buckets(self):
        imbs = [0.1, -0.2, 0.3, -0.4, 0.5, -0.1, 0.2, -0.3, 0.4, -0.5, 0.15, -0.25, 0.35, -0.45, 0.05]
        history = [
            {"buy_ratio": 0.5, "buy_ratio_volume": 0.5, "imbalance": imb, "volatility": 0.001}
            for imb in imbs
        ]
        pred, meta = born_rule_predict(history, skip_volume_bucket=False)
        self.assertEqual(meta["bucket_feature"], "imbalance")
        self.assertIn(meta["fallback_reason"], ("none", "saturation_gate"))
        self.assertIsNotNone(meta["interference_term"])

    def test_orderbook_delta_bounded_to_half_pi(self):
        cases = [
            [{"buy_ratio": 0.5, "imbalance": 0.9, "volatility": 0.001}] * 10,
            [{"buy_ratio": 0.5, "imbalance": 0.05, "volatility": 0.08}] * 10,
        ]
        for history in cases:
            delta, _ = compute_delta_from_orderbook_features(history)
            self.assertGreaterEqual(delta, 0.0)
            self.assertLessEqual(delta, math.pi / 2 + 1e-9)

    def test_destructive_interference_falls_back_to_classical(self):
        history = []
        for i in range(8):
            history.append({
                "buy_ratio": 0.2 + 0.6 * (i % 2),
                "open": 100,
                "close": 100 + (0.5 if i % 2 else -0.5),
                "high": 102,
                "low": 98,
                "volatility": 0.08,
                "body_ratio": 0.1,
            })
        pred, meta = born_rule_predict(history)
        self.assertEqual(meta["fallback_reason"], "destructive_interference")
        self.assertAlmostEqual(pred, meta["classical_part"])

    def test_delta_override_bypasses_destructive_gate(self):
        history = [
            {"buy_ratio": 0.2, "imbalance": 0.7, "volatility": 0.001},
            {"buy_ratio": 0.25, "imbalance": 0.7, "volatility": 0.001},
            {"buy_ratio": 0.75, "imbalance": 0.7, "volatility": 0.001},
            {"buy_ratio": 0.8, "imbalance": 0.7, "volatility": 0.001},
        ]
        pred_pi, meta_pi = born_rule_predict(history, delta_override=math.pi)
        pred_zero, meta_zero = born_rule_predict(history, delta_override=0.0)
        self.assertEqual(meta_pi["fallback_reason"], "none")
        self.assertEqual(meta_zero["fallback_reason"], "none")
        self.assertLess(meta_pi["interference_term"], 0)
        self.assertNotAlmostEqual(pred_pi, pred_zero, places=4)


if __name__ == "__main__":
    unittest.main()
