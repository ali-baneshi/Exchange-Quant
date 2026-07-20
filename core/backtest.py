#!/usr/bin/env python3

"""
Backtest: Classical vs Quantum comparison on historical klines.

Uses walk-forward validation (train→val→held-out), block bootstrap,
and Bonferroni correction.  Compares the Born rule quantum model against
a classical ensemble on binary direction prediction.

Usage:
    python3 backtest.py
"""

import math
import statistics
import time

from data_historical import fetch_klines_range, parse_klines, held_out_split
from quantum_core import born_rule_predict
from validation import comprehensive_report, print_report


def compute_features(candle, prev_candles):
    features = {
        "ts": candle["ts"],
        "price": candle["close"],
        "open": candle["open"],
        "high": candle["high"],
        "low": candle["low"],
        "close": candle["close"],
        "vol": candle["vol"],
        "amount": candle["amount"],
        "count": candle.get("count", 0),
    }
    candle_range = candle["high"] - candle["low"]
    body = abs(candle["close"] - candle["open"])
    features["body_ratio"] = body / candle_range if candle_range > 0 else 0.0
    features["direction"] = 1.0 if candle["close"] > candle["open"] else 0.0
    features["volatility"] = candle_range / candle["close"] if candle["close"] else 0.0

    signed_direction = 1.0 if candle["close"] > candle["open"] else -1.0
    features["avg_trade_size"] = candle["amount"] / max(1, candle.get("count", 1))
    features["price_impact"] = (candle["close"] - candle["open"]) / candle["amount"] if candle["amount"] > 0 else 0.0
    features["imbalance"] = (features["direction"] - 0.5) * features["body_ratio"] * 2

    if prev_candles:
        prev_close = prev_candles[-1]["close"]
        features["return"] = (candle["close"] - prev_close) / prev_close if prev_close else 0.0
        features["log_return"] = math.log(candle["close"] / prev_close) if prev_close > 0 else 0.0
        if len(prev_candles) >= 3:
            vols = [c["vol"] for c in prev_candles[-3:]]
            vol_prev = statistics.mean(vols[:-1]) if len(vols) > 1 else vols[0]
            features["volume_change"] = (candle["vol"] - vol_prev) / vol_prev if vol_prev > 0 else 0.0
        else:
            features["volume_change"] = 0.0
        if len(prev_candles) >= 5:
            recent_vols = [c["vol"] for c in prev_candles[-5:]]
            features["vol_percentile"] = sum(1 for v in recent_vols if v <= candle["vol"]) / len(recent_vols)
        else:
            features["vol_percentile"] = 0.5
    else:
        features["return"] = 0.0
        features["log_return"] = 0.0
        features["volume_change"] = 0.0
        features["vol_percentile"] = 0.5

    features["conviction"] = features["direction"] * features["body_ratio"]
    features["buy_ratio"] = features["conviction"]
    features["signed_conviction"] = signed_direction * features["body_ratio"]
    features["abs_return"] = abs(features["return"])

    return features


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


def quantum_model_klines(history):
    pred, meta = born_rule_predict(history, value_key="conviction")
    return pred, meta["delta"], meta["confidence"]


def run_backtest(candles, label="", periods_per_year=8760):
    features_list = []
    for i in range(len(candles)):
        prev = features_list if i > 0 else []
        f = compute_features(candles[i], prev)
        features_list.append(f)

    history = []
    results = []

    for i in range(len(features_list) - 1):
        curr = features_list[i]
        next_candle = features_list[i + 1]
        target = next_candle["direction"]

        history.append(curr)

        if len(history) >= 20 + 1:
            lookback = history[-(20 + 1):-1]

            pred_c = classical_ensemble_klines(lookback)
            pred_q, delta, conf = quantum_model_klines(lookback)

            c_err = abs(pred_c - target)
            q_err = abs(pred_q - target)

            results.append({
                "step": i,
                "c_err": c_err,
                "q_err": q_err,
            })

    c_errs = [r["c_err"] for r in results]
    q_errs = [r["q_err"] for r in results]

    report = comprehensive_report(c_errs, q_errs, label, periods_per_year=periods_per_year)
    return results, report


PERIODS_PER_YEAR = {"15min": 35040, "60min": 8760, "1day": 365}

def main():
    periods = [("15min", 5000), ("60min", 5000), ("1day", 5000)]

    for period, n in periods:
        print(f"\n{'#' * 65}")
        print(f"#  PERIOD: {period}  ({n} candles)")
        print(f"{'#' * 65}")

        raw = fetch_klines_range("btcusdt", period, n)
        candles = parse_klines(raw)
        print(f"  Loaded {len(candles)} candles")

        train_val, held_out = held_out_split(candles)
        print(f"  Train/val: {len(train_val)}  Held-out: {len(held_out)}")

        # Further split train_val into train (60%) and val (40%)
        split2 = int(len(train_val) * 0.6)
        train_set = train_val[:split2]
        val_set = train_val[split2:]

        t0 = time.time()

        ppy = PERIODS_PER_YEAR[period]

        # Train
        _, report_train = run_backtest(train_set, f" [train {period}]", periods_per_year=ppy)
        print_report(report_train, detail=False)

        # Validate
        _, report_val = run_backtest(val_set, f" [val {period}]", periods_per_year=ppy)
        print_report(report_val, detail=False)

        # Held-out test (FINAL)
        _, report_ho = run_backtest(held_out, f" [held-out test {period}]", periods_per_year=ppy)
        print_report(report_ho, detail=True)

        elapsed = time.time() - t0
        print(f"  Completed in {elapsed:.1f}s")

    # Cross-period summary (held-out only)
    print(f"\n{'=' * 65}")
    print(f"  CROSS-PERIOD HELD-OUT COMPARISON (Bonferroni corrected)")
    print(f"{'='*65}")
    print(f"{'Period':>8} {'n':>6} {'imprv%':>8} {'win_rate':>9} {'raw_p':>8} {'corr_p':>8} {'sig':>10} {'DD_red':>8}")
    print("-" * 75)
    for period, n in periods:
        ppy = PERIODS_PER_YEAR[period]
        raw = fetch_klines_range("btcusdt", period, n)
        candles = parse_klines(raw)
        _, held_out = held_out_split(candles)
        if held_out:
            _, report = run_backtest(held_out, f" [held-out {period}]", periods_per_year=ppy)
            p_str = f"{report['bonferroni_p']:.4f}" if report else "?"
            dd_str = f"{report['max_drawdown_reduction']:+.1f}%" if report else "?"
            sig_str = "YES" if report and report['significant_005'] else "no"
            print(f"{period:>8} {report['n']:>6d} {report['improvement_pct']:>+7.2f}% "
                  f"{report['win_rate']:>8.1%} {report['raw_p_value']:>8.4f} {p_str:>8} {sig_str:>10} {dd_str:>8}")


if __name__ == "__main__":
    main()
