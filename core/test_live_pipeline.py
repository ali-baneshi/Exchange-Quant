#!/usr/bin/env python3

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from data_fetcher import compute_buy_ratio_for_window
from pipeline_live_ensemble import (
    _exit_code_for_stop_reason,
    _has_pending,
    _prediction_record,
    _resolve_prediction,
    _stop_reason,
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
            "predictions": {"quantum": 0.65, "vol_regime": 0.5},
        }
        pred = _prediction_record(
            "btcusdt", 7, 60, "quantum", obs, 0.52, {}, 0.65, meta,
            lookback_observation_ids=[1, 2, 3],
        )
        self.assertEqual(pred["status"], "pending")
        self.assertEqual(pred["target_at_ms"], 160000)
        self.assertEqual(pred["signal"], "long")
        self.assertEqual(pred["quantum_raw"], 0.65)
        self.assertEqual(pred["lookback_observation_ids"], [1, 2, 3])

    def test_resolve_prediction_marks_snapshot_label_ineligible(self):
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
        self.assertEqual(resolved["resolved_label"], "label_unavailable")
        self.assertAlmostEqual(resolved["prediction_error"], 0.05)
        self.assertGreater(resolved["net_return"], 0.0)
        self.assertFalse(resolved["score_eligible"])
        self.assertIn("label_unavailable", resolved["exit_quality_flags"])

    def test_quality_flags_make_prediction_ineligible(self):
        pred = {
            "entry_price": 100.0,
            "entry_spread": 0.0,
            "entry_quality_flags": ["no_trades"],
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

    def test_ensemble_updates_from_original_stored_predictions(self):
        ens = Ensemble(window=3)
        for quantum, vol in ((0.2, 0.8), (0.21, 0.79), (0.22, 0.78), (0.23, 0.77), (0.24, 0.76)):
            ens.update_from_predictions({"quantum": quantum, "vol_regime": vol}, actual=0.25)
        self.assertAlmostEqual(ens.performance["quantum"][-1], abs(0.24 - 0.25))
        self.assertAlmostEqual(ens.performance["vol_regime"][-1], abs(0.76 - 0.25))
        self.assertGreater(ens.weights[0], ens.weights[1])

    def test_max_resolved_counts_eligible_resolutions_not_fetches(self):
        predictions = [
            {"status": "resolved", "score_eligible": True},
            {"status": "resolved", "score_eligible": False},
        ]
        self.assertIsNone(_stop_reason(predictions, 720, 100, 2, None, 0))
        predictions.append({"status": "resolved", "score_eligible": True})
        self.assertEqual(
            _stop_reason(predictions, 721, 101, 2, None, 0),
            "max_resolved",
        )

    def test_late_resolution_is_ineligible(self):
        pred = {
            "target_at_ms": 1000,
            "entry_price": 100.0,
            "entry_spread": 0.0,
            "entry_quality_flags": [],
            "classical": 0.5,
            "prediction": 0.5,
            "signal": "flat",
        }
        obs = {
            "wall_time_ms": 5000,
            "time": "t",
            "price": 100.0,
            "buy_ratio": 0.5,
            "spread": 0.0,
            "quality_flags": [],
        }
        resolved = _resolve_prediction(pred, obs, sample_interval_s=1.0)
        self.assertIn("late_resolution", resolved["exit_quality_flags"])
        self.assertFalse(resolved["score_eligible"])

    def test_resolve_prediction_uses_forward_window_trades(self):
        pred = {
            "created_at_ms": 40000,
            "target_at_ms": 100000,
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
            "buy_ratio": 0.50,
            "buy_ratio_volume": 0.52,
            "spread": 0.001,
            "quality_flags": [],
        }
        trades = [
            {"ts": 30000, "direction": "sell", "amount": 1.0},
            {"ts": 50000, "direction": "buy", "amount": 1.0},
            {"ts": 70000, "direction": "buy", "amount": 1.0},
            {"ts": 90000, "direction": "buy", "amount": 1.0},
            {"ts": 110000, "direction": "sell", "amount": 1.0},
        ]
        resolved = _resolve_prediction(pred, obs, trades=trades, horizon_s=60.0)
        self.assertEqual(resolved["resolved_label"], "forward_window")
        self.assertEqual(resolved["forward_window_start_ms"], 40000)
        self.assertEqual(resolved["forward_window_end_ms"], 100000)
        self.assertAlmostEqual(resolved["resolved_actual"], 1.0)
        self.assertEqual(resolved["forward_window_trade_count"], 3)
        self.assertNotIn("short_forward_window", resolved["exit_quality_flags"])
        self.assertIn("sparse_forward_window", resolved["exit_quality_flags"])
        self.assertTrue(resolved["score_eligible"])

    def test_resolve_uses_created_to_target_window(self):
        pred = {
            "created_at_ms": 1_000_000,
            "target_at_ms": 1_060_000,
            "entry_price": 100.0,
            "entry_spread": 0.0,
            "entry_quality_flags": [],
            "classical": 0.5,
            "prediction": 0.5,
            "signal": "flat",
        }
        obs = {
            "wall_time_ms": 1_065_000,
            "time": "t1",
            "price": 100.0,
            "buy_ratio": 0.9,
            "spread": 0.0,
            "quality_flags": [],
        }
        trades = [
            {"ts": 1_010_000, "direction": "buy", "amount": 1.0},
            {"ts": 1_030_000, "direction": "sell", "amount": 1.0},
            {"ts": 1_050_000, "direction": "buy", "amount": 1.0},
            {"ts": 1_070_000, "direction": "buy", "amount": 1.0},
        ]
        resolved = _resolve_prediction(pred, obs, trades=trades, horizon_s=60.0)
        self.assertEqual(resolved["resolved_label"], "forward_window")
        self.assertAlmostEqual(resolved["resolved_actual"], 2 / 3, places=4)
        self.assertEqual(resolved["forward_window_trade_count"], 3)

    def test_resolve_prediction_flags_short_forward_window(self):
        pred = {
            "created_at_ms": 40000,
            "target_at_ms": 100000,
            "entry_price": 100.0,
            "entry_spread": 0.0,
            "entry_quality_flags": [],
            "classical": 0.5,
            "prediction": 0.5,
            "signal": "flat",
        }
        obs = {
            "wall_time_ms": 160000,
            "time": "t1",
            "price": 100.0,
            "buy_ratio": 0.55,
            "spread": 0.0,
            "quality_flags": [],
        }
        trades = [{"ts": 50000, "direction": "buy", "amount": 1.0}]
        resolved = _resolve_prediction(pred, obs, trades=trades, horizon_s=60.0)
        self.assertEqual(resolved["resolved_label"], "label_unavailable")
        self.assertEqual(resolved["resolved_actual"], 0.55)
        self.assertIn("short_forward_window", resolved["exit_quality_flags"])
        self.assertFalse(resolved["score_eligible"])

    def test_compute_buy_ratio_for_window(self):
        trades = [
            {"ts": 1000, "direction": "buy", "amount": 2.0},
            {"ts": 2000, "direction": "sell", "amount": 1.0},
            {"ts": 3000, "direction": "buy", "amount": 1.0},
        ]
        result, count = compute_buy_ratio_for_window(trades, 1500, 3500, min_trades=2)
        self.assertEqual(count, 2)
        self.assertAlmostEqual(result["buy_ratio"], 0.5)
        self.assertAlmostEqual(result["buy_ratio_volume"], 1.0 / 2.0)

    def test_exit_code_for_stop_reason(self):
        self.assertEqual(_exit_code_for_stop_reason("max_resolved"), 0)
        self.assertEqual(_exit_code_for_stop_reason("max_fetches"), 2)
        self.assertEqual(_exit_code_for_stop_reason("user_stop"), 2)


if __name__ == "__main__":
    unittest.main()
