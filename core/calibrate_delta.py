#!/usr/bin/env python3

"""
Calibrate delta mapping using historical klines.
FIXED: Now uses held-out data for final calibration reporting.
Calibration tuning happens on train/val, reported on held-out.
"""

import math
import statistics
import cmath
import json
import os
import sys

from data_historical import fetch_klines_range, parse_klines, held_out_split


def compute_features_for_window(candles):
    if len(candles) < 10:
        return None
    volatilities = [(k["high"] - k["low"]) / k["close"] for k in candles[-40:]]
    directions = [1 if k["close"] > k["open"] else 0 for k in candles]
    returns = [(k["close"] - k["open"]) / k["open"] for k in candles]
    bodies = [abs(k["close"] - k["open"]) / (k["high"] - k["low"] + 1e-10) for k in candles]
    conv = [d * b for d, b in zip(directions[-20:], bodies[-20:])]

    avg_vol = statistics.mean(volatilities)
    avg_conv = statistics.mean(conv)
    trend = abs(statistics.mean(directions[-10:]) - 0.5) * 2
    avg_return = statistics.mean(returns[-10:])
    vol_of_vol = statistics.stdev(volatilities) if len(volatilities) > 1 else 0
    avg_body = statistics.mean(bodies[-10:])

    return {
        "volatility": round(avg_vol, 6),
        "conviction": round(avg_conv, 4),
        "trend_strength": round(trend, 4),
        "return": round(avg_return, 6),
        "vol_of_vol": round(vol_of_vol, 6),
        "body_ratio": round(avg_body, 4),
    }


def quantum_model_custom(history, delta):
    convs = [h.get("conviction", 0) for h in history]
    if len(convs) < 4:
        return statistics.mean(convs) if convs else 0.5
    mu = statistics.mean(convs)
    var = statistics.variance(convs) if len(convs) > 1 else 0
    if var < 1e-8:
        return mu
    med = statistics.median(convs)
    eps = math.sqrt(var) / 4
    high = [c for c in convs if c > med + eps]
    low = [c for c in convs if c <= med - eps]
    if not high or not low:
        high = [c for c in convs if c > med]
        low = [c for c in convs if c <= med]
    if not high or not low:
        return mu
    p_h = len(high) / len(convs)
    p_l = len(low) / len(convs)
    mu_h = statistics.mean(high)
    mu_l = statistics.mean(low)
    amp_h = math.sqrt(p_h * mu_h)
    amp_l = math.sqrt(p_l * mu_l) * cmath.exp(1j * delta)
    return max(0, min(1, abs(amp_h + amp_l) ** 2))


def calibrate_on_set(candles, window=20, label=""):
    dataset = []
    history = []

    for i in range(len(candles) - 1):
        curr = candles[i]
        target = 1.0 if candles[i + 1]["close"] > candles[i + 1]["open"] else 0.0
        f = compute_features_for_window(candles[:i + 1])
        if f is None:
            continue

        conv = f["conviction"]
        history.append({"conviction": conv})

        if len(history) >= window + 1:
            lookback = history[-(window + 1):-1]
            # Test all three delta candidates, note which is best
            best_delta = 0.0
            best_err = float("inf")
            for delta_candidate in [0.0, math.pi / 2, math.pi]:
                pred = quantum_model_custom(lookback, delta_candidate)
                err = abs(pred - target)
                if err < best_err:
                    best_err = err
                    best_delta = delta_candidate
            dataset.append({
                "features": f,
                "target": target,
                "optimal_delta": best_delta,
                "error": best_err,
            })
    return dataset


def print_calibration(dataset, label=""):
    if not dataset:
        print(f"  No calibration data{label}")
        return

    n = len(dataset)
    delta_0_count = sum(1 for d in dataset if d["optimal_delta"] == 0.0)
    delta_pi2_count = sum(1 for d in dataset if d["optimal_delta"] == math.pi / 2)
    delta_pi_count = sum(1 for d in dataset if d["optimal_delta"] == math.pi)

    print(f"\n  Calibration{label}: {n} windows")
    print(f"    δ=0:   {delta_0_count:4d} ({delta_0_count/n*100:.1f}%)")
    print(f"    δ=π/2: {delta_pi2_count:4d} ({delta_pi2_count/n*100:.1f}%)")
    print(f"    δ=π:   {delta_pi_count:4d} ({delta_pi_count/n*100:.1f}%)")

    # By volatility
    buckets = {
        "low_vol": {"cond": lambda f: f["volatility"] < 0.002, "deltas": []},
        "mid_vol": {"cond": lambda f: 0.002 <= f["volatility"] < 0.005, "deltas": []},
        "high_vol": {"cond": lambda f: f["volatility"] >= 0.005, "deltas": []},
    }
    for d in dataset:
        for name, b in buckets.items():
            if b["cond"](d["features"]):
                b["deltas"].append(d["optimal_delta"])

    print(f"    By volatility:")
    for name, b in buckets.items():
        if not b["deltas"]:
            continue
        n_b = len(b["deltas"])
        d0 = sum(1 for d in b["deltas"] if d == 0.0)
        dp2 = sum(1 for d in b["deltas"] if d == math.pi / 2)
        dp = sum(1 for d in b["deltas"] if d == math.pi)
        majority = max([("0", d0), ("π/2", dp2), ("π", dp)], key=lambda x: x[1])
        print(f"      {name:>10s}: n={n_b:4d}  δ=0:{d0:4d}  δ=π/2:{dp2:4d}  δ=π:{dp:4d}  → majority δ={majority[0]}")


def calibrate(period="60min", window=20):
    raw = fetch_klines_range("btcusdt", period, 2000)
    candles = parse_klines(raw)
    print(f"Loaded {len(candles)} {period} candles")

    train_val, held_out = held_out_split(candles)
    split2 = int(len(train_val) * 0.6)
    train_set = train_val[:split2]
    val_set = train_val[split2:]

    # Calibrate on train+val only
    train_dataset = calibrate_on_set(train_set, window, " [train]")
    val_dataset = calibrate_on_set(val_set, window, " [val]")
    ho_dataset = calibrate_on_set(held_out, window, " [held-out]")

    print_calibration(train_dataset, " [TRAIN]")
    print_calibration(val_dataset, " [VAL]")
    print_calibration(ho_dataset, " [HELD-OUT (informational only)]")

    n_ho = len(ho_dataset)
    if n_ho > 0:
        d0_ho = sum(1 for d in ho_dataset if d["optimal_delta"] == 0.0)
        dp2_ho = sum(1 for d in ho_dataset if d["optimal_delta"] == math.pi / 2)
        dp_ho = sum(1 for d in ho_dataset if d["optimal_delta"] == math.pi)
        print(f"\n  Held-out majority: δ={'0' if d0_ho > dp2_ho and d0_ho > dp_ho else 'π/2' if dp2_ho > dp_ho else 'π'}")
        print(f"  (δ=0: {d0_ho/n_ho*100:.1f}%, δ=π/2: {dp2_ho/n_ho*100:.1f}%, δ=π: {dp_ho/n_ho*100:.1f}%)")
        print(f"\n  NOTE: Held-out calibration is for CROSS-VALIDATION only.")
        print(f"  The delta-mapping rule used in production should be trained")
        print(f"  on the training set and frozen before seeing held-out data.")

    return ho_dataset


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    for period in ["15min", "60min", "1day"]:
        print(f"\n{'=' * 60}")
        print(f"  Calibrating delta for {period}")
        print(f"{'=' * 60}")
        calibrate(period)
