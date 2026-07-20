#!/usr/bin/env python3

"""
One-shot ensemble pipeline.  Each run:
  1. Load state from _live_results/state.json
  2. Fetch live data from Huobi
  3. If enough history, run classical vs quantum ensemble comparison
  4. Print results, save state, exit
"""

import json
import os
import statistics
import sys
import time

from data_fetcher import HuobiData
from ensemble import Ensemble
from baselines import classical_ensemble
from validation import comprehensive_report, print_report

STATE_PATH = os.path.join(os.path.dirname(__file__), "_live_results", "state.json")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "_live_results")
os.makedirs(RESULTS_DIR, exist_ok=True)

WINDOW = 15


def _atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {"history": [], "results": [], "step": 0, "performance": None}


def _save_state(state):
    _atomic_write(STATE_PATH, state)


def _save_results(results):
    path = os.path.join(RESULTS_DIR, f"results_ensemble.json")
    _atomic_write(path, results)


def _restore_ensemble(ens, state):
    if state.get("performance"):
        for name in ens.MODEL_NAMES:
            if name in state["performance"]:
                ens.performance[name] = state["performance"][name]
    ens._refresh_weights()


def run():
    state = _load_state()
    history = state["history"]
    results = state["results"]
    step = state["step"]

    hd = HuobiData()
    features = hd.fetch_features("btcusdt")
    if features is None:
        print("NO DATA from Huobi")
        return

    step += 1
    history.append(features)

    meta_str = f"[step {step}] {time.strftime('%H:%M:%S')} p={features['price']:.1f}"

    if len(history) < WINDOW + 1:
        print(f"{meta_str} WARMUP ({len(history)}/{WINDOW + 1})")
        state.update({"history": history, "results": results, "step": step})
        _save_state(state)
        return

    lookback = history[-(WINDOW + 1):-1]
    actual = features["buy_ratio"]

    pred_c, _ = classical_ensemble(lookback)

    ens = Ensemble(window=WINDOW)
    _restore_ensemble(ens, state)
    pred_q, w, meta = ens.predict_and_update(lookback, actual)

    c_err = abs(pred_c - actual)
    q_err = abs(pred_q - actual)
    winner = "E" if q_err < c_err else "C" if c_err < q_err else "="

    result = {
        "step": step,
        "ts": features.get("timestamp", int(time.time() * 1000)),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "price": features["price"],
        "actual": round(actual, 4),
        "classical": round(pred_c, 4),
        "ensemble": round(pred_q, 4),
                "quantum_raw": round(meta["predictions"]["quantum"], 4),
                "vol_regime_raw": round(meta["predictions"]["vol_regime"], 4),
                "w_quantum": round(w[0], 4),
                "w_vol_regime": round(w[1], 4),
                "delta": round(meta["delta"], 4),
        "confidence": round(meta["confidence"], 4),
        "winner": winner,
    }
    results.append(result)

    print(f"{meta_str} act={actual:.3f} c={pred_c:.3f} e={pred_q:.3f} δ={meta['delta']:.2f} "
          f"w={w[0]:.2f}/{w[1]:.2f} "
          f"W={winner}")

    _save_results(results)

    recent = results[-min(10, len(results)):]
    wins = sum(1 for r in recent if r["winner"] == "E")
    print(f"  --- last {len(recent)}: ensemble wins {wins}/{len(recent)} ({wins/len(recent)*100:.0f}%)")
    c_all = [abs(r["classical"] - r["actual"]) for r in results]
    e_all = [abs(r["ensemble"] - r["actual"]) for r in results]
    w_all = sum(1 for r in results if r["winner"] == "E")
    print(f"  --- total {len(results)}: wins {w_all}/{len(results)} ({w_all/len(results)*100:.1f}%)  "
          f"c_err={statistics.mean(c_all):.4f}  e_err={statistics.mean(e_all):.4f}  "
          f"imprv={(statistics.mean(c_all)-statistics.mean(e_all))/statistics.mean(c_all)*100:+.2f}%")

    if len(results) >= 30:
        print(f"\n  --- Honest live evaluation (block bootstrap, Bonferroni corrected) ---")
        report = comprehensive_report(c_all, e_all, " [live one-shot]")
        print_report(report, detail=True)

    state.update({
        "history": history,
        "results": results,
        "step": step,
        "performance": {name: ens.performance[name] for name in ens.MODEL_NAMES},
    })
    _save_state(state)


if __name__ == "__main__":
    run()
