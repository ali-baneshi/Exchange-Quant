#!/usr/bin/env python3

"""
validation_report.py — Classical-only kline report + live Born-rule status.

Born rule was removed from kline evaluation (2026-07-23). This report:
  1. Evaluates classical ensemble MAE on held-out klines
  2. Runs classical ablation (vol / MA / vol+ma) when data allows
  3. Optionally summarizes existing live order-book results

Usage:
    python3 validation_report.py [--period 60min] [--output report.json]
"""

import argparse
import glob
import json
import os
import statistics
import sys
import time

from data_historical import fetch_klines_range, parse_klines, held_out_split
from backtest import classical_ensemble_klines, run_backtest
from features import compute_features
from validation import comprehensive_report, print_report

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "_live_results")


def _mean_or_none(errs):
    return statistics.mean(errs) if errs else None


def classical_splits(candles, period):
    train_val, held_out = held_out_split(candles)
    split2 = int(len(train_val) * 0.6)
    train_set = train_val[:split2]
    val_set = train_val[split2:]

    errs_train = run_backtest(train_set)
    errs_val = run_backtest(val_set)
    errs_ho = run_backtest(held_out)

    return {
        "period": period,
        "n_total": len(candles),
        "n_train": len(train_set),
        "n_val": len(val_set),
        "n_held_out": len(held_out),
        "train_mean_err": _mean_or_none(errs_train),
        "val_mean_err": _mean_or_none(errs_val),
        "heldout_mean_err": _mean_or_none(errs_ho),
        "heldout_n_preds": len(errs_ho),
        "target": "binary_direction",
        "born_rule_on_klines": "removed",
    }


def classical_ablation(candles, window=15):
    """vol_regime vs MA vs ensemble on held-out klines (classical only)."""
    from ensemble import _volregime_predict, _ma_predict

    _, held_out = held_out_split(candles)
    features_list = []
    for i in range(len(held_out)):
        prev = features_list if i > 0 else []
        features_list.append(compute_features(held_out[i], prev))

    def run_model(predict_fn):
        history, errs = [], []
        for i in range(len(features_list) - 1):
            history.append(features_list[i])
            target = 1.0 if held_out[i + 1]["close"] > held_out[i + 1]["open"] else 0.0
            if len(history) >= window + 1:
                lookback = history[-(window + 1):-1]
                pred = predict_fn(lookback)
                errs.append(abs(pred - target))
        return errs

    def ensemble_predict(lookback):
        return statistics.mean([_volregime_predict(lookback), _ma_predict(lookback)])

    errs_v = run_model(_volregime_predict)
    errs_m = run_model(_ma_predict)
    errs_vm = run_model(ensemble_predict)

    report = None
    if errs_v and errs_vm:
        report = comprehensive_report(errs_v, errs_vm, " [vol vs vol+ma]")

    means = {
        "vol_regime": _mean_or_none(errs_v),
        "ma": _mean_or_none(errs_m),
        "vol+ma": _mean_or_none(errs_vm),
    }
    ranked = [(k, v) for k, v in means.items() if v is not None]
    best = min(ranked, key=lambda x: x[1]) if ranked else (None, None)

    return {
        "means": means,
        "best_model": best[0],
        "best_mean_err": best[1],
        "n": len(errs_v),
        "vol_vs_ensemble_report": report,
        "born_rule_on_klines": "removed",
    }


