#!/usr/bin/env python3

"""
Holistic validation framework for the Exchange-Q project.

Provides:
  - Walk-forward cross-validation
  - Held-out final evaluation
  - Bonferroni correction
  - Max drawdown, sharpe-like metrics
  - Autocorrelation-aware bootstrap
"""

import math
import statistics
import random

from config import N_HYPOTHESES_TOTAL, N_HYPOTHESES_LIVE


def _validate_paired_errors(errors_c, errors_q):
    if len(errors_c) != len(errors_q):
        raise ValueError("Paired error arrays must have equal length")
    for label, values in (("classical", errors_c), ("model", errors_q)):
        for value in values:
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{label} errors must contain finite numbers")
            if value < 0:
                raise ValueError(f"{label} errors must be non-negative")


def _percentile(values, probability):
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def bonferroni_correct(p_value, n_tests=N_HYPOTHESES_TOTAL):
    """
    Adjust p-value with Bonferroni correction.
    Returns (corrected_p, significant_at_005, significant_at_001).
    """
    corrected = min(1.0, p_value * n_tests)
    return corrected, corrected < 0.05, corrected < 0.01


def max_drawdown_from_errors(errors, direction=1):
    if not errors:
        return 0.0
    # Reward centered at 0.5 (random baseline): positive for good predictions,
    # negative for bad ones. Produces a real equity curve that can go up/down.
    equity = []
    acc = 0.0
    for e in errors:
        reward = (0.5 - e) * direction
        acc += reward
        equity.append(acc)
    peak = equity[0]
    mdd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > mdd:
                mdd = dd
        elif peak < 0 and v < peak:
            dd = (peak - v) / abs(peak)
            if dd > mdd:
                mdd = dd
    return mdd


def sharpe_ratio(errors, periods_per_year=8760):
    """
    Compute a Sharpe-like ratio from error-based rewards.
    Treats (max_error - error) as per-period return.
    periods_per_year: 8760 for hourly data, 35040 for 15min, 365 for daily.
    """
    if len(errors) < 2:
        return 0.0
    max_err = max(errors)
    if max_err == 0:
        return 0.0
    returns = [(max_err - e) / max_err for e in errors]
    mean_ret = statistics.mean(returns)
    std_ret = statistics.stdev(returns) if len(returns) > 1 else 1e-8
    if std_ret == 0:
        return 0.0
    sharpe = mean_ret / std_ret * math.sqrt(periods_per_year)
    return sharpe


def profit_factor(errors_q, errors_c):
    """
    Profit factor from error comparison.
    Win = quantum error < classical error (treated as "profit" event).
    Loss = quantum error > classical error (treated as "loss" event).
    Returns profit_factor = sum(wins) / sum(losses) if losses > 0 else inf.
    """
    win_sum = 0.0
    loss_sum = 0.0
    for eq, ec in zip(errors_q, errors_c):
        if eq < ec:
            win_sum += 1.0
        elif eq > ec:
            loss_sum += 1.0
    if loss_sum == 0:
        return float('inf') if win_sum > 0 else 1.0
    return win_sum / loss_sum


def paired_moving_block_test(errors_c, errors_q, n_bootstrap=10000, seed=42):
    """
    One-sided paired moving-block bootstrap on mean loss differential.

    loss_diff = model_error - classical_error
    H0: E[loss_diff] >= 0
    HA: E[loss_diff] < 0
    """
    _validate_paired_errors(errors_c, errors_q)
    n = len(errors_c)
    if n < 2:
        return {
            "p_value": 0.5,
            "mean_loss_diff": 0.0 if not errors_c else errors_q[0] - errors_c[0],
            "ci_low": 0.0,
            "ci_high": 0.0,
            "block_len": 1,
            "n_bootstrap": n_bootstrap,
            "method": "paired_moving_block_bootstrap_mean_loss",
        }

    block_len = max(1, math.ceil(n ** (1 / 3)))
    n_blocks = (n + block_len - 1) // block_len
    diffs = [eq - ec for ec, eq in zip(errors_c, errors_q)]
    observed_mean = statistics.mean(diffs)
    centered = [value - observed_mean for value in diffs]

    rng = random.Random(seed)
    count_extreme = 0
    bootstrap_means = []

    for _ in range(n_bootstrap):
        sample_diffs = []
        raw_sample = []
        for _block in range(n_blocks):
            start = rng.randrange(n)
            for offset in range(block_len):
                idx = (start + offset) % n
                sample_diffs.append(centered[idx])
                raw_sample.append(diffs[idx])
        null_mean = statistics.mean(sample_diffs[:n])
        raw_mean = statistics.mean(raw_sample[:n])
        bootstrap_means.append(raw_mean)
        if null_mean <= observed_mean:
            count_extreme += 1

    p_value = (count_extreme + 1) / (n_bootstrap + 1)
    return {
        "p_value": p_value,
        "mean_loss_diff": observed_mean,
        "ci_low": _percentile(bootstrap_means, 0.025),
        "ci_high": _percentile(bootstrap_means, 0.975),
        "block_len": block_len,
        "n_bootstrap": n_bootstrap,
        "method": "paired_moving_block_bootstrap_mean_loss",
    }


