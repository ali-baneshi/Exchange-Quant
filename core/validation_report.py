#!/usr/bin/env python3

"""
validation_report.py — Honest, corrected, single-source-of-truth report.

Runs ALL experiments with proper train/val/test split, Bonferroni correction,
block bootstrap, and financial metrics.  Outputs a structured JSON report.

Usage:
    python3 validation_report.py [--period 60min] [--output report.json]
"""

import argparse
import json
import math
import statistics
import sys
import time

from data_historical import fetch_klines_range, parse_klines, held_out_split
from ensemble import Ensemble
from ensemble_adaptive import AdaptiveEnsemble
from validation import (
    comprehensive_report, print_report, bonferroni_correct, N_HYPOTHESES_TOTAL
)

from backtest import classical_ensemble_klines, quantum_model_klines as qm_klines
from backtest_boost import run_split as run_boost_split
from backtest_ensemble import run_backtest as run_ensemble_backtest


def run_backtest_plain(candles, label="", window=20):
    """Run classical vs quantum comparison on candles (like original backtest.py)."""
    from backtest import compute_features, classical_ensemble_klines, quantum_model_klines

    features_list = []
    for i in range(len(candles)):
        prev = features_list if i > 0 else []
        f = compute_features(candles[i], prev)
        features_list.append(f)

    history = []
    c_errs = []
    q_errs = []

    for i in range(len(features_list) - 1):
        curr = features_list[i]
        target = 1.0 if candles[i + 1]["close"] > candles[i + 1]["open"] else 0.0
        history.append(curr)

        if len(history) >= window + 1:
            lookback = history[-(window + 1):-1]
            pred_c = classical_ensemble_klines(lookback)
            pred_q, delta, conf = quantum_model_klines(lookback)
            c_errs.append(abs(pred_c - target))
            q_errs.append(abs(pred_q - target))

    return comprehensive_report(c_errs, q_errs, label, periods_per_year=8760)


def run_boost_split_ho(candles, label="", window=15):
    """Compare adaptive vs fixed-weight ensemble."""
    from backtest_boost import compute_features

    features_list = []
    for i in range(len(candles)):
        prev = features_list if i > 0 else []
        f = compute_features(candles[i], prev)
        features_list.append(f)

    ens_fixed = Ensemble(window=window)
    ens_fixed.weights = [0.5, 0.5]
    orig_refresh = ens_fixed._refresh_weights
    ens_fixed._refresh_weights = lambda: None

    ens_adaptive = Ensemble(window=window)

    errs_fixed, errs_adaptive = [], []

    for variant_key, ensemble, out in [
        ("fixed", ens_fixed, errs_fixed),
        ("adaptive", ens_adaptive, errs_adaptive),
    ]:
        history = []
        for i in range(len(features_list) - 1):
            curr = features_list[i]
            target = 1.0 if candles[i + 1]["close"] > candles[i + 1]["open"] else 0.0
            history.append(curr)
            if len(history) >= window + 1:
                lookback = history[-(window + 1):-1]
                pred, w, meta = ensemble.predict_and_update(lookback, target)
                out.append(abs(pred - target))

    return comprehensive_report(errs_fixed, errs_adaptive, label + " [adaptive_vs_fixed]", periods_per_year=8760)


def run_ensemble_ho(candles, label="", window=20):
    """Run AdaptiveEnsemble vs standalone quantum."""
    from backtest_ensemble import compute_features, quantum_model_klines

    features_list = []
    for i in range(len(candles)):
        prev = features_list if i > 0 else []
        f = compute_features(candles[i], prev)
        features_list.append(f)

    ensemble = AdaptiveEnsemble(mode="buyratio", n_models=2, window=window)
    history = []
    e_errs, q_errs = [], []

    for i in range(len(features_list) - 1):
        curr = features_list[i]
        target = 1.0 if candles[i + 1]["close"] > candles[i + 1]["open"] else 0.0
        history.append(curr)
        if len(history) >= window + 1:
            lookback = history[-(window + 1):-1]
            pred_q, _ = quantum_model_klines(lookback)
            pred_e, preds, weights = ensemble.predict_and_update(lookback, target)
            e_errs.append(abs(pred_e - target))
            q_errs.append(abs(pred_q - target))

    return comprehensive_report(e_errs, q_errs, label + " [ensemble_vs_q]", periods_per_year=8760)



