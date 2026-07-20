#!/usr/bin/env python3

"""
Compare ensemble with and without delta boost on historical klines.
Uses walk-forward validation: train/val on first 80%, test on last 20%.
"""

import math
import statistics
import sys

from data_historical import fetch_klines_range, parse_klines, held_out_split
from ensemble import Ensemble
from validation import comprehensive_report, print_report


def compute_features(candle, prev_candles):
    candle_range = candle["high"] - candle["low"]
    body = abs(candle["close"] - candle["open"])
    body_ratio = body / candle_range if candle_range > 0 else 0.0
    direction = 1.0 if candle["close"] > candle["open"] else 0.0
    volatility = candle_range / candle["close"] if candle["close"] else 0.001
    conviction = direction * body_ratio

    features = {
        "conviction": conviction,
        "buy_ratio": conviction,
        "direction": direction,
        "body_ratio": body_ratio,
        "volatility": volatility,
        "imbalance": (direction - 0.5) * body_ratio * 2,
        "close": candle["close"],
        "vol": candle["vol"],
    }

    if prev_candles:
        prev_close = prev_candles[-1]["close"]
        features["return"] = (candle["close"] - prev_close) / prev_close if prev_close else 0.0
        if len(prev_candles) >= 3:
            vols = [c["vol"] for c in prev_candles[-3:]]
            vol_prev = statistics.mean(vols[:-1]) if len(vols) > 1 else vols[0]
            features["volume_change"] = (candle["vol"] - vol_prev) / vol_prev if vol_prev > 0 else 0.0
        else:
            features["volume_change"] = 0.0
    else:
        features["return"] = 0.0
        features["volume_change"] = 0.0

    return features


def run_split(period, candles, split_label, window=15, adaptive=True):
    features_list = []
    for i in range(len(candles)):
        prev = features_list if i > 0 else []
        f = compute_features(candles[i], prev)
        features_list.append(f)

    if adaptive:
        ensemble = Ensemble(window=window)
    else:
        ensemble = Ensemble(window=window)
        # Freeze weights at equal for comparison
        ensemble.weights = [0.5, 0.5]
        original_refresh = ensemble._refresh_weights
        ensemble._refresh_weights = lambda: None

    history = []
    results = []

    for i in range(len(features_list) - 1):
        curr = features_list[i]
        target = 1.0 if candles[i + 1]["close"] > candles[i + 1]["open"] else 0.0
        history.append(curr)

        if len(history) >= window + 1:
            lookback = history[-(window + 1):-1]
            pred, w, meta = ensemble.predict_and_update(lookback, target)
            results.append({
                "step": i,
                "target": target,
                "pred": pred,
                "err": abs(pred - target),
                "weights": w,
                "meta": meta,
            })

    errs = [r["err"] for r in results]
    label = f" [adaptive={adaptive} {split_label}]"
    return errs, label, results


def run(period="60min", window=15):
    raw = fetch_klines_range("btcusdt", period, 2000)
    candles = parse_klines(raw)
    print(f"Loaded {len(candles)} {period} candles")

    train_val, held_out = held_out_split(candles)
    print(f"  Train/val: {len(train_val)}  Held-out: {len(held_out)}")

    # Walk-forward on train/val to tune parameters (currently window, delta thresholds)
    # Phase 1: train on first 60% of train_val, validate on last 40% of train_val
    split2 = int(len(train_val) * 0.6)
    train_set = train_val[:split2]
    val_set = train_val[split2:]

    errs_no_train, lab_no_train, _ = run_split(period, train_set, "train", window=window, adaptive=False)
    errs_boost_train, lab_boost_train, _ = run_split(period, train_set, "train", window=window, adaptive=True)
    errs_no_val, lab_no_val, _ = run_split(period, val_set, "val", window=window, adaptive=False)
    errs_boost_val, lab_boost_val, _ = run_split(period, val_set, "val", window=window, adaptive=True)

    print(f"\n{'='*55}")
    print(f"  TRAIN SET [{period}]")
    print(f"{'='*55}")
    r_no = comprehensive_report(errs_no_train, errs_boost_train, lab_no_train)
    print_report(r_no, detail=True)

    print(f"\n{'='*55}")
    print(f"  VALIDATION SET [{period}]")
    print(f"{'='*55}")
    r_val = comprehensive_report(errs_no_val, errs_boost_val, lab_boost_val)
    print_report(r_val, detail=True)

    # Held-out evaluation: run BOTH boost and no-boost on held-out data
    # NO parameter tuning here — just evaluation
    print(f"\n{'='*55}")
    print(f"  HELD-OUT TEST [{period}] — FINAL HONEST EVALUATION")
    print(f"{'='*55}")
    errs_no_ho, lab_no_ho, results_no = run_split(period, held_out, "heldout", window=window, adaptive=False)
    errs_boost_ho, lab_boost_ho, results_boost = run_split(period, held_out, "heldout", window=window, adaptive=True)

    r_ho = comprehensive_report(errs_no_ho, errs_boost_ho, " [held-out test]")
    print_report(r_ho, detail=True)

    # Show delta distribution on held-out
    deltas = [r["meta"]["delta"] for r in results_boost if r["meta"]["delta"] is not None]
    if deltas:
        at_zero = sum(1 for d in deltas if abs(d) < 0.01)
        at_pi = sum(1 for d in deltas if abs(d - math.pi) < 0.01)
        at_pi2 = sum(1 for d in deltas if abs(d - math.pi / 2) < 0.01)
        other = len(deltas) - at_zero - at_pi - at_pi2
        print(f"  Held-out delta dist: δ=0:{at_zero} δ=π:{at_pi} δ=π/2:{at_pi2} other:{other}")

    avg_w = [statistics.mean([r["weights"][i] for r in results_boost]) for i in range(2)]
    print(f"  Held-out avg weights (adaptive): q={avg_w[0]:.3f} v={avg_w[1]:.3f}")

    return r_ho


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    for period in ["60min"]:
        print(f"\n{'#'*55}")
        print(f"#  {period}")
        print(f"{'#'*55}")
        run(period)
