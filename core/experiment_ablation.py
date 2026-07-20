#!/usr/bin/env python3

"""
Ablation study: does the Born rule add value beyond volatility regime alone?

Compares:
  - 2-model Ensemble (quantum + vol_regime)
  - 1-model (vol_regime only)

If the 2-model performs equally or worse → Born rule is unnecessary.
"""

import math
import statistics
import sys

from data_historical import fetch_klines_range, parse_klines, held_out_split
from backtest_boost import compute_features
from ensemble import (
    _quantum_predict, _volregime_predict, _ma_predict
)
from validation import comprehensive_report, print_report


MODEL_NAMES_2 = ["quantum", "vol_regime"]
MODEL_NAMES_1 = ["vol_regime"]
MODEL_NAMES_QM = ["quantum", "ma"]


class _EnsembleBase:
    """Minimal ensemble runner — no delta boost, pure weight-based fusion."""

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
        if "quantum" in self.model_names:
            preds["quantum"] = _quantum_predict(history)[0]
        if "vol_regime" in self.model_names:
            preds["vol_regime"] = _volregime_predict(history)
        if "ma" in self.model_names:
            preds["ma"] = _ma_predict(history)
        return preds

    def predict_and_update(self, history, actual):
        preds = self._raw_preds(history)
        self._refresh_weights()

        total = 0.0
        for i, name in enumerate(self.model_names):
            total += preds[name] * self.weights[i]
        ensemble = max(0, min(1, total / sum(self.weights)))

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

    ens_qv = _EnsembleBase(MODEL_NAMES_2)  # quantum + vol
    ens_v_only = _EnsembleBase(MODEL_NAMES_1)  # vol only
    ens_qm = _EnsembleBase(MODEL_NAMES_QM)  # quantum + ma
    ens_m_only = _EnsembleBase(["ma"])  # ma only

    errs_qv = []
    errs_v = []
    errs_qm = []
    errs_m = []

    for name, ens, out in [
        ("2-model (with quantum)", ens_qv, errs_qv),
        ("1-model (vol only)",  ens_v_only, errs_v),
        ("quantum+ma", ens_qm, errs_qm),
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
    print(f"  ABLATION STUDY — Held-out {period}")
    print(f"{'='*60}")

    # Compare 2-model vs 1-model
    r = comprehensive_report(errs_v, errs_qv, " [1-model vs 2-model]")
    print_report(r, detail=True)

    mean_v = statistics.mean(errs_v)
    mean_qv = statistics.mean(errs_qv)

    print(f"  1-model (vol only):       err={mean_v:.4f}")
    print(f"  2-model (quantum+vol):    err={mean_qv:.4f}")
    print(f"  2-model - 1-model Δ:      {(mean_qv - mean_v):+.4f}")

    if mean_qv < mean_v:
        print(f"\n  >>> CONCLUSION: quantum+vol < vol alone on held-out.")
        print(f"  >>> Born rule ADDS value (p={r.get('bonferroni_p', '?'):.4f}).")
    else:
        print(f"\n  >>> CONCLUSION: quantum+vol >= vol alone.")
        print(f"  >>> Born rule does NOT add value over vol_regime alone.")

    mean_qm = statistics.mean(errs_qm)
    mean_m = statistics.mean(errs_m)

    print(f"\n{'='*60}")
    print(f"  BORN RULE + MA vs MA ALONE")
    print(f"{'='*60}")
    print(f"  quantum+ma:           err={mean_qm:.4f}")
    print(f"  ma only:              err={mean_m:.4f}")
    print(f"  Δ:                    {(mean_qm - mean_m):+.4f}")
    if mean_qm < mean_m:
        print(f"  >>> Born rule ADDS value over MA alone.")
    else:
        print(f"  >>> Born rule does NOT add value over MA alone.")

    # Build per-model errors from a fresh run (same loop structure)
    m_quantum = []
    m_vol = []
    m_ma = []
    h = []
    for i in range(len(features_list) - 1):
        target = 1.0 if held_out[i + 1]["close"] > held_out[i + 1]["open"] else 0.0
        h.append(features_list[i])
        if len(h) >= window + 1:
            lb = h[-(window + 1):-1]
            q = _quantum_predict(lb)[0]
            v = _volregime_predict(lb)
            ma = _ma_predict(lb)
            m_quantum.append(abs(q - target))
            m_vol.append(abs(v - target))
            m_ma.append(abs(ma - target))

    print(f"\n{'='*60}")
    print(f"  INDIVIDUAL MODEL BREAKDOWN (held-out {period})")
    print(f"{'='*60}")

    for label, errs in [
        ("quantum (born rule)", m_quantum),
        ("vol_regime", m_vol),
        ("ma", m_ma),
    ]:
        print(f"  {label:<25s}  err={statistics.mean(errs):.4f}")

    all_single = [
        ("quantum", m_quantum),
        ("vol_regime", m_vol),
        ("ma", m_ma),
    ]
    best_single = min(all_single, key=lambda x: statistics.mean(x[1]))
    print(f"\n  Best single model:  {best_single[0]} (err={statistics.mean(best_single[1]):.4f})")
    print(f"  1-model (vol only):  {mean_v:.4f}")
    print(f"  2-model (q+vol):     {mean_qv:.4f}")

    return {
        "err_2model": mean_qv,
        "err_1model": mean_v,
        "err_qm": mean_qm,
        "err_m": mean_m,
        "err_quantum": statistics.mean(m_quantum) if m_quantum else None,
        "err_vol": statistics.mean(m_vol) if m_vol else None,
        "err_ma": statistics.mean(m_ma) if m_ma else None,
        "best_single": best_single[0],
        "n_heldout": len(errs_qv),
        "report": r,
    }


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    run_on_candles("60min")
