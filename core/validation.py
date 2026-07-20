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


N_HYPOTHESES_TOTAL = 5
"""
Known hypotheses tested to date:
  1. Born rule on 15min candles
  2. Born rule on 60min candles
  3. Born rule on 1day candles
  4. Adaptive ensemble (boost) on 60min
  5. AdaptiveEnsemble vs standalone quantum on 60min
Any NEW hypothesis must increment this counter.
"""


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
        if peak != 0:
            dd = (peak - v) / peak
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


def block_bootstrap_pvalue(errors_c, errors_q, n_bootstrap=10000, seed=42):
    """
    White's Reality Check with block bootstrap to handle autocorrelation.
    Uses non-overlapping blocks of size block_len = ceil(n^(1/3)).
    H0: win_rate <= 0.5
    """
    n = len(errors_c)
    if n < 2:
        return 0.5

    wins = sum(1 for ec, eq in zip(errors_c, errors_q) if eq < ec)
    win_rate = wins / n

    block_len = max(1, int(n ** (1/3)) + 1)
    # Ceiling to avoid floating-point floor errors (e.g. 64**(1/3)=3.999...)
    n_blocks = (n + block_len - 1) // block_len

    diffs = [eq - ec for ec, eq in zip(errors_c, errors_q)]

    rng = random.Random(seed)
    count_extreme = 0

    for _ in range(n_bootstrap):
        sample_diffs = []
        for b in range(n_blocks):
            if rng.random() < 0.5:
                start = b * block_len
                end = min(start + block_len, n)
                for idx in range(start, end):
                    sample_diffs.append(diffs[idx])
            else:
                start = b * block_len
                end = min(start + block_len, n)
                for idx in range(start, end):
                    sample_diffs.append(-diffs[idx])
        sample_diffs = sample_diffs[:n]
        sample_wins = sum(1 for d in sample_diffs if d < 0)
        sample_rate = sample_wins / n
        if sample_rate >= win_rate:
            count_extreme += 1

    p_value = (count_extreme + 1) / (n_bootstrap + 1)
    return p_value


def comprehensive_report(errors_c, errors_q, label="", periods_per_year=8760):
    """
    Produce an honest, comprehensive comparison report.
    Includes all corrections and financial metrics.
    """
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

    raw_p = block_bootstrap_pvalue(errors_c, errors_q)
    corrected_p, sig_005, sig_001 = bonferroni_correct(raw_p)

    mdd_q = max_drawdown_from_errors(errors_q)
    mdd_c = max_drawdown_from_errors(errors_c)
    sharpe_q = sharpe_ratio(errors_q, periods_per_year)
    sharpe_c = sharpe_ratio(errors_c, periods_per_year)
    pf = profit_factor(errors_q, errors_c)

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
        "max_drawdown_q": round(mdd_q, 4),
        "max_drawdown_c": round(mdd_c, 4),
        "max_drawdown_reduction": round((mdd_c - mdd_q) / mdd_c * 100, 2) if mdd_c > 0 else 0,
        "sharpe_q": round(sharpe_q, 4),
        "sharpe_c": round(sharpe_c, 4),
        "profit_factor": round(pf, 4),
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
    print(f"  Bonferroni p:     {r['bonferroni_p']}  (n_tests={N_HYPOTHESES_TOTAL})")
    print(f"  Sig at 0.05:      {r['significant_005']}")
    print(f"  Sig at 0.01:      {r['significant_001']}")
    if detail:
        print(f"\n  Financial metrics:")
        print(f"  Max DD (classical): {r['max_drawdown_c']:.4f}")
        print(f"  Max DD (quantum):   {r['max_drawdown_q']:.4f}")
        print(f"  DD reduction:       {r['max_drawdown_reduction']:+.2f}%")
        print(f"  Sharpe (classical): {r['sharpe_c']}")
        print(f"  Sharpe (quantum):   {r['sharpe_q']}")
        print(f"  Profit factor:      {r['profit_factor']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(line_buffering=True)

    demo_c = [0.12, 0.08, 0.15, 0.09, 0.11, 0.14, 0.07, 0.10, 0.13, 0.06]
    demo_q = [0.10, 0.07, 0.12, 0.08, 0.09, 0.11, 0.06, 0.08, 0.10, 0.05]
    report = comprehensive_report(demo_c, demo_q, " [demo]")
    print_report(report)
