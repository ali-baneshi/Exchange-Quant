#!/usr/bin/env python3

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from validation import (
    bonferroni_correct,
    block_bootstrap_pvalue,
    comprehensive_report,
    max_drawdown_from_errors,
    profit_factor,
    sharpe_ratio,
)


class ValidationTests(unittest.TestCase):
    def test_bonferroni_correct(self):
        corrected, sig_005, sig_001 = bonferroni_correct(0.008, 5)
        self.assertAlmostEqual(corrected, 0.04)
        self.assertTrue(sig_005)
        self.assertFalse(sig_001)

    def test_bonferroni_caps_at_one(self):
        corrected, _, _ = bonferroni_correct(0.5, 5)
        self.assertAlmostEqual(corrected, 1.0)

    def test_max_drawdown_empty(self):
        self.assertEqual(max_drawdown_from_errors([]), 0.0)

    def test_max_drawdown_never_positive_peak(self):
        errors = [0.9, 0.9, 0.9]
        mdd = max_drawdown_from_errors(errors)
        self.assertGreaterEqual(mdd, 0.0)

    def test_sharpe_empty_and_single(self):
        self.assertEqual(sharpe_ratio([]), 0.0)
        self.assertEqual(sharpe_ratio([0.1]), 0.0)

    def test_profit_factor_all_wins(self):
        eq = [0.1, 0.2, 0.3]
        ec = [0.2, 0.3, 0.4]
        self.assertEqual(profit_factor(eq, ec), float("inf"))

    def test_block_bootstrap_deterministic(self):
        errors_c = [0.12, 0.08, 0.15, 0.09, 0.11, 0.14, 0.07, 0.10, 0.13, 0.06]
        errors_q = [0.10, 0.07, 0.12, 0.08, 0.09, 0.11, 0.06, 0.08, 0.10, 0.05]
        p1 = block_bootstrap_pvalue(errors_c, errors_q, n_bootstrap=500, seed=42)
        p2 = block_bootstrap_pvalue(errors_c, errors_q, n_bootstrap=500, seed=42)
        self.assertAlmostEqual(p1, p2)
        self.assertGreater(p1, 0.0)
        self.assertLess(p1, 1.0)

    def test_comprehensive_report_fields(self):
        errors_c = [0.2, 0.3, 0.25]
        errors_q = [0.15, 0.28, 0.20]
        report = comprehensive_report(errors_c, errors_q, " [test]")
        self.assertEqual(report["n"], 3)
        self.assertIn("bonferroni_p", report)
        self.assertIn("significant_005", report)


if __name__ == "__main__":
    unittest.main()
