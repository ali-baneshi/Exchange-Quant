#!/usr/bin/env python3

"""
Adaptive ensemble (alternative weight strategy).

Implements the 2-model ensemble (quantum + vol_regime) with
relative-gap-based weighting (matching ensemble.py strategy).
Used by backtest_ensemble.py for ensemble backtests.

Usage:
    from ensemble_adaptive import AdaptiveEnsemble
    ens = AdaptiveEnsemble(mode="buyratio", n_models=2, window=20)
    pred, preds, weights = ens.predict_and_update(history, target)
"""

import math
import statistics
import sys
from quantum_core import born_rule_predict

RELATIVE_K = 30.0


def _quantum_buyratio(history):
    pred, meta = born_rule_predict(history)
    return pred, meta["delta"]


def _volatility_regime_conviction(history):
    if len(history) < 5:
        return 0.5
    vols = [h.get("volatility", 0.001) for h in history[-10:]]
    vals = [h.get("buy_ratio", h.get("conviction", 0)) for h in history[-10:]]
    avg_vol = statistics.mean(vols)
    median_vol = statistics.median(vols) if len(vols) > 1 else avg_vol
    if avg_vol > median_vol * 1.5:
        return statistics.mean(vals[-3:]) if vals else 0.5
    elif avg_vol < median_vol * 0.5:
        return vals[-1] if vals else 0.5
    else:
        return statistics.mean(vals) if vals else 0.5


class AdaptiveEnsemble:
    def __init__(self, mode="buyratio", n_models=2, window=20):
        self.mode = mode
        self.n_models = n_models
        self.window = window
        self.model_names = ["quantum", "vol_regime"]
        self.weights = [0.5, 0.5]
        self.performance = {name: [] for name in self.model_names}

    def predict(self, history):
        preds = {}
        confs = {}
        preds["quantum"], confs["quantum"] = _quantum_buyratio(history)
        preds["vol_regime"], confs["vol_regime"] = _volatility_regime_conviction(history), 0.3

        total = 0.0
        weight_sum = 0.0
        for i, name in enumerate(self.model_names):
            w = self.weights[i]
            total += preds[name] * w
            weight_sum += w

        ensemble = total / weight_sum if weight_sum > 0 else 0.5
        return max(0, min(1, ensemble)), preds, self.weights[:]

    def update_weights(self, history, target):
        preds = {}
        preds["quantum"], _ = _quantum_buyratio(history)
        preds["vol_regime"], _ = _volatility_regime_conviction(history), 0.3

        for name in self.model_names:
            err = abs(preds[name] - target)
            self.performance[name].append(err)
            if len(self.performance[name]) > 80:
                self.performance[name] = self.performance[name][-80:]

        mean_errs = []
        for name in self.model_names:
            errs = self.performance.get(name, [])
            if len(errs) >= 5:
                recent = errs[-min(30, len(errs)):]
                mean_errs.append(statistics.mean(recent))
            else:
                mean_errs.append(None)

        valid = [(i, e) for i, e in enumerate(mean_errs) if e is not None]
        if not valid:
            n = len(self.model_names)
            self.weights = [1.0 / n] * n
            return

        min_err = min(e for _, e in valid)

        for i in range(len(self.model_names)):
            if mean_errs[i] is not None:
                gap = mean_errs[i] - min_err
                self.weights[i] = math.exp(-gap * 10.0)
            else:
                self.weights[i] = 0.01

        w_sum = sum(self.weights)
        if w_sum > 0:
            self.weights = [w / w_sum for w in self.weights]

    def predict_and_update(self, history, target=None):
        ensemble, preds, weights = self.predict(history)
        if target is not None and len(history) >= self.window:
            self.update_weights(history, target)
        return ensemble, preds, weights


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)

    demo = [{"buy_ratio": 0.55, "imbalance": 0.3, "volatility": 0.002}] * 25
    demo += [{"buy_ratio": 0.48, "imbalance": -0.2, "volatility": 0.008}] * 25
    ensemble = AdaptiveEnsemble(mode="buyratio", window=10)
    for i in range(10, len(demo)):
        target = demo[i]["buy_ratio"]
        pred, preds, weights = ensemble.predict_and_update(demo[:i], target)
        print(f"step {i:2d} target={target:.3f} pred={pred:.3f}  "
              f"w={[f'{w:.2f}' for w in weights]}  "
              f"q={preds['quantum']:.3f} v={preds['vol_regime']:.3f}")
