#!/usr/bin/env python3

"""
Long-running live pipeline: Classical vs Born-rule with resolve-later scoring.

Legacy entry point — prefer pipeline_live_ensemble.py for production evaluation.
Uses shared forecast protocol (history[-window:], score next observation after delay).

Usage:
    python3 pipeline_live_long.py btcusdt 10000 3600 15
    # 10000 steps, 1-hour horizon, 15-point window
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
from live_protocol import (
    forecast_lookback,
    make_pending,
    pending_due,
    ready_for_forecast,
    resolve_buy_ratio,
)

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "_live_results")
os.makedirs(RESULTS_DIR, exist_ok=True)

_running = True


def _handle_signal(sig, frame):
    global _running
    print(f"\n  Signal {sig} received, shutting down gracefully...")
    _running = False


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
    pending = None
    warmup_complete = False

    output_path = os.path.join(RESULTS_DIR, f"{symbol}_live_{int(time.time())}.json")

    print(f"  LONG-RUN LIVE PIPELINE (forecast / resolve-later)")
    print(f"  symbol={symbol}  max_steps={n_steps}  horizon={delay}s  window={window}")
    print(f"  output={output_path}")
    print(f"  PID={os.getpid()}")
    print(f"  Started at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    for i in range(n_steps):
        if not _running:
            break

        features = hd.fetch_features(symbol)
        now_ms = int(time.time() * 1000)
        if features is None:
            print(f"  [{i}] NO DATA — retrying in 60s")
            time.sleep(60)
            continue

        history.append(features)

        if pending and pending_due(pending, now_ms):
            pending = resolve_buy_ratio(pending, features["buy_ratio"], now_ms)
            sig = delta_signals([pending.get("delta") or 0])
            pending.update({
                "ts": features.get("timestamp", now_ms),
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "price": features["price"],
                "symbol": symbol,
                "signal": sig["signal"],
                "alert": sig["alert"],
                "quantum": pending.get("prediction"),
            })
            results.append(pending)
            print(f"  [{i:5d}] {time.strftime('%H:%M:%S')} RESOLVED "
                  f"act={features['buy_ratio']:.3f} "
                  f"c_err={pending['classical_error']:.3f} "
                  f"q_err={pending['prediction_error']:.3f}")
            pending = None

            if len(results) % 10 == 0:
                recent = results[-min(len(results), 50):]
                wins = sum(
                    1 for r in recent
                    if r.get("prediction_error", 1) < r.get("classical_error", 0)
                )
                print(f"         --- last {len(recent)}: quantum wins {wins}/{len(recent)} "
                      f"({wins/len(recent)*100:.0f}%)")
                _atomic_write(output_path, results)

        if ready_for_forecast(history, window) and pending is None:
            if not warmup_complete:
                warmup_complete = True
                print(f"  WARMUP complete — creating forecasts for horizon={delay}s")

            lookback = forecast_lookback(history, window)
            pred_c, _ = classical_ensemble(lookback)
            pred_q, q_meta = born_rule_predict(lookback)
            pending = make_pending(
                i, delay, now_ms,
                {
                    "classical": pred_c,
                    "prediction": pred_q,
                    "quantum": pred_q,
                    "delta": q_meta["delta"],
                    "confidence": q_meta["confidence"],
                    "delta_source": q_meta.get("delta_source", "unknown"),
                    "fallback_reason": q_meta.get("fallback_reason", "unknown"),
                    "classical_part": q_meta.get("classical_part"),
                    "interference_term": q_meta.get("interference_term"),
                    "data_source": q_meta.get("delta_source", "unknown"),
                    "timeframe": f"{int(delay)}s" if delay >= 1 else "stream",
                },
            )
            print(f"  [{i:5d}] {time.strftime('%H:%M:%S')} "
                  f"p={features['price']:.1f} "
                  f"c={pred_c:.3f} "
                  f"q={pred_q:.3f} "
                  f"δ={q_meta['delta']:.2f} PENDING")
        else:
            print(f"  [{i:5d}] {time.strftime('%H:%M:%S')} WARMUP ({len(history)}/{window})")
            time.sleep(5)
            continue

        if delay > 0 and _running:
            time.sleep(delay)

    print(f"\n  Stopped at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Collected {len(results)} resolved comparison steps")

    if results:
        _atomic_write(output_path, results)
        print(f"  Saved to {output_path}")

        c_errs = [r["classical_error"] for r in results]
        q_errs = [r["prediction_error"] for r in results]
        wins = sum(1 for ce, qe in zip(c_errs, q_errs) if qe < ce)
        n = len(results)
        print(f"\n  FINAL: quantum wins {wins}/{n} ({wins/n*100:.1f}%)  "
              f"c_err={statistics.mean(c_errs):.4f}  q_err={statistics.mean(q_errs):.4f}")


if __name__ == "__main__":
    import warnings
    warnings.warn(
        "pipeline_live_long.py is deprecated; use pipeline_live_ensemble.py for production",
        DeprecationWarning,
        stacklevel=1,
    )
    symbol = sys.argv[1] if len(sys.argv) > 1 else "btcusdt"
    n_steps = int(sys.argv[2]) if len(sys.argv) > 2 else 10000
    delay = float(sys.argv[3]) if len(sys.argv) > 3 else 3600.0
    window = int(sys.argv[4]) if len(sys.argv) > 4 else 15
    run(symbol=symbol, n_steps=n_steps, delay=delay, window=window)
