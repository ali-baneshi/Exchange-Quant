#!/usr/bin/env python3

"""
Analyze live pipeline results from JSON.

Usage:
  python3 analyze_live_results.py
  python3 analyze_live_results.py _live_results/btcusdt_live_*.json
"""

import json
import os
import sys
import statistics
import glob
from collections import Counter

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "_live_results")
SCHEMA_VERSIONS = (2, 3)


def load_results(path):
    with open(path) as f:
        return json.load(f)


def _is_result_document(data):
    if isinstance(data, list):
        return True
    if not isinstance(data, dict):
        return False
    if data.get("schema_version") in SCHEMA_VERSIONS:
        return True
    return "predictions" in data


def _normalize_results(data):
    if isinstance(data, dict) and data.get("schema_version") in SCHEMA_VERSIONS:
        predictions = data.get("predictions", [])
        resolved = [p for p in predictions if p.get("status") == "resolved"]
        if any("score_eligible" in p for p in resolved):
            eligible = [p for p in resolved if p.get("score_eligible", True)]
            if eligible:
                resolved = eligible
        return resolved, data
    return data, None


def _detect_format(results):
    if not results:
        return "unknown"
    r = results[0]
    if r.get("mode") == "quantum" and "prediction" in r:
        return "quantum_prediction"
    if "ensemble" in r or "prediction" in r:
        return "ensemble"
    if "quantum" in r:
        return "classic"
    return "unknown"


def analyze(results):
    results, meta_doc = _normalize_results(results)
    if meta_doc is not None:
        version = meta_doc.get("schema_version", "?")
        total_predictions = len(meta_doc.get("predictions", []))
        pending = sum(1 for p in meta_doc.get("predictions", []) if p.get("status") == "pending")
        observations = len(meta_doc.get("observations", []))
        print(f"  Schema:         v{version} resolve-later")
        if meta_doc.get("run_id"):
            print(f"  Run ID:         {meta_doc['run_id']}")
        if meta_doc.get("ensemble_weights"):
            w = meta_doc["ensemble_weights"]
            print(f"  Ensemble w:     q={w[0]:.2f} v={w[1]:.2f}")
        print(f"  Observations:   {observations}")
        print(f"  Predictions:    {total_predictions} total, {pending} pending, {len(results)} resolved (eligible)")
        print(f"  Horizon:        {meta_doc.get('horizon_s')}s")

    n = len(results)
    if n < 3:
        print(f"  Only {n} resolved data points — need at least 3 for analysis")
        return

    fmt = _detect_format(results)

    if fmt == "ensemble":
        model_name = "Ensemble"
        key = "prediction" if "prediction" in results[0] else "ensemble"
        actual_key = "resolved_actual" if "resolved_actual" in results[0] else "actual"
        m_errs = [abs(r[key] - r[actual_key]) for r in results]
        q_errs = [abs(r.get("quantum_raw", r[key]) - r[actual_key]) for r in results]
        raw_name = "Quantum_raw"
    elif fmt == "quantum_prediction":
        model_name = "Quantum"
        key = "prediction"
        actual_key = "resolved_actual" if "resolved_actual" in results[0] else "actual"
        m_errs = [abs(r[key] - r[actual_key]) for r in results]
        q_errs = m_errs
        raw_name = "Quantum"
    else:
        model_name = "Quantum"
        actual_key = "resolved_actual" if "resolved_actual" in results[0] else "actual"
        m_errs = [abs(r["quantum"] - r[actual_key]) for r in results]
        q_errs = m_errs
        raw_name = "Quantum"

    c_errs = [abs(r["classical"] - r[actual_key]) for r in results]
    wins = sum(1 for ce, me in zip(c_errs, m_errs) if me < ce)
    losses = n - wins

    mean_c = statistics.mean(c_errs)
    mean_m = statistics.mean(m_errs)
    improvement = (mean_c - mean_m) / mean_c * 100 if mean_c > 0 else 0
    exploratory = n < 30

    start_time = results[0].get("created_time", results[0].get("time", "?"))
    end_time = results[-1].get("resolved_time", results[-1].get("time", "?"))
    start_price = results[0].get("entry_price", results[0].get("price", 0))
    end_price = results[-1].get("exit_price", results[-1].get("price", 0))
    print(f"  Data range:     {start_time} → {end_time}")
    print(f"  Resolved obs:   {n}")
    print(f"  Price range:    {start_price:.2f} → {end_price:.2f}")
    print(f"  Model:          {model_name}")
    print(f"  Classical err:  {mean_c:.4f}")
    print(f"  {model_name} err:    {mean_m:.4f}")
    if exploratory:
        print(f"  Status:         exploratory only until n>=30")
    else:
        print(f"  Improvement:    {improvement:+.2f}%")
        print(f"  {model_name} wins:   {wins}/{n} ({wins/n*100:.1f}%)")
        print(f"  Losses:         {losses}/{n} ({losses/n*100:.1f}%)")
    if q_errs is not m_errs:
        raw_wins = sum(1 for ce, qe in zip(c_errs, q_errs) if qe < ce)
        raw_mean = statistics.mean(q_errs)
        print(f"  {raw_name} err: {raw_mean:.4f}")
        if not exploratory:
            print(f"  {raw_name} wins:{raw_wins}/{n} ({raw_wins/n*100:.1f}%)")

    preds = [r[key] for r in results if key and key in r]
    acts = [r[actual_key] for r in results if actual_key in r and key and key in r]
    if preds and acts:
        bias = statistics.mean(p - a for p, a in zip(preds, acts))
        print(f"  Bias pred-act:  {bias:+.4f}")

    deltas = [r.get("delta") for r in results]
    delta_none = sum(d is None for d in deltas)
    valid_deltas = [d for d in deltas if d is not None]
    print(f"  Delta None:     {delta_none}/{n} ({delta_none/n*100:.1f}%)")
    if valid_deltas:
        print(f"  Delta range:    {min(valid_deltas):.3f} → {max(valid_deltas):.3f}")
        print(f"  Delta mean:     {statistics.mean(valid_deltas):.3f}")

    sources = Counter(r.get("delta_source", r.get("data_source", "legacy")) for r in results)
    fallbacks = Counter(r.get("fallback_reason", "legacy") for r in results)
    print(f"  Delta sources:  {dict(sources)}")
    print(f"  Fallbacks:      {dict(fallbacks)}")

    interference = [r.get("interference_term") for r in results if r.get("interference_term") is not None]
    if interference:
        print(f"  Interference:   mean={statistics.mean(interference):+.4f} "
              f"range={min(interference):+.4f}→{max(interference):+.4f}")

    eligible = [r for r in results if r.get("score_eligible", True)]
    skipped = n - len(eligible)
    if skipped:
        print(f"  Skipped quality:{skipped}/{n}")
    trades = [r for r in eligible if r.get("signal") == "long"]
    if trades:
        returns = [r.get("net_return", 0.0) for r in trades]
        wins_ret = sum(1 for r in returns if r > 0)
        loss_sum = abs(sum(r for r in returns if r < 0))
        win_sum = sum(r for r in returns if r > 0)
        pf = win_sum / loss_sum if loss_sum > 0 else float("inf") if win_sum > 0 else 1.0
        print(f"  Trades:         {len(trades)} long  hit={wins_ret}/{len(trades)} ({wins_ret/len(trades)*100:.1f}%)")
        print(f"  Avg net ret:    {statistics.mean(returns):+.5f}")
        print(f"  Profit factor:  {pf:.4f}")
    non_fallback = [r for r in eligible if r.get("fallback_reason") == "none"]
    print(f"  Born active:    {len(non_fallback)}/{len(eligible)} eligible")

    if fmt == "ensemble":
        last_w = results[-1]
        if "w_quantum" in last_w and "w_vol_regime" in last_w:
            print(f"  Last weights:   q={last_w['w_quantum']:.2f} v={last_w['w_vol_regime']:.2f}")
        elif meta_doc and meta_doc.get("ensemble_weights"):
            w = meta_doc["ensemble_weights"]
            print(f"  Last weights:   q={w[0]:.2f} v={w[1]:.2f} (from doc)")
        last_delta = last_w.get("delta")
        print(f"  Last delta:     {last_delta:.2f}" if last_delta is not None else "  Last delta:     None")

    try:
        from reality_check import reality_check
        rc = reality_check(c_errs, m_errs, n_bootstrap=10000)
        print(f"  White's RC p:   {rc.get('p_value', 'N/A')}  → {rc.get('interpretation', 'N/A')}")
    except ImportError:
        pass

    return {
        "n": n,
        "mean_c": mean_c,
        "mean_q": mean_m,
        "improvement": improvement,
        "wins": wins,
        "win_rate": wins / n if n > 0 else 0,
    }


