#!/usr/bin/env python3

"""
Long-running live pipeline: Classical vs Born-rule comparison on streaming Huobi data.

Fetches live order-book features, runs both classical and quantum models,
and logs results.  Designed for extended (multi-day/week) unsupervised runs.

Usage:
    python3 pipeline_live_long.py btcusdt 10000 3600 15
    # 10000 steps, 1-hour delay, 15-point window
"""

import json
import statistics
import signal
import sys
import time
import os

from data_fetcher import HuobiData
from delta_adaptive import delta_signals
from baselines import classical_ensemble
from quantum_core import born_rule_predict

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "_live_results")
os.makedirs(RESULTS_DIR, exist_ok=True)

_running = True


def _handle_signal(sig, frame):
    global _running
    print(f"\n  Signal {sig} received, shutting down gracefully...")
    _running = False


def quantum_model(history):
    pred, meta = born_rule_predict(history, variance_floor=1e-6)
    return pred, meta


def _atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def run(symbol="btcusdt", n_steps=10000, delay=3600.0, window=15):
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    hd = HuobiData()
    history = []
    results = []
    warmup_complete = False

    output_path = os.path.join(RESULTS_DIR, f"{symbol}_live_{int(time.time())}.json")

    print(f"  LONG-RUN LIVE PIPELINE")
    print(f"  symbol={symbol}  max_steps={n_steps}  delay={delay}s  window={window}")
    print(f"  output={output_path}")
    print(f"  PID={os.getpid()}")
    print(f"  Started at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    for i in range(n_steps):
        if not _running:
            break

        features = hd.fetch_features(symbol)
        if features is None:
            print(f"  [{i}] NO DATA — retrying in 60s")
            time.sleep(60)
            continue

        history.append(features)

        if len(history) >= window + 1:
            if not warmup_complete:
                warmup_complete = True
                print(f"  WARMUP complete — entering hourly comparison phase")

            lookback = history[-(window + 1):-1]
            actual = history[-1]["buy_ratio"]

            pred_c, _ = classical_ensemble(lookback)
            pred_q, q_meta = quantum_model(lookback)
            delta = q_meta["delta"]
            conf = q_meta["confidence"]
            sig = delta_signals([delta] if delta else [0])

            result = {
                "step": i,
                "ts": features.get("timestamp", int(time.time() * 1000)),
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "price": features["price"],
                "symbol": symbol,
                "timeframe": f"{int(delay)}s" if delay >= 1 else "stream",
                "data_source": q_meta.get("delta_source", "unknown"),
                "actual": actual,
                "classical": pred_c,
                "quantum": pred_q,
                "delta": delta,
                "delta_source": q_meta.get("delta_source", "unknown"),
                "fallback_reason": q_meta.get("fallback_reason", "unknown"),
                "classical_part": q_meta.get("classical_part"),
                "interference_term": q_meta.get("interference_term"),
                "confidence": conf,
                "signal": sig["signal"],
                "alert": sig["alert"],
            }
            results.append(result)

            c_err = abs(pred_c - actual)
            q_err = abs(pred_q - actual)

            print(f"  [{i:5d}] {time.strftime('%H:%M:%S')} "
                  f"p={features['price']:.1f} "
                  f"act={actual:.3f} "
                  f"c={pred_c:.3f} "
                  f"q={pred_q:.3f} "
                  f"δ={delta:.2f} "
                  f"{'⚡' if sig['alert'] else ' '}")

            if len(results) % 10 == 0:
                recent = results[-min(len(results), 50):]
                wins = sum(1 for r in recent if abs(r["quantum"] - r["actual"]) < abs(r["classical"] - r["actual"]))
                print(f"         --- last {len(recent)}: quantum wins {wins}/{len(recent)} ({wins/len(recent)*100:.0f}%)")
                _atomic_write(output_path, results)

            if delay > 0 and _running:
                time.sleep(delay)
        else:
            print(f"  [{i:5d}] {time.strftime('%H:%M:%S')} WARMUP ({len(history)}/{window + 1})")
            time.sleep(5)

    print(f"\n  Stopped at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Collected {len(results)} comparison steps")

    if results:
        _atomic_write(output_path, results)
        print(f"  Saved to {output_path}")

        c_errs = [abs(r["classical"] - r["actual"]) for r in results]
        q_errs = [abs(r["quantum"] - r["actual"]) for r in results]
        wins = sum(1 for ce, qe in zip(c_errs, q_errs) if qe < ce)
        n = len(results)
        print(f"\n  FINAL: quantum wins {wins}/{n} ({wins/n*100:.1f}%)  "
              f"c_err={statistics.mean(c_errs):.4f}  q_err={statistics.mean(q_errs):.4f}")


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "btcusdt"
    n_steps = int(sys.argv[2]) if len(sys.argv) > 2 else 10000
    delay = float(sys.argv[3]) if len(sys.argv) > 3 else 3600.0
    run(symbol=symbol, n_steps=n_steps, delay=delay)
