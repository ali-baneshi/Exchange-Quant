#!/usr/bin/env python3

"""
Short live pipeline: Quick comparison of classical vs quantum on Huobi data.

Best for interactive testing — runs a limited number of steps with short delays.

Usage:
    python3 pipeline_real.py btcusdt 60 1.0
    # 60 steps, 1-second delay
"""

import math
import statistics
import cmath
import sys
import time

from data_fetcher import HuobiData
from delta_adaptive import compute_delta, delta_signals
from baselines import classical_ensemble


def quantum_model(history):
    if len(history) < 4:
        return 0.5, 0.0, 0.0

    ratios = [h["buy_ratio"] for h in history]
    mu = statistics.mean(ratios)
    var = statistics.variance(ratios) if len(ratios) > 1 else 0

    if var < 1e-6:
        classical_pred = mu
        delta, conf = compute_delta(history)
        quantum_pred = classical_pred
        return quantum_pred, delta, conf

    median_ratio = statistics.median(ratios)
    eps = math.sqrt(var) / 4
    high_grp = [r for r in ratios if r > median_ratio + eps]
    low_grp  = [r for r in ratios if r <= median_ratio - eps]

    if not high_grp or not low_grp:
        high_grp = [r for r in ratios if r > median_ratio]
        low_grp  = [r for r in ratios if r <= median_ratio]

    if not high_grp or not low_grp:
        return mu, 0.0, 0.0

    p_high = len(high_grp) / len(ratios)
    p_low  = len(low_grp) / len(ratios)
    mu_high = statistics.mean(high_grp)
    mu_low  = statistics.mean(low_grp)

    delta, conf = compute_delta(history)

    amp_h = math.sqrt(p_high * mu_high)
    amp_l = math.sqrt(p_low * mu_low) * cmath.exp(1j * delta)
    quantum_pred = abs(amp_h + amp_l) ** 2

    return quantum_pred, delta, conf


def run_live_pipeline(symbol="btcusdt", n_steps=60, window=15, delay=1.0):
    hd = HuobiData()
    history = []
    results = []

    print(f"\n  LIVE PIPELINE: {symbol.upper()}  |  {n_steps} steps  |  delay={delay}s\n")
    print(f"{'step':>5} {'price':>10} {'buy_ratio':>9} {'classical':>9} {'quantum':>8} {'delta':>7} {'signal':>18}")
    print("-" * 72)

    for i in range(n_steps):
        features = hd.fetch_features(symbol)

        if features is None:
            print(f"  {i:4d}  {'--NODATA--':>10}  {'':>9}  {'':>9}  {'':>8}  {'':>7}  {'FAILED':>18}")
            time.sleep(delay)
            continue

        history.append(features)

        if len(history) >= window + 1:
            lookback = history[-(window + 1):-1]
            actual = history[-1]["buy_ratio"]

            ensemble_pred, _ = classical_ensemble(lookback)

            quantum_pred, delta, conf = quantum_model(lookback)

            signal = delta_signals([delta] if delta else [0])

            results.append({
                "step": i,
                "price": features["price"],
                "actual": actual,
                "classical": ensemble_pred,
                "quantum": quantum_pred,
                "delta": delta,
                "confidence": conf,
                "signal": signal["signal"],
                "alert": signal["alert"],
            })

            c_err = abs(ensemble_pred - actual)
            q_err = abs(quantum_pred - actual)
            winner = "Q" if q_err < c_err else "C" if c_err < q_err else "="

            alert_mark = " ⚡" if signal["alert"] else ""
            print(f"  {i:4d} {features['price']:8.2f} {actual:10.3f} {ensemble_pred:10.3f} {quantum_pred:8.3f} {delta:7.3f} {signal['signal']:>18}{alert_mark}")
        else:
            print(f"  {i:4d} {features['price']:8.2f} {'WARMUP':>10} {'':>10} {'':>8} {'':>7}")

        time.sleep(delay)

    return results


def print_summary(results):
    if not results:
        print("No results collected.")
        return

    classical_errors = [abs(r["classical"] - r["actual"]) for r in results]
    quantum_errors = [abs(r["quantum"] - r["actual"]) for r in results]

    mean_c = statistics.mean(classical_errors)
    mean_q = statistics.mean(quantum_errors)
    median_c = statistics.median(classical_errors)
    median_q = statistics.median(quantum_errors)

    quantum_wins = sum(1 for r in results if abs(r["quantum"] - r["actual"]) < abs(r["classical"] - r["actual"]))
    quantum_better_pct = quantum_wins / len(results) * 100

    alerts = sum(1 for r in results if r["alert"])
    price_change = results[-1]["price"] - results[0]["price"] if len(results) > 1 else 0

    print("\n" + "=" * 72)
    print("  LIVE PIPELINE - SUMMARY")
    print("=" * 72)
    print(f"  Total steps:     {len(results)}")
    print(f"  Price range:     {results[0]['price']:.2f} -> {results[-1]['price']:.2f}  ({price_change:+.2f})")
    print(f"  Classical error: {mean_c:.4f} (median: {median_c:.4f})")
    print(f"  Quantum error:   {mean_q:.4f} (median: {median_q:.4f})")
    improvement = (mean_c - mean_q) / mean_c * 100 if mean_c > 0 else 0
    print(f"  Improvement:     {improvement:+.1f}%")
    print(f"  Quantum wins:    {quantum_wins}/{len(results)} ({quantum_better_pct:.1f}%)")
    print(f"  Alerts raised:   {alerts}")
    print("=" * 72)


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "btcusdt"
    n_steps = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    delay = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0

    results = run_live_pipeline(symbol=symbol, n_steps=n_steps, delay=delay)
    print_summary(results)


if __name__ == "__main__":
    main()
