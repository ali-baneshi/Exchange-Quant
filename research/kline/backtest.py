#!/usr/bin/env python3

"""
Backtest: Classical-only evaluation on historical klines.

Born rule has been removed from kline-based evaluation (2026-07-23).
See decision log: Born rule requires order-book imbalance data and
cannot work on kline-only data (all p-values = 1.0 on 5000 candles).

Reports mean absolute error of a classical ensemble against next-candle
binary direction (0/1). This is NOT comparable to live buy_ratio forecasts.

Usage:
    python3 backtest.py
"""

import statistics
import time

from research.kline.data_historical import fetch_klines_range, held_out_split, parse_klines
from research.kline.features import compute_features


def classical_ensemble_klines(history):
    if len(history) < 3:
        return 0.5

    convs = [h["conviction"] for h in history]
    vols = [h["volatility"] for h in history]
    dirs = [h["direction"] for h in history]

    sma = statistics.mean(convs)

    alpha = 0.3
    ema = convs[0]
    for v in convs[1:]:
        ema = alpha * v + (1 - alpha) * ema

    window = min(5, len(convs))
    if window >= 2:
        xs = list(range(window))
        ys = convs[-window:]
        n = window
        sx = sum(xs)
        sy = sum(ys)
        sxx = sum(x * x for x in xs)
        sxy = sum(x * y for x, y in zip(xs, ys))
        denom = n * sxx - sx * sx
        slope = (n * sxy - sx * sy) / denom if denom != 0 else 0
        base = statistics.mean(ys)
        momentum = max(0, min(1, base + slope * (window + 1)))
    else:
        momentum = sma

    mean_vol = statistics.mean(vols)
    mean_dir = statistics.mean(dirs)
    vol_reg = 1 / (1 + mean_vol * 100)
    logistic = mean_dir * vol_reg

    preds = [sma, ema, momentum, logistic]
    ensemble = statistics.mean(preds)
    return max(0, min(1, ensemble))


def _mean_or_none(errs):
    return statistics.mean(errs) if errs else None


def run_backtest(candles, window=20):
    """Walk one step ahead; return list of abs errors vs next-candle direction."""
    features_list = []
    for i in range(len(candles)):
        prev = features_list[max(0, i - 5):i] if i > 0 else []
        f = compute_features(candles[i], prev)
        features_list.append(f)

    history = []
    errs = []

    for i in range(len(features_list) - 1):
        curr = features_list[i]
        next_candle = features_list[i + 1]
        target = next_candle["direction"]

        history.append(curr)

        if len(history) >= window + 1:
            lookback = history[-(window + 1):-1]
            pred = classical_ensemble_klines(lookback)
            errs.append(abs(pred - target))

    return errs


def _print_split(name, errs):
    mean_err = _mean_or_none(errs)
    if mean_err is None:
        print(f"  {name}: insufficient data (n=0)")
    else:
        print(f"  {name}: Classical mean error: {mean_err:.4f}  (n={len(errs)})")
    return mean_err


def main():
    print(f"\n{'='*65}")
    print(f"  {'!'*61}")
    print("  ! WARNING: Target is BINARY DIRECTION (0/1), NOT continuous  !")
    print("  ! buy_ratio. Results are NOT directly comparable to live     !")
    print("  ! pipeline (continuous buy_ratio) predictions.              !")
    print(f"  {'!'*61}")
    print(f"{'='*65}\n")

    periods = [("15min", 5000), ("60min", 5000), ("1day", 5000)]
    summary = []

    for period, n in periods:
        print(f"\n{'#' * 65}")
        print(f"#  PERIOD: {period}  ({n} candles)")
        print(f"{'#' * 65}")

        raw = fetch_klines_range("btcusdt", period, n)
        candles = parse_klines(raw)
        print(f"  Loaded {len(candles)} candles")

        train_val, held_out = held_out_split(candles)
        print(f"  Train/val: {len(train_val)}  Held-out: {len(held_out)}")

        split2 = int(len(train_val) * 0.6)
        train_set = train_val[:split2]
        val_set = train_val[split2:]

        t0 = time.time()

        print(f"\n  --- TRAIN ({period}) ---")
        errs_train = run_backtest(train_set)
        _print_split("TRAIN", errs_train)

        print(f"\n  --- VAL ({period}) ---")
        errs_val = run_backtest(val_set)
        _print_split("VAL", errs_val)

        print(f"\n  --- HELD-OUT EVALUATION ({period}) ---")
        print("  WARNING: binary direction target (0/1)")
        errs_ho = run_backtest(held_out)
        mean_ho = _print_split("HELD-OUT", errs_ho)
        summary.append((period, len(errs_ho), mean_ho))

        elapsed = time.time() - t0
        print(f"  Completed in {elapsed:.1f}s")

    print(f"\n{'=' * 65}")
    print("  CROSS-PERIOD HELD-OUT SUMMARY")
    print(f"{'='*65}")
    print(f"{'Period':>8} {'n':>6} {'mean_err':>8}")
    print("-" * 30)
    for period, n_err, mean_err in summary:
        if mean_err is None:
            print(f"{period:>8} {n_err:>6d} {'n/a':>8}")
        else:
            print(f"{period:>8} {n_err:>6d} {mean_err:>8.4f}")


if __name__ == "__main__":
    main()
