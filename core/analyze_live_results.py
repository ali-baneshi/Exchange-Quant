#!/usr/bin/env python3

"""
Analyze live pipeline results from JSON.

Usage:
  python3 analyze_live_results.py
  python3 analyze_live_results.py --schema-version 5
  python3 analyze_live_results.py --run-id btcusdt-quantum-123 --min-resolved 30
  python3 analyze_live_results.py _live_results/btcusdt_quantum_*.json
"""

import argparse
import glob
import json
import math
import os
import statistics
import sys
from collections import Counter

from config import (
    ACQUISITION_POLICY_VERSION,
    DATA_POLICY_VERSION,
    DISQUALIFYING_QUALITY_FLAGS,
    LIVE_IMPLEMENTATION_REVISION,
    LIVE_MODEL_VERSION,
    MIN_SIGNIFICANCE_N,
)

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "_live_results")
SCHEMA_VERSIONS = (2, 3, 4, 5, 6)


def load_results(path):
    with open(path) as f:
        return json.load(f)


def _is_collector_list(data, path):
    if not isinstance(data, list):
        return False
    base = os.path.basename(path)
    return base.startswith("collected_") or (
        data and isinstance(data[0], dict) and "buy_ratio" in data[0] and "status" not in data[0]
    )


def _is_result_document(data):
    if isinstance(data, list):
        return True
    if not isinstance(data, dict):
        return False
    if data.get("schema_version") in SCHEMA_VERSIONS:
        return True
    return "predictions" in data


def _document_schema_version(data):
    if isinstance(data, dict):
        return data.get("schema_version")
    return None


def _document_run_id(data):
    if isinstance(data, dict):
        return data.get("run_id")
    return None


def should_include_path(path, data, args):
    """Filter paths by CLI flags before analysis."""
    if args.exclude_collector and _is_collector_list(data, path):
        return False, "collector list"

    schema = _document_schema_version(data)
    if args.schema_version is not None:
        if schema != args.schema_version:
            return False, f"schema v{schema} != v{args.schema_version}"

    if args.run_id is not None:
        rid = _document_run_id(data)
        if rid != args.run_id:
            return False, "run_id mismatch"

    if (
        schema == 6
        and not getattr(args, "allow_pre_hardening_v6", False)
    ):
        identity_errors = _v6_identity_errors(data)
        if identity_errors:
            return False, "invalid v6r1 identity: " + ", ".join(identity_errors)

    return True, None


def _v6_identity_errors(data):
    if not isinstance(data, dict):
        return ["document_not_object"]
    errors = []
    expected = {
        "model_version": LIVE_MODEL_VERSION,
        "data_policy_version": DATA_POLICY_VERSION,
        "implementation_revision": LIVE_IMPLEMENTATION_REVISION,
        "acquisition_policy_version": ACQUISITION_POLICY_VERSION,
    }
    for field, value in expected.items():
        if data.get(field) != value:
            errors.append(f"{field}!={value}")
    manifest = data.get("experiment_manifest")
    if not isinstance(manifest, dict):
        errors.append("missing_experiment_manifest")
    else:
        for field in (
            "model_version",
            "implementation_revision",
            "acquisition_policy_version",
        ):
            if manifest.get(field) != expected[field]:
                errors.append(f"manifest.{field}!={expected[field]}")
        if manifest.get("label_policy") != "captured_trade_window_v1":
            errors.append("manifest.label_policy")
        if manifest.get("primary_metric") != "paired_mae_difference":
            errors.append("manifest.primary_metric")
    for field in ("run_id", "config_hash", "symbol", "mode", "horizon_s"):
        if data.get(field) in (None, ""):
            errors.append(f"missing_{field}")
    return errors


def _finite_unit(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0.0 <= value <= 1.0
    )


