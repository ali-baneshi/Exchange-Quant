#!/usr/bin/env python3

"""Regression tests: imports, deprecate stubs, live protocol."""

import importlib
import os
import subprocess
import sys
import unittest

CORE = os.path.dirname(os.path.abspath(__file__))


class TestImports(unittest.TestCase):
    def test_validation_report_imports(self):
        # Must not ImportError after Born-on-klines removal
        mod = importlib.import_module("validation_report")
        self.assertTrue(hasattr(mod, "classical_splits"))
        self.assertTrue(hasattr(mod, "live_born_status"))
        self.assertFalse(hasattr(mod, "qm_klines"))

    def test_backtest_classical_only(self):
        import backtest
        self.assertTrue(hasattr(backtest, "classical_ensemble_klines"))
        self.assertTrue(hasattr(backtest, "run_backtest"))
        self.assertFalse(hasattr(backtest, "quantum_model_klines"))

    def test_features_shared(self):
        from features import compute_features
        f = compute_features(
            {"ts": 1, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "vol": 10, "amount": 5, "count": 2},
            [],
        )
        self.assertIn("conviction", f)
        self.assertIn("buy_ratio", f)


class TestDeprecateStubs(unittest.TestCase):
    def _run_stub(self, name):
        path = os.path.join(CORE, name)
        proc = subprocess.run(
            [sys.executable, path],
            capture_output=True, text=True, cwd=CORE,
        )
        return proc

    def test_backtest_boost_exits_1(self):
        proc = self._run_stub("backtest_boost.py")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("DEPRECATED", proc.stdout)

    def test_backtest_ensemble_exits_1(self):
        proc = self._run_stub("backtest_ensemble.py")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("DEPRECATED", proc.stdout)

    def test_calibrate_delta_exits_1(self):
        proc = self._run_stub("calibrate_delta.py")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("DEPRECATED", proc.stdout)

    def test_stubs_do_not_export_removed_apis(self):
        import backtest_boost
        import backtest_ensemble
        import calibrate_delta
        for mod in (backtest_boost, backtest_ensemble, calibrate_delta):
            self.assertFalse(hasattr(mod, "run_split"))
            self.assertFalse(hasattr(mod, "run_backtest"))
            self.assertFalse(hasattr(mod, "quantum_model_klines"))


class TestLiveProtocol(unittest.TestCase):
    def test_forecast_lookback(self):
        from live_protocol import forecast_lookback, ready_for_forecast, make_pending, resolve_buy_ratio

        hist = [{"buy_ratio": i / 20} for i in range(20)]
        self.assertTrue(ready_for_forecast(hist, 15))
        lb = forecast_lookback(hist, 15)
        self.assertEqual(len(lb), 15)
        self.assertEqual(lb[-1]["buy_ratio"], 19 / 20)

        pending = make_pending(1, 60, 1000, {"classical": 0.4, "prediction": 0.6})
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(pending["target_at_ms"], 61000)
        resolved = resolve_buy_ratio(pending, 0.5, 62000)
        self.assertEqual(resolved["status"], "resolved")
        self.assertAlmostEqual(resolved["prediction_error"], 0.1)
        self.assertAlmostEqual(resolved["classical_error"], 0.1)

    def test_quantum_core_delta_override(self):
        from quantum_core import born_rule_predict
        hist = [
            {"buy_ratio": 0.2 + 0.05 * (i % 5), "imbalance": 0.1 * ((-1) ** i), "volatility": 0.01}
            for i in range(20)
        ]
        pred0, meta0 = born_rule_predict(hist, delta_override=0.0)
        pred_pi, meta_pi = born_rule_predict(hist, delta_override=3.1415926535)
        self.assertEqual(meta0["delta_source"], "override")
        self.assertEqual(meta_pi["delta_source"], "override")
        self.assertGreaterEqual(pred0, 0.0)
        self.assertLessEqual(pred0, 1.0)
        # Constructive vs destructive should differ when buckets exist
        if meta0.get("fallback_reason") == "none":
            self.assertNotAlmostEqual(pred0, pred_pi, places=6)


if __name__ == "__main__":
    unittest.main()
