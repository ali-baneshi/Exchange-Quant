#!/usr/bin/env python3

"""Integration tests for the durable live runner (fake clock + mock provider)."""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))

from pipeline_live_ensemble import RESULTS_DIR, run, _resume_paths
from live_store import LiveRunStore


def _feature_step(step, base_ms=1_000_000, buy_ratio=0.5):
    ts = base_ms + step * 1000
    return {
        "timestamp": ts,
        "collected_at_ms": ts,
        "price": 100.0 + step * 0.1,
        "buy_ratio": buy_ratio,
        "buy_ratio_volume": buy_ratio,
        "imbalance": 0.1,
        "volatility": 0.01,
        "volume_change": 0.0,
        "spread": 0.001,
        "quality_flags": [],
        "ticker_timestamp_ms": ts,
        "depth_timestamp_ms": ts,
    }


class FakeProvider:
    def __init__(self, features):
        self._features = list(features)
        self._index = 0

    def fetch_trades(self, symbol, size=50):
        return [
            {
                "trade_id": str(i),
                "ts": i * 1000,
                "direction": "buy" if i % 2 == 0 else "sell",
                "amount": 1.0,
                "price": 100.0,
            }
            for i in range(min(size, 100))
        ]

    def fetch_features(self, symbol, feature_lookback_s=None):
        if self._index >= len(self._features):
            return dict(self._features[-1])
        value = dict(self._features[self._index])
        self._index += 1
        return value

    def fetch_features_with_trades(self, symbol, trade_size=50, feature_lookback_s=None):
        features = self.fetch_features(symbol, feature_lookback_s=feature_lookback_s)
        return features, self.fetch_trades(symbol, size=trade_size)


class LiveRunnerIntegrationTests(unittest.TestCase):
    def _run_with_clock(self, tmpdir, features, **run_kwargs):
        wall = [0.0]
        mono = [0.0]

        def time_fn():
            return wall[0]

        def monotonic_fn():
            return mono[0]

        def sleep_fn(seconds):
            wall[0] += seconds
            mono[0] += seconds

        provider = FakeProvider(features)
        db_override = os.path.join(tmpdir, run_kwargs.pop("run_id", "test-run") + ".sqlite3")
        json_override = db_override.replace(".sqlite3", ".json")

        with patch.object(
            __import__("pipeline_live_ensemble"),
            "RESULTS_DIR",
            tmpdir,
        ):
            # Patch path construction by using resume_run_id after first partial run
            exit_code = run(
                symbol="btcusdt",
                mode="quantum",
                delay=run_kwargs.get("delay", 10.0),
                window=run_kwargs.get("window", 3),
                sample_interval=run_kwargs.get("sample_interval", 1.0),
                max_resolved=run_kwargs.get("max_resolved"),
                max_fetches=run_kwargs.get("max_fetches"),
                max_runtime_s=run_kwargs.get("max_runtime_s", 0.0),
                resume_run_id=run_kwargs.get("resume_run_id"),
                _time_fn=time_fn,
                _monotonic_fn=monotonic_fn,
                _sleep_fn=sleep_fn,
                _data_provider=provider,
            )
        return exit_code, json_override, db_override

    def test_completes_max_resolved_with_fake_clock(self):
        features = [_feature_step(i, buy_ratio=0.4 + (i % 5) * 0.02) for i in range(80)]
        with tempfile.TemporaryDirectory() as tmp:
            orig_results = RESULTS_DIR
            try:
                import pipeline_live_ensemble as ple
                ple.RESULTS_DIR = tmp
                wall = [0.0]
                mono = [0.0]
                provider = FakeProvider(features)
                code = run(
                    symbol="btcusdt",
                    mode="quantum",
                    delay=10.0,
                    window=3,
                    sample_interval=1.0,
                    max_resolved=2,
                    _time_fn=lambda: wall[0],
                    _monotonic_fn=lambda: mono[0],
                    _sleep_fn=lambda s: (wall.__setitem__(0, wall[0] + s), mono.__setitem__(0, mono[0] + s)),
                    _data_provider=provider,
                )
                self.assertEqual(code, 0)
                json_files = [f for f in os.listdir(tmp) if f.endswith(".json")]
                self.assertTrue(json_files)
                import json
                with open(os.path.join(tmp, json_files[0])) as f:
                    doc = json.load(f)
                resolved = [
                    p for p in doc["predictions"]
                    if p.get("status") == "resolved" and p.get("score_eligible", True)
                ]
                self.assertGreaterEqual(len(resolved), 2)
                for pred in doc["predictions"]:
                    if pred.get("status") == "pending":
                        self.assertIn("lookback_observation_ids", pred)
                        self.assertIn("quantum_raw", pred)
            finally:
                ple.RESULTS_DIR = orig_results

    def test_resume_does_not_duplicate_forecasts(self):
        features = [_feature_step(i, buy_ratio=0.45 + (i % 3) * 0.05) for i in range(80)]
        with tempfile.TemporaryDirectory() as tmp:
            import json
            import pipeline_live_ensemble as ple
            orig_results = ple.RESULTS_DIR
            ple.RESULTS_DIR = tmp
            try:
                wall = [0.0]
                mono = [0.0]
                provider = FakeProvider(features)

                def advance(s):
                    wall[0] += s
                    mono[0] += s

                code1 = run(
                    symbol="btcusdt",
                    mode="quantum",
                    delay=10.0,
                    window=3,
                    sample_interval=1.0,
                    max_fetches=15,
                    _time_fn=lambda: wall[0],
                    _monotonic_fn=lambda: mono[0],
                    _sleep_fn=advance,
                    _data_provider=provider,
                )
                self.assertEqual(code1, 2)

                json_files = [f for f in os.listdir(tmp) if f.endswith(".json")]
                self.assertTrue(json_files)
                json_path = os.path.join(tmp, json_files[0])
                with open(json_path) as f:
                    before = json.load(f)
                run_id = before["run_id"]
                ids_before = [p["id"] for p in before["predictions"]]

                provider2 = FakeProvider(features[15:])
                code2 = run(
                    symbol="btcusdt",
                    mode="quantum",
                    delay=10.0,
                    window=3,
                    sample_interval=1.0,
                    max_resolved=2,
                    resume_run_id=run_id,
                    _time_fn=lambda: wall[0],
                    _monotonic_fn=lambda: mono[0],
                    _sleep_fn=advance,
                    _data_provider=provider2,
                )
                self.assertEqual(code2, 0)
                with open(json_path) as f:
                    after = json.load(f)
                ids_after = [p["id"] for p in after["predictions"]]
                self.assertEqual(len(ids_after), len(set(ids_after)))
                for fid in ids_before:
                    self.assertLessEqual(ids_after.count(fid), 1)
            finally:
                ple.RESULTS_DIR = orig_results

    def test_resume_paths_finds_run_id_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_id = "btcusdt-quantum-12345"
            db_path = os.path.join(tmp, f"{run_id}.sqlite3")
            open(db_path, "w").close()
            import pipeline_live_ensemble as ple
            orig = ple.RESULTS_DIR
            ple.RESULTS_DIR = tmp
            try:
                found_db, found_json = _resume_paths(run_id)
                self.assertEqual(found_db, db_path)
                self.assertTrue(found_json.endswith(".json"))
            finally:
                ple.RESULTS_DIR = orig


if __name__ == "__main__":
    unittest.main()