def _v6_row_errors(pred, horizon_s):
    errors = []
    for field in ("classical", "prediction", "resolved_actual"):
        if not _finite_unit(pred.get(field)):
            errors.append(f"invalid_{field}")
    classical_error = pred.get("classical_error")
    prediction_error = pred.get("prediction_error")
    if not isinstance(classical_error, (int, float)) or not math.isfinite(classical_error):
        errors.append("invalid_classical_error")
    if not isinstance(prediction_error, (int, float)) or not math.isfinite(prediction_error):
        errors.append("invalid_prediction_error")
    if not errors:
        if not math.isclose(
            classical_error,
            abs(pred["classical"] - pred["resolved_actual"]),
            rel_tol=0.0,
            abs_tol=5e-7,
        ):
            errors.append("classical_error_mismatch")
        if not math.isclose(
            prediction_error,
            abs(pred["prediction"] - pred["resolved_actual"]),
            rel_tol=0.0,
            abs_tol=5e-7,
        ):
            errors.append("prediction_error_mismatch")
    created = pred.get("created_at_ms")
    target = pred.get("target_at_ms")
    resolved = pred.get("resolved_at_ms")
    if not all(isinstance(value, (int, float)) for value in (created, target, resolved)):
        errors.append("invalid_timestamps")
    else:
        if not created < target <= resolved:
            errors.append("timestamp_order")
        if isinstance(horizon_s, (int, float)) and not math.isclose(
            target - created,
            float(horizon_s) * 1000,
            rel_tol=0.0,
            abs_tol=1.0,
        ):
            errors.append("horizon_mismatch")
    if pred.get("forward_window_start_ms") != created:
        errors.append("forward_window_start_mismatch")
    if pred.get("forward_window_end_ms") != target:
        errors.append("forward_window_end_mismatch")
    if pred.get("score_eligible") is not True:
        errors.append("score_not_explicitly_true")
    flags = list(pred.get("entry_quality_flags", [])) + list(
        pred.get("exit_quality_flags", [])
    )
    if any(flag in DISQUALIFYING_QUALITY_FLAGS for flag in flags):
        errors.append("disqualifying_quality_flag")
    return sorted(set(errors))


def _dedupe_predictions(predictions):
    """Keep the latest record per forecast id (resume-safe)."""
    by_id = {}
    for pred in predictions:
        forecast_id = pred.get("id")
        if forecast_id is None:
            by_id[id(pred)] = pred
            continue
        existing = by_id.get(forecast_id)
        if existing is None:
            by_id[forecast_id] = pred
            continue
        if pred.get("status") == "resolved" and existing.get("status") != "resolved":
            by_id[forecast_id] = pred
    return list(by_id.values())


def _normalize_results(data):
    if isinstance(data, dict) and data.get("schema_version") in SCHEMA_VERSIONS:
        predictions = _dedupe_predictions(data.get("predictions", []))
        resolved = [p for p in predictions if p.get("status") == "resolved"]
        if data.get("schema_version") in (5, 6):
            resolved = [
                p for p in resolved
                if p.get("resolved_label") == "forward_window"
                and p.get("label_capture_complete") is True
            ]
        if data.get("schema_version") == 6:
            resolved = [p for p in resolved if p.get("score_eligible") is True]
        elif any("score_eligible" in p for p in resolved):
            resolved = [p for p in resolved if p.get("score_eligible", True)]
        meta = dict(data)
        meta["predictions"] = predictions
        if data.get("schema_version") == 6:
            valid = []
            validation_exclusions = Counter()
            for pred in resolved:
                row_errors = _v6_row_errors(pred, data.get("horizon_s"))
                if row_errors:
                    validation_exclusions.update(row_errors)
                else:
                    valid.append(pred)
            resolved = valid
            meta["_validation_exclusions"] = dict(validation_exclusions)
        return resolved, meta
    return data, None


def _reporting_tier(n):
    if n < 30:
        return "diagnostics"
    if n < MIN_SIGNIFICANCE_N:
        return "exploratory"
    return "primary"


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


