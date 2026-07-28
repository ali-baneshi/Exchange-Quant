#!/usr/bin/env python3

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from analyze_live_results import (
    _dedupe_predictions,
    _is_result_document,
    _normalize_results,
    analyze,
    discover_paths,
    should_include_path,
)
from argparse import Namespace
from config import (
    ACQUISITION_POLICY_VERSION,
    DATA_POLICY_VERSION,
    LIVE_IMPLEMENTATION_REVISION,
    LIVE_MODEL_VERSION,
)


V3_FIXTURE = {
    "schema_version": 5,
    "run_id": "btcusdt-quantum-test",
    "symbol": "btcusdt",
    "mode": "quantum",
    "horizon_s": 60,
    "observations": [{"buy_ratio": 0.5}],
    "predictions": [
        {
            "status": "resolved",
            "mode": "quantum",
            "prediction": 0.6,
            "classical": 0.4,
            "resolved_actual": 0.55,
            "classical_error": 0.15,
            "prediction_error": 0.05,
            "score_eligible": True,
            "resolved_label": "forward_window",
            "label_capture_complete": True,
            "delta": 1.0,
            "delta_source": "orderbook",
            "fallback_reason": "none",
            "created_time": "t0",
            "resolved_time": "t1",
            "entry_price": 100.0,
            "exit_price": 101.0,
            "signal": "long",
            "net_return": 0.001,
        },
        {
            "status": "resolved",
            "mode": "quantum",
            "prediction": 0.5,
            "classical": 0.45,
            "resolved_actual": 0.48,
            "classical_error": 0.03,
            "prediction_error": 0.02,
            "score_eligible": True,
            "resolved_label": "forward_window",
            "label_capture_complete": True,
            "delta": 0.8,
            "delta_source": "orderbook",
            "fallback_reason": "none",
            "created_time": "t2",
            "resolved_time": "t3",
            "entry_price": 101.0,
            "exit_price": 100.5,
            "signal": "no_trade",
            "net_return": 0.0,
        },
        {
            "status": "resolved",
            "mode": "quantum",
            "prediction": 0.7,
            "classical": 0.5,
            "resolved_actual": 0.52,
            "classical_error": 0.02,
            "prediction_error": 0.18,
            "score_eligible": True,
            "resolved_label": "forward_window",
            "label_capture_complete": True,
            "delta": 1.2,
            "delta_source": "orderbook",
            "fallback_reason": "none",
            "created_time": "t4",
            "resolved_time": "t5",
            "entry_price": 100.5,
            "exit_price": 100.8,
            "signal": "long",
            "net_return": 0.0005,
        },
    ],
}


