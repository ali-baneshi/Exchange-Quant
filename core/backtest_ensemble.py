#!/usr/bin/env python3

"""
Ensemble backtest: AdaptiveEnsemble vs standalone quantum on klines.

Compares a 2-model ensemble (quantum + vol_regime) against pure Born rule.
Uses walk-forward validation with Bonferroni-corrected p-values.

Usage:
    python3 backtest_ensemble.py
"""

import math
import statistics
import sys
import time

from data_historical import fetch_klines_range, parse_klines, held_out_split
from ensemble_adaptive import AdaptiveEnsemble
from quantum_core import born_rule_predict
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
        "open": candle["open"],
        "high": candle["high"],
        "low": candle["low"],
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


def quantum_model_klines(history):
    pred, meta = born_rule_predict(history, value_key="conviction")
    return pred, meta["delta"]


PERIODS_PER_YEAR = {"15min": 35040, "60min": 8760, "1day": 365}

def run_backtest(period, candles, label="", window=20, periods_per_year=8760):
    features_list = []
    for i in range(len(candles)):
        prev = features_list if i > 0 else []
        f = compute_features(candles[i], prev)
        features_list.append(f)

    ensemble = AdaptiveEnsemble(mode="buyratio", n_models=2, window=window)
    history = []
    results = []

    for i in range(len(features_list) - 1):
        curr = features_list[i]
        target = 1.0 if candles[i + 1]["close"] > candles[i + 1]["open"] else 0.0
        history.append(curr)

        if len(history) >= window + 1:
            lookback = history[-(window + 1):-1]

            pred_q, _ = quantum_model_klines(lookback)
            pred_e, preds, weights = ensemble.predict_and_update(lookback, target)

            c_err = abs(pred_e - target)
            q_err = abs(pred_q - target)

            results.append({
                "ensemble_err": c_err,
                "quantum_err": q_err,
            })

    e_errs = [r["ensemble_err"] for r in results]
    q_errs = [r["quantum_err"] for r in results]

    report = comprehensive_report(e_errs, q_errs, label, periods_per_year=periods_per_year)
    return results, report


def main():
    for period in ["15min", "60min", "1day"]:
        print(f"\n{'#' * 60}")
        print(f"#  {period}")
        print(f"{'#' * 60}")

        raw = fetch_klines_range("btcusdt", period, 5000)
        candles = parse_klines(raw)
        print(f"Loaded {len(candles)} {period} candles")

        train_val, held_out = held_out_split(candles)
        split2 = int(len(train_val) * 0.6)
        train_set = train_val[:split2]
        val_set = train_val[split2:]

        t0 = time.time()
        ppy = PERIODS_PER_YEAR[period]

        _, report_train = run_backtest(period, train_set, f" [train {period}]", periods_per_year=ppy)
        print_report(report_train, detail=False)

        _, report_val = run_backtest(period, val_set, f" [val {period}]", periods_per_year=ppy)
        print_report(report_val, detail=False)

        _, report_ho = run_backtest(period, held_out, f" [held-out {period}]", periods_per_year=ppy)
        print_report(report_ho, detail=True)

        print(f"  Completed in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    main()