def main():
    paths = sys.argv[1:] if len(sys.argv) > 1 else sorted(glob.glob(os.path.join(RESULTS_DIR, "*.json")))
    # Skip persisted runner state — not a results document
    paths = [p for p in paths if os.path.basename(p) != "state.json"]

    if not paths:
        print(f"No result files found in {RESULTS_DIR}")
        print(f"Usage: {sys.argv[0]} [path/to/results.json ...]")
        return

    all_summaries = []

    for path in paths:
        print(f"\n{'=' * 55}")
        print(f"  FILE: {os.path.basename(path)}")
        print(f"{'=' * 55}")
        results = load_results(path)
        if not _is_result_document(results):
            print("  Skipping non-result JSON (not schema v2/v3 / not a list)")
            continue
        summary = analyze(results)
        if summary:
            all_summaries.append(summary)

    if len(all_summaries) > 1:
        print(f"\n{'=' * 55}")
        print(f"  AGGREGATE")
        print(f"{'=' * 55}")
        total_n = sum(s["n"] for s in all_summaries)
        total_wins = sum(s["wins"] for s in all_summaries)
        weighted_c = sum(s["mean_c"] * s["n"] for s in all_summaries) / total_n if total_n else 0
        weighted_q = sum(s["mean_q"] * s["n"] for s in all_summaries) / total_n if total_n else 0
        print(f"  Total observations: {total_n}")
        print(f"  Weighted classical: {weighted_c:.4f}")
        print(f"  Weighted quantum:   {weighted_q:.4f}")
        imprv = (weighted_c - weighted_q) / weighted_c * 100 if weighted_c else 0
        print(f"  Improvement:        {imprv:+.2f}%")
        print(f"  Total wins:         {total_wins}/{total_n} ({total_wins/total_n*100:.1f}%)")


if __name__ == "__main__":
    main()