def _metrics_for_results(results):
    fmt = _detect_format(results)
    if fmt == "ensemble":
        key = "prediction" if "prediction" in results[0] else "ensemble"
        actual_key = "resolved_actual" if "resolved_actual" in results[0] else "actual"
        m_errs = [abs(r[key] - r[actual_key]) for r in results]
    elif fmt == "quantum_prediction":
        key = "prediction"
        actual_key = "resolved_actual" if "resolved_actual" in results[0] else "actual"
        m_errs = [abs(r[key] - r[actual_key]) for r in results]
    else:
        actual_key = "resolved_actual" if "resolved_actual" in results[0] else "actual"
        m_errs = [abs(r["quantum"] - r[actual_key]) for r in results]

    c_errs = [abs(r["classical"] - r[actual_key]) for r in results]
    wins = sum(1 for ce, me in zip(c_errs, m_errs) if me < ce)
    mean_c = statistics.mean(c_errs)
    mean_m = statistics.mean(m_errs)
    improvement = (mean_c - mean_m) / mean_c * 100 if mean_c > 0 else 0
    return {
        "n": len(results),
        "mean_c": mean_c,
        "mean_q": mean_m,
        "improvement": improvement,
        "wins": wins,
        "win_rate": wins / len(results) if results else 0,
    }


def _print_segment_summary(label, results):
    if len(results) < 1:
        return None
    m = _metrics_for_results(results)
    print(f"  [{label}] n={m['n']}  c_err={m['mean_c']:.4f}  q_err={m['mean_q']:.4f}  "
          f"wins={m['wins']}/{m['n']}")
    if m["n"] >= 30:
        print(f"  [{label}] improvement={m['improvement']:+.2f}%")
    return m