def live_born_status():
    """Summarize on-disk live results if present; do not invent quantum kline scores."""
    paths = sorted(glob.glob(os.path.join(RESULTS_DIR, "*.json")))
    result_paths = [p for p in paths if os.path.basename(p) != "state.json"]
    status = {
        "born_rule_on_klines": "removed",
        "live_result_files": len(result_paths),
        "message": (
            "Born rule is only valid on live order-book pipelines. "
            "Run: python3 pipeline_live_ensemble.py btcusdt 720 3600 quantum"
        ),
    }
    if not result_paths:
        status["live_eval"] = "no_results_yet"
        return status

    resolved = 0
    for p in result_paths[:200]:
        try:
            with open(p) as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("schema_version") in (2, 3):
                resolved += sum(
                    1 for r in data.get("predictions", [])
                    if isinstance(r, dict) and r.get("status") == "resolved"
                )
                if data.get("schema_version") == 3:
                    status.setdefault("schema_v3_files", 0)
                    status["schema_v3_files"] += 1
                    if data.get("run_id"):
                        status.setdefault("run_ids", [])
                        if data["run_id"] not in status["run_ids"]:
                            status["run_ids"].append(data["run_id"])
            elif isinstance(data, dict) and data.get("resolved"):
                resolved += 1
            elif isinstance(data, list):
                resolved += sum(
                    1 for r in data
                    if isinstance(r, dict) and (r.get("resolved") or r.get("status") == "resolved")
                )
        except Exception:
            continue

    status["live_eval"] = "partial" if resolved else "files_present_unresolved"
    status["resolved_records_sampled"] = resolved
    return status


def main():
    parser = argparse.ArgumentParser(description="Classical validation report (Born rule off klines)")
    parser.add_argument("--period", default="60min", choices=["15min", "60min", "1day"])
    parser.add_argument("--output", default=None, help="JSON output path")
    args = parser.parse_args()

    sys.stdout.reconfigure(line_buffering=True)

    period = args.period
    n_candles = 5000

    print(f"\n{'='*65}")
    print(f"  VALIDATION REPORT (classical klines + live Born status)")
    print(f"  Period: {period}")
    print(f"  Born rule on klines: REMOVED (2026-07-23)")
    print(f"{'='*65}\n")

    raw = fetch_klines_range("btcusdt", period, n_candles)
    candles = parse_klines(raw)
    print(f"  Data: {len(candles)} candles (oldest→newest)\n")

    all_reports = {"born_rule_on_klines": "removed"}
    t0 = time.time()

    print(f"{'='*55}")
    print(f"  1. CLASSICAL ENSEMBLE (binary direction target)")
    print(f"{'='*55}")
    classical = classical_splits(candles, period)
    all_reports["classical_klines"] = classical
    for key in ("train_mean_err", "val_mean_err", "heldout_mean_err"):
        val = classical[key]
        label = key.replace("_mean_err", "")
        if val is None:
            print(f"  {label}: n/a")
        else:
            print(f"  {label} mean abs error: {val:.4f}")

    print(f"\n{'='*55}")
    print(f"  2. CLASSICAL ABLATION (vol / MA / vol+ma)")
    print(f"{'='*55}")
    ablation = classical_ablation(candles)
    all_reports["classical_ablation"] = {
        k: v for k, v in ablation.items() if k != "vol_vs_ensemble_report"
    }
    if ablation.get("vol_vs_ensemble_report"):
        print_report(ablation["vol_vs_ensemble_report"], detail=False)
        all_reports["classical_ablation"]["vol_vs_ensemble"] = ablation["vol_vs_ensemble_report"]
    for name, mean_err in ablation["means"].items():
        if mean_err is None:
            print(f"  {name}: n/a")
        else:
            print(f"  {name}: err={mean_err:.4f}")
    if ablation["best_model"]:
        print(f"  Best: {ablation['best_model']} ({ablation['best_mean_err']:.4f})")

    print(f"\n{'='*55}")
    print(f"  3. LIVE BORN-RULE STATUS (order book only)")
    print(f"{'='*55}")
    live = live_born_status()
    all_reports["live_born_status"] = live
    print(f"  live_result_files: {live['live_result_files']}")
    print(f"  live_eval: {live['live_eval']}")
    print(f"  {live['message']}")

    # Smoke that classical_ensemble_klines still imports for callers
    _ = classical_ensemble_klines

    elapsed = time.time() - t0
    print(f"\n  Total time: {elapsed:.1f}s")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(all_reports, f, indent=2, default=str)
        print(f"  Saved to {args.output}")


if __name__ == "__main__":
    main()
