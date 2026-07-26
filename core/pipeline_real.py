#!/usr/bin/env python3

"""
Short live pipeline: Classical vs Born-rule on Huobi with resolve-later scoring.

Demo / smoke test only — for production evaluation use pipeline_live_ensemble.py.

Uses the shared forecast protocol (same as pipeline_live_ensemble):
  lookback = history[-window:], score against the next observation after `delay`.

Usage:
    python3 pipeline_real.py btcusdt 60 1.0
    # 60 steps, 1-second horizon/sample delay
"""

import statistics
import sys
import time

from data_fetcher import HuobiData
from delta_adaptive import delta_signals
from baselines import classical_ensemble
from quantum_core import born_rule_predict
from live_protocol import (
    DEFAULT_WINDOW,
    forecast_lookback,
    make_pending,
    pending_due,
    ready_for_forecast,
    resolve_buy_ratio,
)


def run_live_pipeline(symbol="btcusdt", n_steps=60, window=DEFAULT_WINDOW, delay=1.0):
    hd = HuobiData()
    history = []
    results = []
    pending = None

    print(f"\n  LIVE PIPELINE (forecast): {symbol.upper()}  |  {n_steps} steps  |  horizon={delay}s\n")
    print(f"{'step':>5} {'price':>10} {'buy_ratio':>9} {'classical':>9} {'quantum':>8} {'delta':>7} {'event':>12}")
    print("-" * 72)

    for i in range(n_steps):
        features = hd.fetch_features(symbol)
        now_ms = int(time.time() * 1000)

        if features is None:
            print(f"  {i:4d}  {'--NODATA--':>10}  {'':>9}  {'':>9}  {'':>8}  {'':>7}  {'FAILED':>12}")
            time.sleep(delay)
            continue

        history.append(features)
        actual = features["buy_ratio"]

        if pending and pending_due(pending, now_ms):
            pending = resolve_buy_ratio(pending, actual, now_ms)
            signal = delta_signals([pending.get("delta") or 0])
            pending["signal"] = signal["signal"]
            pending["alert"] = signal["alert"]
            pending["price"] = features["price"]
            results.append(pending)
            c_err = pending["classical_error"]
            q_err = pending["prediction_error"]
            winner = "Q" if q_err < c_err else "C" if c_err < q_err else "="
            alert_mark = " ⚡" if signal["alert"] else ""
            print(f"  {i:4d} {features['price']:8.2f} {actual:10.3f} "
                  f"{pending['classical']:10.3f} {pending['prediction']:8.3f} "
                  f"{pending.get('delta', 0):7.3f} {'RESOLVED':>12} {winner}{alert_mark}")
            pending = None

        if ready_for_forecast(history, window) and pending is None:
            lookback = forecast_lookback(history, window)
            ensemble_pred, _ = classical_ensemble(lookback)
            quantum_pred, meta = born_rule_predict(lookback)
            pending = make_pending(
                i, delay, now_ms,
                {
                    "classical": ensemble_pred,
                    "prediction": quantum_pred,
                    "quantum": quantum_pred,
                    "delta": meta["delta"],
                    "confidence": meta["confidence"],
                    "delta_source": meta.get("delta_source"),
                    "fallback_reason": meta.get("fallback_reason"),
                },
            )
            print(f"  {i:4d} {features['price']:8.2f} {actual:10.3f} "
                  f"{ensemble_pred:10.3f} {quantum_pred:8.3f} "
                  f"{meta['delta']:7.3f} {'PENDING':>12}")
        else:
            print(f"  {i:4d} {features['price']:8.2f} {'WARMUP':>10} {'':>10} {'':>8} {'':>7} {'':>12}")

        time.sleep(delay)

    return results


def print_summary(results):
    if not results:
        print("No resolved results collected.")
        return

    classical_errors = [r["classical_error"] for r in results]
    quantum_errors = [r["prediction_error"] for r in results]

    mean_c = statistics.mean(classical_errors)
    mean_q = statistics.mean(quantum_errors)
    median_c = statistics.median(classical_errors)
    median_q = statistics.median(quantum_errors)

    quantum_wins = sum(1 for ce, qe in zip(classical_errors, quantum_errors) if qe < ce)
    quantum_better_pct = quantum_wins / len(results) * 100

    alerts = sum(1 for r in results if r.get("alert"))
    price_change = results[-1]["price"] - results[0]["price"] if len(results) > 1 else 0

    print("\n" + "=" * 72)
    print("  LIVE PIPELINE - SUMMARY (forecast / resolve-later)")
    print("=" * 72)
    print(f"  Total resolved:  {len(results)}")
    print(f"  Price range:     {results[0]['price']:.2f} -> {results[-1]['price']:.2f}  ({price_change:+.2f})")
    print(f"  Classical error: {mean_c:.4f} (median: {median_c:.4f})")
    print(f"  Quantum error:   {mean_q:.4f} (median: {median_q:.4f})")
    improvement = (mean_c - mean_q) / mean_c * 100 if mean_c > 0 else 0.0
    print(f"  Improvement:     {improvement:+.1f}%")
    print(f"  Quantum wins:    {quantum_wins}/{len(results)} ({quantum_better_pct:.1f}%)")
    print(f"  Alerts raised:   {alerts}")
    print("=" * 72)


def main():
    import warnings
    warnings.warn(
        "pipeline_real.py is a smoke demo; use pipeline_live_ensemble.py for production",
        DeprecationWarning,
        stacklevel=1,
    )
    symbol = sys.argv[1] if len(sys.argv) > 1 else "btcusdt"
    n_steps = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    delay = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0

    results = run_live_pipeline(symbol=symbol, n_steps=n_steps, delay=delay)
    print_summary(results)


if __name__ == "__main__":
    main()
