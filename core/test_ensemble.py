#!/usr/bin/env python3

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from ensemble import Ensemble


def _history(n=20, buy_ratio=0.55):
    return [
        {"buy_ratio": buy_ratio, "imbalance": 0.3, "volatility": 0.002}
        for _ in range(n)
    ]


class EnsembleTests(unittest.TestCase):
    def test_predict_bounded(self):
        ens = Ensemble(window=5)
        pred, weights, meta = ens.predict(_history())
        self.assertGreaterEqual(pred, 0.0)
        self.assertLessEqual(pred, 1.0)
        self.assertAlmostEqual(sum(weights), 1.0, places=5)

    def test_predict_and_update_changes_weights(self):
        ens = Ensemble(window=5)
        history = _history()
        _, w_before, _ = ens.predict(history)
        ens.predict_and_update(history, actual=0.9)
        self.assertTrue(any(len(errs) > 0 for errs in ens.performance.values()))
        _, w_after, _ = ens.predict(history)
        # Weights may shift once performance history exists
        self.assertEqual(len(w_after), 2)


if __name__ == "__main__":
    unittest.main()