def main():
    parser = argparse.ArgumentParser(description="Comprehensive validation report")
    parser.add_argument("--period", default="60min", choices=["15min", "60min", "1day"])
    parser.add_argument("--output", default=None, help="JSON output path")
    args = parser.parse_args()

    sys.stdout.reconfigure(line_buffering=True)

    period = args.period
    n_candles = 5000

    print(f"\n{'='*65}")
    print(f"  COMPREHENSIVE VALIDATION REPORT")
    print(f"  Period: {period}  |  Bonferroni correction: {N_HYPOTHESES_TOTAL} tests")
    print(f"  Methodology: walk-forward (train→val→held-out), block bootstrap")
    print(f"{'='*65}\n")

    raw = fetch_klines_range("btcusdt", period, n_candles)
    candles = parse_klines(raw)
    train_val, held_out = held_out_split(candles)
    split2 = int(len(train_val) * 0.6)
    train_set = train_val[:split2]
    val_set = train_val[split2:]

    print(f"  Data: {len(candles)} total | "
          f"{len(train_set)} train | {len(val_set)} val | {len(held_out)} held-out\n")

    all_reports = {}
    t0 = time.time()

    # === 1. Backtest: classical vs quantum Born rule ===
    print(f"{'='*55}")
    print(f"  1. BORN RULE BACKTEST: Classical vs Quantum")
    print(f"{'='*55}")
    r_bt_train = run_backtest_plain(train_set, f" [train {period}]")
    r_bt_val = run_backtest_plain(val_set, f" [val {period}]")
    r_bt_ho = run_backtest_plain(held_out, f" [held-out {period}]")
    print_report(r_bt_ho, detail=False)
    all_reports["born_rule_heldout"] = r_bt_ho
    all_reports["born_rule_val"] = r_bt_val

    # === 2. Adaptive vs Fixed weight comparison ===
    print(f"{'='*55}")
    print(f"  2. ADAPTIVE WEIGHTING: Fixed equal weight vs Adaptive")
    print(f"{'='*55}")
    r_bs_ho = run_boost_split_ho(held_out, f" [held-out {period}]")
    print_report(r_bs_ho, detail=False)
    all_reports["adaptive_weights_heldout"] = r_bs_ho

    # === 3. AdaptiveEnsemble vs standalone quantum ===
    print(f"{'='*55}")
    print(f"  3. ADAPTIVE ENSEMBLE vs Standalone Quantum")
    print(f"{'='*55}")
    r_en_ho = run_ensemble_ho(held_out, f" [held-out {period}]")
    print_report(r_en_ho, detail=False)
    all_reports["ensemble_vs_quantum_heldout"] = r_en_ho

    # === SUMMARY ===
    print(f"\n{'='*65}")
    print(f"  SUMMARY — BONFERRONI-CORRECTED HELD-OUT RESULTS")
    print(f"{'='*65}")
    print(f"{'Experiment':<30} {'n':>6} {'Imprv%':>8} {'WinRate':>9} {'Raw_p':>8} {'Bonf_p':>8} {'Sig':>5}")
    print("-" * 75)

    for key, r in all_reports.items():
        if isinstance(r, dict) and "mean_q" in r:
            p_str = f"{r['bonferroni_p']:.4f}" if r else "?"
            sig = "YES" if r and r['significant_005'] else "no"
            print(f"{key:<30} {r['n']:>6d} {r['improvement_pct']:>+7.2f}% "
                  f"{r['win_rate']:>8.1%} {r['raw_p_value']:>8.4f} {p_str:>8} {sig:>5}")

    elapsed = time.time() - t0
    print(f"\n  Total time: {elapsed:.1f}s")

    # Save JSON
    if args.output:
        with open(args.output, "w") as f:
            json.dump(all_reports, f, indent=2, default=str)
        print(f"  Saved to {args.output}")


if __name__ == "__main__":
    main()