def block_bootstrap_pvalue(errors_c, errors_q, n_bootstrap=10000, seed=42):
    """Backward-compatible p-value wrapper for paired_moving_block_test."""
    return paired_moving_block_test(
        errors_c, errors_q, n_bootstrap=n_bootstrap, seed=seed
    )["p_value"]


def comprehensive_report(errors_c, errors_q, label="", periods_per_year=8760, live=False):
    """
    Produce an honest, comprehensive comparison report.
    Includes all corrections and financial metrics.
    """
    _validate_paired_errors(errors_c, errors_q)
    n = len(errors_c)
    if n == 0:
        return {}

    wins = sum(1 for ec, eq in zip(errors_c, errors_q) if eq < ec)
    ties = sum(1 for ec, eq in zip(errors_c, errors_q) if ec == eq)
    losses = n - wins - ties
    win_rate = wins / n

    mean_c = statistics.mean(errors_c)
    mean_q = statistics.mean(errors_q)
    imprv = (mean_c - mean_q) / mean_c * 100 if mean_c != 0 else 0

    test_result = paired_moving_block_test(errors_c, errors_q)
    raw_p = test_result["p_value"]
    n_tests = N_HYPOTHESES_LIVE if live else N_HYPOTHESES_TOTAL
    corrected_p, sig_005, sig_001 = bonferroni_correct(raw_p, n_tests=n_tests)

    return {
        "label": label,
        "n": n,
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "win_rate": round(win_rate, 4),
        "mean_c": round(mean_c, 4),
        "mean_q": round(mean_q, 4),
        "improvement_pct": round(imprv, 2),
        "raw_p_value": round(raw_p, 4),
        "bonferroni_p": round(corrected_p, 4),
        "significant_005": sig_005,
        "significant_001": sig_001,
        "n_tests_corrected": n_tests,
        "mean_loss_diff": round(test_result["mean_loss_diff"], 6),
        "mean_loss_diff_ci_95": [
            round(test_result["ci_low"], 6),
            round(test_result["ci_high"], 6),
        ],
        "block_len": test_result["block_len"],
        "n_bootstrap": test_result["n_bootstrap"],
        "test_method": test_result["method"],
        "financial_metrics_valid": False,
    }


def print_report(r, detail=True):
    """Pretty-print a comprehensive report dict."""
    if not r:
        print("  (empty results)")
        return
    print(f"\n{'='*60}")
    print(f"  VALIDATION REPORT{r['label']}")
    print(f"{'='*60}")
    print(f"  Observations:     {r['n']}")
    print(f"  Classical err:    {r['mean_c']}")
    print(f"  Quantum err:      {r['mean_q']}")
    print(f"  Improvement:      {r['improvement_pct']:+.2f}%")
    print(f"  Win rate:         {r['win_rate']:.2%}  ({r['wins']}/{r['n']})")
    print(f"  Ties:             {r['ties']}")
    print(f"  Raw p-value:      {r['raw_p_value']}")
    n_tests = r.get("n_tests_corrected", N_HYPOTHESES_TOTAL)
    print(f"  Bonferroni p:     {r['bonferroni_p']}  (n_tests={n_tests})")
    print(f"  Sig at 0.05:      {r['significant_005']}")
    print(f"  Sig at 0.01:      {r['significant_001']}")
    if detail:
        ci_low, ci_high = r["mean_loss_diff_ci_95"]
        print(f"\n  Paired loss inference:")
        print(f"  Mean model-classical loss: {r['mean_loss_diff']:+.6f}")
        print(f"  95% block-bootstrap CI:    [{ci_low:+.6f}, {ci_high:+.6f}]")
        print(f"  Block length:              {r['block_len']}")
        print(f"  Method:                    {r['test_method']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(line_buffering=True)

    demo_c = [0.12, 0.08, 0.15, 0.09, 0.11, 0.14, 0.07, 0.10, 0.13, 0.06]
    demo_q = [0.10, 0.07, 0.12, 0.08, 0.09, 0.11, 0.06, 0.08, 0.10, 0.05]
    report = comprehensive_report(demo_c, demo_q, " [demo]")
    print_report(report)
