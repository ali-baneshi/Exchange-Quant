#!/usr/bin/env python3

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from pipeline_live_ensemble import (
    _has_pending,
    _prediction_record,
    _resolve_prediction,
)
from ensemble import Ensemble


class LivePipelineTests(unittest.TestCase):
    def test_prediction_record_starts_pending_with_future_target(self):
        obs = {
            "wall_time_ms": 100000,
            "time": "t0",
            "price": 100.0,
            "buy_ratio": 0.55,
            "buy_ratio_volume": 0.60,
            "spread": 0.001,
            "quality_flags": [],
        }
        meta = {
            "delta": 1.2,
            "delta_source": "orderbook",
            "fallback_reason": "none",
            "classical_part": 0.5,
            "interference_term": 0.05,
            "confidence": 0.3,
        }
        pred = _prediction_record("btcusdt", 7, 60, "quantum", obs, 0.52, {}, 0.65, meta)
        self.assertEqual(pred["status"], "pending")
        self.assertEqual(pred["target_at_ms"], 160000)
        self.assertEqual(pred["signal"], "long")

    def test_resolve_prediction_uses_future_observation(self):
        pred = {
            "entry_price": 100.0,
            "entry_spread": 0.001,
            "entry_quality_flags": [],
            "classical": 0.45,
            "prediction": 0.65,
            "signal": "long",
        }
        obs = {
            "wall_time_ms": 160000,
            "time": "t1",
            "price": 101.0,
            "buy_ratio": 0.70,
            "buy_ratio_volume": 0.72,
            "spread": 0.001,
            "quality_flags": [],
        }
        resolved = _resolve_prediction(pred, obs)
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["resolved_actual"], 0.70)
        self.assertAlmostEqual(resolved["prediction_error"], 0.05)
        self.assertGreater(resolved["net_return"], 0.0)
        self.assertTrue(resolved["score_eligible"])

    def test_quality_flags_make_prediction_ineligible(self):
        pred = {
            "entry_price": 100.0,
            "entry_spread": 0.0,
            "entry_quality_flags": ["stale_trades"],
            "classical": 0.5,
            "prediction": 0.5,
            "signal": "flat",
        }
        obs = {"wall_time_ms": 1, "time": "t", "price": 100.0, "buy_ratio": 0.5, "spread": 0.0, "quality_flags": []}
        self.assertFalse(_resolve_prediction(pred, obs)["score_eligible"])

    def test_has_pending(self):
        preds = [{"status": "pending"}, {"status": "resolved"}]
        self.assertTrue(_has_pending(preds))
        self.assertFalse(_has_pending([{"status": "resolved"}]))

    def test_ensemble_update_on_resolve(self):
        ens = Ensemble(window=3)
        history = [
            {"buy_ratio": 0.4, "imbalance": 0.2, "volatility": 0.002},
            {"buy_ratio": 0.6, "imbalance": 0.3, "volatility": 0.002},
            {"buy_ratio": 0.5, "imbalance": 0.1, "volatility": 0.002},
        ]
        _, w0, _ = ens.predict(history)
        ens.predict_and_update(history, actual=0.55)
        _, w1, _ = ens.predict(history)
        self.assertTrue(any(len(e) > 0 for e in ens.performance.values()))


if __name__ == "__main__":
    unittest.main()