def analyze(results, min_resolved=3, show_segments=True):
    results, meta_doc = _normalize_results(results)
    if meta_doc is not None:
        version = meta_doc.get("schema_version", "?")
        total_predictions = len(meta_doc.get("predictions", []))
        pending = sum(1 for p in meta_doc.get("predictions", []) if p.get("status") == "pending")
        observations = len(meta_doc.get("observations", []))
        print(f"  Schema:         v{version} resolve-later")
        if meta_doc.get("run_id"):
            print(f"  Run ID:         {meta_doc['run_id']}")
        if meta_doc.get("config_hash"):
            print(f"  Config hash:    {meta_doc['config_hash']}")
        if meta_doc.get("status"):
            print(f"  Run status:     {meta_doc['status']} ({meta_doc.get('stop_reason', 'n/a')})")
        if meta_doc.get("model_version"):
            print(f"  Model version:  {meta_doc['model_version']}")
        if meta_doc.get("ensemble_weights"):
            w = meta_doc["ensemble_weights"]
            print(f"  Ensemble w:     q={w[0]:.2f} v={w[1]:.2f}")
        print(f"  Observations:   {observations}")
        resolved_total = sum(
            1 for p in meta_doc.get("predictions", []) if p.get("status") == "resolved"
        )
        excluded = resolved_total - len(results)
        reasons = Counter()
        for pred in meta_doc.get("predictions", []):
            if pred.get("status") != "resolved" or pred in results:
                continue
            reasons.update(pred.get("entry_quality_flags", []))
            reasons.update(pred.get("exit_quality_flags", []))
            if pred.get("resolved_label") != "forward_window":
                reasons.update(["non_forward_label"])
            if pred.get("label_capture_complete") is not True:
                reasons.update(["incomplete_capture"])
        print(f"  Predictions:    {total_predictions} total, {pending} pending, "
              f"{resolved_total} resolved, {len(results)} eligible, {excluded} excluded")
        if reasons:
            print(f"  Exclusions:     {dict(reasons)}")
        validation_exclusions = meta_doc.get("_validation_exclusions", {})
        if validation_exclusions:
            print(f"  Invalid rows:   {validation_exclusions}")
        print(f"  Horizon:        {meta_doc.get('horizon_s')}s")

    n = len(results)
    if n < min_resolved:
        print(f"  Only {n} resolved data points — need at least {min_resolved} for analysis")
        return None

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
    ties = sum(1 for ce, me in zip(c_errs, m_errs) if me == ce)
    losses = n - wins - ties

    mean_c = statistics.mean(c_errs)
    mean_m = statistics.mean(m_errs)
    improvement = (mean_c - mean_m) / mean_c * 100 if mean_c > 0 else 0
    tier = _reporting_tier(n)
    acts = [r[actual_key] for r in results if actual_key in r]
    null_mae = statistics.mean(abs(0.5 - a) for a in acts) if acts else None

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
    if null_mae is not None:
        print(f"  Null baseline:  MAE(constant 0.5)={null_mae:.4f}  "
              f"(classical {'<' if mean_c < null_mae else '>='} null, "
              f"{model_name.lower()} {'<' if mean_m < null_mae else '>='} null)")
    if tier == "diagnostics":
        print("  Status:         diagnostics only (n<30)")
    elif tier == "exploratory":
        print(f"  Status:         exploratory (30<=n<{MIN_SIGNIFICANCE_N}) — no significance claim")
        print(f"  Improvement:    {improvement:+.2f}%")
        print(f"  {model_name} wins:   {wins}/{n} ({wins/n*100:.1f}%)")
        print(f"  Losses:         {losses}/{n} ({losses/n*100:.1f}%)")
        print(f"  Ties:           {ties}/{n} ({ties/n*100:.1f}%)")
    else:
        print(f"  Status:         primary analysis (n>={MIN_SIGNIFICANCE_N})")
        print(f"  Improvement:    {improvement:+.2f}%")
        print(f"  {model_name} wins:   {wins}/{n} ({wins/n*100:.1f}%)")
        print(f"  Losses:         {losses}/{n} ({losses/n*100:.1f}%)")
        print(f"  Ties:           {ties}/{n} ({ties/n*100:.1f}%)")
    if q_errs is not m_errs:
        raw_wins = sum(1 for ce, qe in zip(c_errs, q_errs) if qe < ce)
        raw_mean = statistics.mean(q_errs)
        print(f"  {raw_name} err: {raw_mean:.4f}")
        if tier != "diagnostics":
            print(f"  {raw_name} wins:{raw_wins}/{n} ({raw_wins/n*100:.1f}%)")

    preds = [r[key] for r in results if key and key in r]
    acts = [r[actual_key] for r in results if actual_key in r and key and key in r]
    if preds and acts:
        bias = statistics.mean(p - a for p, a in zip(preds, acts))
        print(f"  Bias pred-act:  {bias:+.4f}")

    saturated = [r for r in results if r.get(key, 0) >= 0.99]
    if saturated:
        sat_wins = sum(
            1 for r in saturated
            if r.get("prediction_error", 999) < r.get("classical_error", 999)
        )
        print(f"  Saturation:     {len(saturated)}/{n} at q>=0.99  wins={sat_wins}/{len(saturated)}")

    deltas = [r.get("delta") for r in results]
    delta_none = sum(d is None for d in deltas)
    valid_deltas = [d for d in deltas if d is not None]
    print(f"  Delta None:     {delta_none}/{n} ({delta_none/n*100:.1f}%)")
    if valid_deltas:
        print(f"  Delta range:    {min(valid_deltas):.3f} → {max(valid_deltas):.3f}")
        print(f"  Delta mean:     {statistics.mean(valid_deltas):.3f}")

    sources = Counter(r.get("delta_source", r.get("data_source", "legacy")) for r in results)
    fallbacks = Counter(r.get("fallback_reason", "legacy") for r in results)
    buckets = Counter(r.get("bucket_feature", "unknown") for r in results)
    print(f"  Delta sources:  {dict(sources)}")
    print(f"  Fallbacks:      {dict(fallbacks)}")
    if any(b != "unknown" for b in buckets):
        print(f"  Bucket feature: {dict(buckets)}")

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
        print(f"  Price sim:      {len(trades)} long (diagnostic — uses price move, not buy_ratio target)")
        print(f"  Price sim hit:  {wins_ret}/{len(trades)} ({wins_ret/len(trades)*100:.1f}%)  "
              f"avg_net={statistics.mean(returns):+.5f}  pf={pf:.4f}")
    non_fallback = [r for r in eligible if r.get("fallback_reason") == "none"]
    born_rate = len(non_fallback) / len(eligible) * 100 if eligible else 0.0
    print(f"  Born active:    {len(non_fallback)}/{len(eligible)} eligible ({born_rate:.1f}%)")

    labels = Counter(r.get("resolved_label", "unknown") for r in eligible)
    if labels:
        fw = labels.get("forward_window", 0)
        print(f"  Resolved label: {dict(labels)}  forward_window={fw}/{len(eligible)} ({100*fw/len(eligible):.1f}%)")
    short_fw = sum(1 for r in eligible if "short_forward_window" in r.get("exit_quality_flags", []))
    if short_fw:
        print(f"  short_forward_window: {short_fw}/{len(eligible)} (disqualified from scoring)")

    if show_segments and n >= 30:
        print(f"  --- Segmented (n>={30}) ---")
        _print_segment_summary("all_eligible", results)
        born_only = [r for r in results if r.get("fallback_reason") == "none"]
        _print_segment_summary("born_active_only", born_only)
        for reason in ("flat_history", "single_bucket", "insufficient_history", "destructive_interference", "saturation_gate"):
            subset = [r for r in results if r.get("fallback_reason") == reason]
            if subset:
                _print_segment_summary(reason, subset)

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
        from reality_check import paired_loss_test
        if tier == "primary":
            rc = paired_loss_test(c_errs, m_errs, n_bootstrap=10000, live=True)
            print(f"  Paired block test raw: {rc.get('raw_p_value', 'N/A')}  "
                  f"Bonferroni: {rc.get('corrected_p_value', 'N/A')}  "
                  f"→ {rc.get('interpretation', 'N/A')}")
        elif tier == "exploratory":
            print(f"  Paired block test: withheld until n>={MIN_SIGNIFICANCE_N}")
    except ImportError:
        pass

    summary = _metrics_for_results(results)
    summary["errors_c"] = list(c_errs)
    summary["errors_q"] = list(m_errs)
    if meta_doc:
        summary.update({
            "config_hash": meta_doc.get("config_hash"),
            "experiment_id": meta_doc.get("experiment_id"),
            "model_version": meta_doc.get("model_version"),
            "implementation_revision": meta_doc.get("implementation_revision"),
            "acquisition_policy_version": meta_doc.get("acquisition_policy_version"),
            "mode": meta_doc.get("mode"),
            "horizon_s": meta_doc.get("horizon_s"),
        })
    return summary


