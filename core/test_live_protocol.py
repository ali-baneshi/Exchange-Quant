#!/usr/bin/env python3

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from live_protocol import pending_due, resolve_buy_ratio


class LiveProtocolTests(unittest.TestCase):
    def test_pending_due_before_target(self):
        pending = {"status": "pending", "target_at_ms": 2000}
        self.assertFalse(pending_due(pending, 1999))

    def test_pending_due_at_target(self):
        pending = {"status": "pending", "target_at_ms": 2000}
        self.assertTrue(pending_due(pending, 2000))

    def test_pending_due_resolved_record(self):
        pending = {"status": "resolved", "target_at_ms": 1000}
        self.assertFalse(pending_due(pending, 5000))

    def test_pending_due_none(self):
        self.assertFalse(pending_due(None, 1000))

    def test_resolve_buy_ratio_sets_errors(self):
        pending = {"prediction": 0.6, "classical": 0.4, "status": "pending"}
        resolved = resolve_buy_ratio(pending, 0.55, 3000)
        self.assertEqual(resolved["status"], "resolved")
        self.assertAlmostEqual(resolved["prediction_error"], 0.05)
        self.assertAlmostEqual(resolved["classical_error"], 0.15)


if __name__ == "__main__":
    unittest.main()