class AnalyzeLiveResultsTests(unittest.TestCase):
    def test_is_result_document_v5(self):
        self.assertTrue(_is_result_document(V3_FIXTURE))

    def test_normalize_v5_returns_resolved_list(self):
        resolved, meta = _normalize_results(V3_FIXTURE)
        self.assertEqual(len(resolved), 3)
        self.assertEqual(meta["schema_version"], 5)
        self.assertEqual(meta["run_id"], "btcusdt-quantum-test")

    def test_normalize_filters_ineligible_when_present(self):
        data = dict(V3_FIXTURE)
        data["predictions"] = list(V3_FIXTURE["predictions"])
        data["predictions"].append({
            "status": "resolved",
            "mode": "quantum",
            "prediction": 0.5,
            "classical": 0.5,
            "resolved_actual": 0.5,
            "score_eligible": False,
            "resolved_label": "forward_window",
            "label_capture_complete": True,
        })
        resolved, _ = _normalize_results(data)
        self.assertEqual(len(resolved), 3)

    def test_normalize_all_ineligible_returns_empty(self):
        data = dict(V3_FIXTURE)
        data["predictions"] = [
            {
                "status": "resolved",
                "mode": "quantum",
                "prediction": 0.5,
                "classical": 0.5,
                "resolved_actual": 0.5,
            "score_eligible": False,
            "resolved_label": "forward_window",
            "label_capture_complete": True,
            },
            {
                "status": "resolved",
                "mode": "quantum",
                "prediction": 0.6,
                "classical": 0.4,
                "resolved_actual": 0.55,
            "score_eligible": False,
            "resolved_label": "forward_window",
            "label_capture_complete": True,
            },
        ]
        resolved, _ = _normalize_results(data)
        self.assertEqual(resolved, [])

    def test_dedupe_predictions_prefers_resolved(self):
        pending = {"id": "f-1", "status": "pending", "prediction": 0.5}
        resolved = {"id": "f-1", "status": "resolved", "prediction": 0.6}
        out = _dedupe_predictions([pending, resolved])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["status"], "resolved")

    def test_reality_check_uses_live_bonferroni(self):
        from reality_check import paired_loss_test
        c_errs = [0.1] * 720
        q_errs = [0.05] * 720
        rc = paired_loss_test(c_errs, q_errs, n_bootstrap=100, live=True)
        self.assertIn("raw_p_value", rc)
        self.assertIn("corrected_p_value", rc)
        self.assertEqual(rc["n_tests_corrected"], 1)

    def test_analyze_v5_returns_summary(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            summary = analyze(dict(V3_FIXTURE))
        out = buf.getvalue()
        self.assertIn("v5", out)
        self.assertIn("btcusdt-quantum-test", out)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["n"], 3)

    def test_should_include_schema_version_filter(self):
        args = Namespace(schema_version=5, run_id=None, exclude_collector=False)
        ok, _ = should_include_path("x.json", V3_FIXTURE, args)
        self.assertTrue(ok)
        v2 = dict(V3_FIXTURE, schema_version=2)
        ok, reason = should_include_path("x.json", v2, args)
        self.assertFalse(ok)
        self.assertIn("schema", reason)

    def test_v5_rejects_snapshot_or_incomplete_labels(self):
        data = dict(V3_FIXTURE)
        data["predictions"] = [
            dict(
                V3_FIXTURE["predictions"][0],
                resolved_label="label_unavailable",
                label_capture_complete=False,
            )
        ]
        resolved, _ = _normalize_results(data)
        self.assertEqual(resolved, [])

    def test_should_include_run_id_filter(self):
        args = Namespace(schema_version=None, run_id="btcusdt-quantum-test", exclude_collector=False)
        ok, _ = should_include_path("x.json", V3_FIXTURE, args)
        self.assertTrue(ok)
        args.run_id = "other-run"
        ok, _ = should_include_path("x.json", V3_FIXTURE, args)
        self.assertFalse(ok)

    def test_should_exclude_collector_list(self):
        collector = [{"buy_ratio": 0.5, "price": 100.0}]
        args = Namespace(schema_version=None, run_id=None, exclude_collector=True)
        ok, reason = should_include_path("collected_btc.json", collector, args)
        self.assertFalse(ok)
        self.assertEqual(reason, "collector list")

    def test_discover_paths_allows_explicit_archive(self):
        archive = os.path.join(
            os.path.dirname(__file__),
            "_live_results",
            "_archive",
            "pre_v3",
            "btcusdt_quantum_1785028289.json",
        )
        if not os.path.isfile(archive):
            self.skipTest("archive fixture missing")
        args = Namespace(paths=[archive])
        paths = discover_paths(args)
        self.assertEqual(paths, [archive])

    def test_pre_hardening_v6_is_rejected_by_default(self):
        data = dict(V3_FIXTURE, schema_version=6)
        args = Namespace(
            schema_version=6,
            run_id=None,
            exclude_collector=False,
            allow_pre_hardening_v6=False,
        )
        ok, reason = should_include_path("x.json", data, args)
        self.assertFalse(ok)
        self.assertIn("implementation_revision", reason)

    def test_v6r1_row_with_forged_error_is_excluded(self):
        pred = dict(
            V3_FIXTURE["predictions"][0],
            created_at_ms=1_000,
            target_at_ms=61_000,
            resolved_at_ms=62_000,
            forward_window_start_ms=1_000,
            forward_window_end_ms=61_000,
            classical_error=0.999,
            entry_quality_flags=[],
            exit_quality_flags=[],
        )
        data = {
            "schema_version": 6,
            "run_id": "v6r1-test",
            "config_hash": "abc",
            "symbol": "btcusdt",
            "mode": "quantum",
            "horizon_s": 60,
            "model_version": LIVE_MODEL_VERSION,
            "data_policy_version": DATA_POLICY_VERSION,
            "implementation_revision": LIVE_IMPLEMENTATION_REVISION,
            "acquisition_policy_version": ACQUISITION_POLICY_VERSION,
            "experiment_manifest": {
                "model_version": LIVE_MODEL_VERSION,
                "implementation_revision": LIVE_IMPLEMENTATION_REVISION,
                "acquisition_policy_version": ACQUISITION_POLICY_VERSION,
                "label_policy": "captured_trade_window_v1",
                "primary_metric": "paired_mae_difference",
            },
            "predictions": [pred],
            "observations": [],
        }
        resolved, meta = _normalize_results(data)
        self.assertEqual(resolved, [])
        self.assertEqual(
            meta["_validation_exclusions"]["classical_error_mismatch"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
