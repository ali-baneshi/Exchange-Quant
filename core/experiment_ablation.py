#!/usr/bin/env python3

"""
Ablation study: classical models on kline data (vol_regime vs MA).

Born rule has been removed from kline-based evaluation (2026-07-23).
It requires order-book imbalance data which is not available in klines.

Compares:
  - vol_regime + MA ensemble
  - vol_regime alone
  - MA alone
"""

import math
import statistics
import sys

from data_historical import fetch_klines_range, parse_klines, held_out_split
from ensemble import _volregime_predict, _ma_predict
from features import compute_features
from validation import comprehensive_report, print_report


class _EnsembleBase:
    """Minimal ensemble runner — pure weight-based fusion."""

    def __init__(self, model_names):
        self.model_names = model_names
        self.n = len(model_names)
        self.performance = {name: [] for name in model_names}
        self.weights = [1.0 / self.n] * self.n

    def _refresh_weights(self):
        for i, name in enumerate(self.model_names):
            errs = self.performance.get(name, [])
            if len(errs) >= 5:
                recent = errs[-min(20, len(errs)):]
                mean_err = statistics.mean(recent)
                self.weights[i] = math.exp(-mean_err * 4)
            else:
                self.weights[i] = 1.0 / self.n
        ws = sum(self.weights)
        if ws > 0:
            self.weights = [w / ws for w in self.weights]

    def _raw_preds(self, history):
        preds = {}
        if "vol_regime" in self.model_names:
            preds["vol_regime"] = _volregime_predict(history)
        if "ma" in self.model_names:
            preds["ma"] = _ma_predict(history)
        return preds

    def predict_and_update(self, history, actual):
        preds = self._raw_preds(history)
        self._refresh_weights()

        total = sum(preds[name] * self.weights[i] for i, name in enumerate(self.model_names))
        ensemble = max(0, min(1, total))

        for name in self.model_names:
            err = abs(preds[name] - actual)
            self.performance[name].append(err)
            if len(self.performance[name]) > 50:
                self.performance[name] = self.performance[name][-50:]

        return ensemble


def run_on_candles(period="60min", window=15):
    raw = fetch_klines_range("btcusdt", period, 2000)
    candles = parse_klines(raw)
    _, held_out = held_out_split(candles)
    print(f"Loaded {len(candles)} {period} candles  |  Held-out: {len(held_out)}")

    features_list = []
    for i in range(len(held_out)):
        prev = features_list if i > 0 else []
        f = compute_features(held_out[i], prev)
        features_list.append(f)

    ens_vm = _EnsembleBase(["vol_regime", "ma"])
    ens_v_only = _EnsembleBase(["vol_regime"])
    ens_m_only = _EnsembleBase(["ma"])

    errs_vm = []
    errs_v = []
    errs_m = []

    for name, ens, out in [
        ("vol+ma ensemble", ens_vm, errs_vm),
        ("vol_regime only", ens_v_only, errs_v),
        ("ma only", ens_m_only, errs_m),
    ]:
        history = []
        for i in range(len(features_list) - 1):
            curr = features_list[i]
            target = 1.0 if held_out[i + 1]["close"] > held_out[i + 1]["open"] else 0.0
            history.append(curr)
            if len(history) >= window + 1:
                lookback = history[-(window + 1):-1]
                pred = ens.predict_and_update(lookback, target)
                out.append(abs(pred - target))

    print(f"\n{'='*60}")
    print(f"  ABLATION STUDY (Classical Only) — Held-out {period}")
    print(f"{'='*60}")

    print(f"\n  NOTE: Born rule removed from kline evaluation (2026-07-23).")
    print(f"  Born rule requires order-book imbalance — not available in klines.\n")

    r = comprehensive_report(errs_v, errs_vm, " [vol vs vol+ma]")
    print_report(r, detail=True)

    mean_v = statistics.mean(errs_v)
    mean_m = statistics.mean(errs_m)
    mean_vm = statistics.mean(errs_vm)

    print(f"  vol_regime:       err={mean_v:.4f}")
    print(f"  ma:               err={mean_m:.4f}")
    print(f"  vol+ma ensemble:  err={mean_vm:.4f}")

    best = min([("vol_regime", mean_v), ("ma", mean_m), ("vol+ma", mean_vm)], key=lambda x: x[1])
    print(f"\n  Best model: {best[0]} (err={best[1]:.4f})")

    return {
        "err_vol": mean_v,
        "err_ma": mean_m,
        "err_ensemble": mean_vm,
        "best_model": best[0],
        "n_heldout": len(errs_v),
        "report": r,
    }


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    run_on_candles("60min")