def discover_paths(args):
    if args.paths:
        expanded = []
        for p in args.paths:
            expanded.extend(glob.glob(p))
        paths = sorted(set(expanded))
    else:
        paths = sorted(glob.glob(os.path.join(RESULTS_DIR, "*.json")))
    paths = [p for p in paths if os.path.basename(p) != "state.json"]
    if not args.paths:
        paths = [p for p in paths if "_archive" not in p.replace("\\", "/")]
    return paths


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Analyze live pipeline JSON results")
    parser.add_argument("paths", nargs="*", help="Result JSON paths (default: _live_results/*.json)")
    parser.add_argument("--schema-version", type=int, choices=list(SCHEMA_VERSIONS), default=6,
                        help="Only analyze this schema version (default: 6 current corpus)")
    parser.add_argument("--run-id", default=None, help="Only analyze matching run_id")
    parser.add_argument("--exclude-collector", action="store_true",
                        help="Skip collected_* list-format JSON files")
    parser.add_argument(
        "--allow-pre-hardening-v6",
        action="store_true",
        help="Allow historical schema-v6 files without the current v6r1 identity",
    )
    parser.add_argument("--min-resolved", type=int, default=3,
                        help="Minimum resolved eligible predictions per file (default: 3)")
    parser.add_argument("--aggregate-min-resolved", type=int, default=30,
                        help="Minimum total n before printing aggregate improvement (default: 30)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    paths = discover_paths(args)

    if not paths:
        print(f"No result files found in {RESULTS_DIR}")
        print(f"Usage: {sys.argv[0]} [--schema-version 6] [path/to/results.json ...]")
        return

    all_summaries = []
    skipped_legacy = 0

    for path in paths:
        try:
            data = load_results(path)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"\n  SKIP {path}: {exc}")
            continue

        ok, reason = should_include_path(path, data, args)
        if not ok:
            skipped_legacy += 1
            print(f"\n  SKIP {os.path.basename(path)}: {reason}")
            continue

        if not _is_result_document(data):
            print(f"\n  SKIP {os.path.basename(path)}: not a result document")
            continue

        print(f"\n{'=' * 55}")
        print(f"  FILE: {os.path.basename(path)}")
        print(f"{'=' * 55}")
        summary = analyze(data, min_resolved=args.min_resolved)
        if summary:
            summary["path"] = path
            all_summaries.append(summary)

    if args.schema_version in (5, 6) and skipped_legacy:
        print(f"\n  NOTE: skipped {skipped_legacy} file(s) not matching --schema-version {args.schema_version}")

    if len(all_summaries) > 1:
        groups = {}
        for summary in all_summaries:
            key = (
                summary.get("config_hash"),
                summary.get("mode"),
                summary.get("horizon_s"),
                summary.get("model_version"),
                summary.get("implementation_revision"),
                summary.get("acquisition_policy_version"),
            )
            groups.setdefault(key, []).append(summary)

        for key, summaries in groups.items():
            print(f"\n{'=' * 55}")
            print("  AGGREGATE — compatible configuration")
            print(f"{'=' * 55}")
            if key[0]:
                print(f"  Config hash:        {key[0]}")
            total_n = sum(s["n"] for s in summaries)
            total_wins = sum(s["wins"] for s in summaries)
            weighted_c = sum(s["mean_c"] * s["n"] for s in summaries) / total_n if total_n else 0
            weighted_q = sum(s["mean_q"] * s["n"] for s in summaries) / total_n if total_n else 0
            tier = _reporting_tier(total_n)
            print(f"  Files:              {len(summaries)}")
            print(f"  Total observations: {total_n}")
            print(f"  Weighted classical: {weighted_c:.4f}")
            print(f"  Weighted quantum:   {weighted_q:.4f}")
            if tier == "diagnostics":
                print("  Status: diagnostics only until n>=30")
            elif tier == "exploratory":
                imprv = (weighted_c - weighted_q) / weighted_c * 100 if weighted_c else 0
                print(f"  Status: exploratory (no significance claim until n>={MIN_SIGNIFICANCE_N})")
                print(f"  Improvement:        {imprv:+.2f}%")
                print(f"  Total wins:         {total_wins}/{total_n} ({total_wins/total_n*100:.1f}%)")
            else:
                imprv = (weighted_c - weighted_q) / weighted_c * 100 if weighted_c else 0
                print("  Status: primary analysis")
                print(f"  Improvement:        {imprv:+.2f}%")
                print(f"  Total wins:         {total_wins}/{total_n} ({total_wins/total_n*100:.1f}%)")
                from reality_check import paired_loss_test
                errors_c = [
                    value for summary in summaries for value in summary["errors_c"]
                ]
                errors_q = [
                    value for summary in summaries for value in summary["errors_q"]
                ]
                result = paired_loss_test(errors_c, errors_q, live=True)
                print(f"  Paired block p:     {result['corrected_p_value']}")


if __name__ == "__main__":
    main()
