#!/usr/bin/env python3

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from analyze_live_results import _is_result_document, _normalize_results, analyze


V3_FIXTURE = {
    "schema_version": 3,
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
    def test_is_result_document_v3(self):
        self.assertTrue(_is_result_document(V3_FIXTURE))

    def test_normalize_v3_returns_resolved_list(self):
        resolved, meta = _normalize_results(V3_FIXTURE)
        self.assertEqual(len(resolved), 3)
        self.assertEqual(meta["schema_version"], 3)
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
        })
        resolved, _ = _normalize_results(data)
        self.assertEqual(len(resolved), 3)

    def test_analyze_v3_returns_summary(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            summary = analyze(dict(V3_FIXTURE))
        out = buf.getvalue()
        self.assertIn("v3", out)
        self.assertIn("btcusdt-quantum-test", out)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["n"], 3)


if __name__ == "__main__":
    unittest.main()
