#!/usr/bin/env python3

"""
One-shot ensemble pipeline (cron-friendly) with forecast / resolve-later.

Each run:
  1. Load state from _live_results/state.json (versioned)
  2. Fetch live data from Huobi
  3. Resolve any pending forecast against the new buy_ratio
  4. Create a new pending forecast from history[-window:]
  5. Persist state and exit

Assumes the cron interval approximates horizon_s (default 3600).
"""

import json
import os
import shutil
import statistics
import sys
import time

from data_fetcher import HuobiData
from ensemble import Ensemble
from baselines import classical_ensemble
from validation import comprehensive_report, print_report
from live_protocol import (
    DEFAULT_WINDOW,
    DEFAULT_HORIZON_S,
    forecast_lookback,
    make_pending,
    pending_due,
    ready_for_forecast,
    resolve_buy_ratio,
)

STATE_PATH = os.path.join(os.path.dirname(__file__), "_live_results", "state.json")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "_live_results")
os.makedirs(RESULTS_DIR, exist_ok=True)

WINDOW = DEFAULT_WINDOW
HORIZON_S = DEFAULT_HORIZON_S
STATE_VERSION = 2


def _atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _default_state():
    return {
        "version": STATE_VERSION,
        "history": [],
        "results": [],
        "step": 0,
        "performance": {name: [] for name in Ensemble.MODEL_NAMES},
        "pending": None,
        "horizon_s": HORIZON_S,
    }


def _backup_state(path):
    bak = path + f".bak.v1.{int(time.time())}"
    shutil.copy2(path, bak)
    print(f"  Backed up old state to {bak}")
    return bak


def _migrate_performance(perf):
    """Keep only current 2-model ensemble keys."""
    if not isinstance(perf, dict):
        return {name: [] for name in Ensemble.MODEL_NAMES}
    return {
        name: list(perf.get(name, []))[-80:]
        for name in Ensemble.MODEL_NAMES
    }


def _load_state():
    if not os.path.exists(STATE_PATH):
        return _default_state()
    with open(STATE_PATH) as f:
        state = json.load(f)
    ver = state.get("version", 1)
    if ver < STATE_VERSION:
        _backup_state(STATE_PATH)
        print(f"  WARNING: state.json version {ver} < {STATE_VERSION} — resetting after backup")
        return _default_state()
    state.setdefault("pending", None)
    state.setdefault("horizon_s", HORIZON_S)
    state["performance"] = _migrate_performance(state.get("performance"))
    state["version"] = STATE_VERSION
    return state


def _save_state(state):
    state["version"] = STATE_VERSION
    _atomic_write(STATE_PATH, state)


def _save_results(results):
    path = os.path.join(RESULTS_DIR, "results_ensemble.json")
    _atomic_write(path, results)


def _restore_ensemble(ens, state):
    perf = _migrate_performance(state.get("performance"))
    for name in ens.MODEL_NAMES:
        ens.performance[name] = list(perf.get(name, []))
    ens._refresh_weights()


def _pct_improvement(c_mean, e_mean):
    if not c_mean:
        return 0.0
    return (c_mean - e_mean) / c_mean * 100


