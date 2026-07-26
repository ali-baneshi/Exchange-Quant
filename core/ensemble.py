#!/usr/bin/env python3

"""
Adaptive ensemble of 2 models: quantum (Born rule) + volatility regime.
Momentum has been removed — it was actively dragging down performance
(err=0.556 vs vol_regime's 0.517 on held-out 60min).

Weights use exp(-relative_gap * K) for aggressive separation.
"""

import math
import statistics
from quantum_core import born_rule_predict
from config import RELATIVE_K


def _quantum_predict(history):
    pred, meta = born_rule_predict(history, skip_volume_bucket=True)
    return pred, meta["delta"]


def _quantum_predict_with_meta(history):
    return born_rule_predict(history, skip_volume_bucket=True)


def _volregime_predict(history):
    if len(history) < 5:
        return 0.5
    vals = [h.get("buy_ratio", h.get("conviction", 0)) for h in history[-10:]]
    vols = [h.get("volatility", 0.001) for h in history[-10:]]
    if not vols or not vals:
        return 0.5
    avg_vol = statistics.mean(vols)
    median_vol = statistics.median(vols) if len(vols) > 1 else avg_vol
    if avg_vol > median_vol * 1.5:
        return statistics.mean(vals[-3:]) if len(vals) >= 3 else vals[-1]
    elif avg_vol < median_vol * 0.5:
        return vals[-1] if vals else 0.5
    else:
        return statistics.mean(vals) if vals else 0.5


def _ma_predict(history, window=10):
    """Simple moving average of conviction over last window entries."""
    if len(history) < 2:
        return 0.5
    vals = [h.get("buy_ratio", h.get("conviction", 0)) for h in history[-window:]]
    return statistics.mean(vals) if vals else 0.5


class Ensemble:
    MODEL_NAMES = ["quantum", "vol_regime"]

    def __init__(self, window=20, perf_memory=80):
        self.window = window
        self.perf_memory = perf_memory
        self.performance = {name: [] for name in self.MODEL_NAMES}
        self.weights = [0.5, 0.5]

    def _refresh_weights(self):
        mean_errs = []
        for name in self.MODEL_NAMES:
            errs = self.performance.get(name, [])
            if len(errs) >= 5:
                recent = errs[-min(30, len(errs)):]
                mean_errs.append(statistics.mean(recent))
            else:
                mean_errs.append(None)

        valid = [(i, e) for i, e in enumerate(mean_errs) if e is not None]
        if not valid:
            n = len(self.MODEL_NAMES)
            self.weights = [1.0 / n] * n
            return

        min_err = min(e for _, e in valid)

        for i in range(len(self.MODEL_NAMES)):
            if mean_errs[i] is not None:
                gap = mean_errs[i] - min_err
                self.weights[i] = math.exp(-gap * RELATIVE_K)
            else:
                self.weights[i] = 0.01

        ws = sum(self.weights)
        if ws > 0:
            self.weights = [w / ws for w in self.weights]

    def _get_raw_predictions(self, history):
        q_pred, q_meta = _quantum_predict_with_meta(history)
        return {
            "quantum": q_pred,
            "vol_regime": _volregime_predict(history),
        }, q_meta

    def predict(self, history):
        raw_preds, q_meta = self._get_raw_predictions(history)
        self._refresh_weights()

        total = sum(raw_preds[n] * self.weights[i] for i, n in enumerate(self.MODEL_NAMES))
        w_sum = sum(self.weights)
        ensemble = total / w_sum if w_sum > 0 else 0.5

        meta = {
            "predictions": raw_preds,
            "weights": self.weights[:],
            "delta": q_meta["delta"],
            "confidence": q_meta["confidence"],
            "delta_source": q_meta["delta_source"],
            "fallback_reason": q_meta["fallback_reason"],
            "classical_part": q_meta["classical_part"],
            "interference_term": q_meta["interference_term"],
            "quantum_meta": q_meta,
        }
        return max(0, min(1, ensemble)), self.weights[:], meta

    def update(self, history, actual):
        raw_preds, _ = self._get_raw_predictions(history)
        self.update_from_predictions(raw_preds, actual)

    def update_from_predictions(self, raw_predictions, actual):
        """Update performance from predictions captured at forecast creation."""
        for name in self.MODEL_NAMES:
            if name not in raw_predictions:
                raise ValueError(f"Missing stored prediction for model {name!r}")
            err = abs(float(raw_predictions[name]) - float(actual))
            self.performance[name].append(err)
            if len(self.performance[name]) > self.perf_memory:
                self.performance[name] = self.performance[name][-self.perf_memory:]

        self._refresh_weights()

    def predict_and_update(self, history, actual=None):
        pred, weights, meta = self.predict(history)
        if actual is not None and len(history) >= self.window:
            self.update(history, actual)
        return pred, weights, meta


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(line_buffering=True)

    demo = [{"buy_ratio": 0.55, "imbalance": 0.3, "volatility": 0.002}] * 25
    demo += [{"buy_ratio": 0.48, "imbalance": -0.2, "volatility": 0.008}] * 25

    ens = Ensemble(window=10)
    for i in range(10, len(demo)):
        target = demo[i]["buy_ratio"]
        pred, w, meta = ens.predict_and_update(demo[:i], target)
        delta_str = f" δ={meta['delta']:.2f}" if meta['delta'] is not None else ""
        print(f"step {i:2d} pred={pred:.3f} actual={target:.3f}  "
              f"w_q={w[0]:.2f} w_v={w[1]:.2f}  "
              f"q={meta['predictions']['quantum']:.3f} "
              f"v={meta['predictions']['vol_regime']:.3f}"
              f"{delta_str}")