def run():
    state = _load_state()
    history = state["history"]
    results = state["results"]
    step = state["step"]
    horizon_s = float(state.get("horizon_s", HORIZON_S))
    pending = state.get("pending")

    hd = HuobiData()
    features = hd.fetch_features("btcusdt")
    if features is None:
        print("NO DATA from Huobi")
        return

    step += 1
    now_ms = int(features.get("collected_at_ms") or time.time() * 1000)
    history.append(features)
    actual = features["buy_ratio"]

    meta_str = f"[step {step}] {time.strftime('%H:%M:%S')} p={features['price']:.1f}"

    ens = Ensemble(window=WINDOW)
    _restore_ensemble(ens, state)

    if pending and pending_due(pending, now_ms):
        resolved = resolve_buy_ratio(pending, actual, now_ms)
        # Update ensemble weights using resolved actual
        lookback_for_update = forecast_lookback(history[:-1], WINDOW) or history[-WINDOW:]
        _, w, meta = ens.predict_and_update(lookback_for_update, actual)
        c_err = resolved["classical_error"]
        q_err = resolved["prediction_error"]
        winner = "E" if q_err < c_err else "C" if c_err < q_err else "="
        result = {
            "step": resolved.get("step", step),
            "ts": features.get("timestamp", now_ms),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "price": features["price"],
            "actual": round(actual, 4),
            "classical": round(resolved.get("classical", 0.5), 4),
            "ensemble": round(resolved.get("prediction", 0.5), 4),
            "quantum_raw": round(resolved.get("quantum_raw", resolved.get("prediction", 0.5)), 4),
            "vol_regime_raw": round(resolved.get("vol_regime_raw", 0.5), 4),
            "w_quantum": round(resolved.get("w_quantum", w[0]), 4),
            "w_vol_regime": round(resolved.get("w_vol_regime", w[1]), 4),
            "delta": round(resolved.get("delta", meta.get("delta", 0.0)), 4),
            "confidence": round(resolved.get("confidence", meta.get("confidence", 0.0)), 4),
            "winner": winner,
            "status": "resolved",
        }
        results.append(result)
        print(f"{meta_str} RESOLVED act={actual:.3f} c={result['classical']:.3f} "
              f"e={result['ensemble']:.3f} W={winner}")
        pending = None
        _save_results(results)

        if results:
            recent = results[-min(10, len(results)):]
            wins = sum(1 for r in recent if r["winner"] == "E")
            print(f"  --- last {len(recent)}: ensemble wins {wins}/{len(recent)} "
                  f"({wins/len(recent)*100:.0f}%)")
            c_all = [abs(r["classical"] - r["actual"]) for r in results]
            e_all = [abs(r["ensemble"] - r["actual"]) for r in results]
            w_all = sum(1 for r in results if r["winner"] == "E")
            c_mean = statistics.mean(c_all) if c_all else 0.0
            e_mean = statistics.mean(e_all) if e_all else 0.0
            print(f"  --- total {len(results)}: wins {w_all}/{len(results)} "
                  f"({w_all/len(results)*100:.1f}%)  "
                  f"c_err={c_mean:.4f}  e_err={e_mean:.4f}  "
                  f"imprv={_pct_improvement(c_mean, e_mean):+.2f}%")

            if len(results) >= 30:
                print(f"\n  --- Honest live evaluation (block bootstrap, Bonferroni corrected) ---")
                report = comprehensive_report(c_all, e_all, " [live one-shot]")
                print_report(report, detail=True)

    if not ready_for_forecast(history, WINDOW):
        print(f"{meta_str} WARMUP ({len(history)}/{WINDOW})")
        state.update({
            "history": history,
            "results": results,
            "step": step,
            "pending": pending,
            "performance": {name: ens.performance[name] for name in ens.MODEL_NAMES},
            "horizon_s": horizon_s,
        })
        _save_state(state)
        return

    if pending is None:
        lookback = forecast_lookback(history, WINDOW)
        pred_c, _ = classical_ensemble(lookback)
        pred_q, w, meta = ens.predict(lookback)
        pending = make_pending(
            step, horizon_s, now_ms,
            {
                "classical": pred_c,
                "prediction": pred_q,
                "ensemble": pred_q,
                "quantum_raw": meta["predictions"]["quantum"],
                "vol_regime_raw": meta["predictions"]["vol_regime"],
                "w_quantum": w[0],
                "w_vol_regime": w[1],
                "delta": meta["delta"],
                "confidence": meta["confidence"],
            },
        )
        print(f"{meta_str} PENDING c={pred_c:.3f} e={pred_q:.3f} "
              f"δ={meta['delta']:.2f} w={w[0]:.2f}/{w[1]:.2f} "
              f"target_in={horizon_s:.0f}s")

    state.update({
        "version": STATE_VERSION,
        "history": history[-500:],
        "results": results,
        "step": step,
        "pending": pending,
        "performance": {name: ens.performance[name] for name in ens.MODEL_NAMES},
        "horizon_s": horizon_s,
    })
    _save_state(state)


if __name__ == "__main__":
    run()
