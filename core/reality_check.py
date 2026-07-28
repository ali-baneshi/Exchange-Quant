#!/usr/bin/env python3

"""Paired moving-block mean-loss inference with a legacy compatibility wrapper."""

import warnings

from validation import paired_moving_block_test, bonferroni_correct
from config import N_HYPOTHESES_TOTAL, N_HYPOTHESES_LIVE


def paired_loss_test(errors_c, errors_q, n_bootstrap=10000, seed=42, live=False):
    """
    Paired moving-block bootstrap on model-minus-classical mean loss.

    H0: quantum_win_rate <= 0.5  (quantum does not outperform)
    HA: quantum_win_rate > 0.5   (quantum outperforms)

    Returns dict with win_rate, raw_p_value, corrected_p_value, interpretation.
    """
    if not errors_c or not errors_q or len(errors_c) != len(errors_q):
        return {"error": "Need equal-length error arrays"}

    n = len(errors_c)
    wins = sum(1 for ec, eq in zip(errors_c, errors_q) if eq < ec)
    ties = sum(1 for ec, eq in zip(errors_c, errors_q) if ec == eq)
    losses = n - wins - ties
    win_rate = wins / n

    test_result = paired_moving_block_test(errors_c, errors_q, n_bootstrap, seed)
    raw_p = test_result["p_value"]
    n_tests = N_HYPOTHESES_LIVE if live else N_HYPOTHESES_TOTAL
    corrected_p, sig_005, sig_001 = bonferroni_correct(raw_p, n_tests=n_tests)

    if sig_001:
        interpretation = "HIGHLY_SIGNIFICANT"
    elif sig_005:
        interpretation = "SIGNIFICANT"
    elif corrected_p < 0.10:
        interpretation = "MARGINAL"
    else:
        interpretation = "NOT_SIGNIFICANT"

    return {
        "n_observations": n,
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "win_rate": round(win_rate, 4),
        "raw_p_value": round(raw_p, 4),
        "corrected_p_value": round(corrected_p, 4),
        "n_tests_corrected": n_tests,
        "n_bootstrap": n_bootstrap,
        "block_len": test_result["block_len"],
        "mean_loss_diff": round(test_result["mean_loss_diff"], 6),
        "mean_loss_diff_ci_95": [
            round(test_result["ci_low"], 6),
            round(test_result["ci_high"], 6),
        ],
        "test_method": test_result["method"],
        "interpretation": interpretation,
    }


def reality_check(errors_c, errors_q, n_bootstrap=10000, seed=42, live=False):
    warnings.warn(
        "reality_check() is deprecated; use paired_loss_test()",
        DeprecationWarning,
        stacklevel=2,
    )
    return paired_loss_test(
        errors_c,
        errors_q,
        n_bootstrap=n_bootstrap,
        seed=seed,
        live=live,
    )


def main():
    c_errs = [
        0.093, 0.088, 0.084, 0.070, 0.069, 0.068, 0.068, 0.068,
        0.067, 0.067, 0.067, 0.067, 0.067, 0.067, 0.067, 0.067,
        0.067, 0.067, 0.067, 0.067, 0.067, 0.067, 0.067, 0.067,
        0.067, 0.067, 0.067, 0.067, 0.067, 0.067,
        0.034, 0.049, 0.059, 0.063, 0.062, 0.054, 0.056,
        0.109, 0.021, 0.022, 0.042, 0.266, 0.162, 0.231,
    ]
    q_errs = [
        0.356, 0.198, 0.160, 0.122, 0.084, 0.047, 0.040, 0.033,
        0.000, 0.000, 0.000, 0.000, 0.000, 0.000, 0.000, 0.000,
        0.000, 0.000, 0.000, 0.000, 0.000, 0.000, 0.000, 0.000,
        0.000, 0.000, 0.000, 0.000, 0.000, 0.000,
        0.033, 0.031, 0.029, 0.026, 0.024, 0.022, 0.020,
        0.184, 0.280, 0.293, 0.307, 0.020, 0.398, 0.064,
    ]

    results = paired_loss_test(c_errs, q_errs, n_bootstrap=10000)

    print()
    print("=" * 60)
    print("  PAIRED MOVING-BLOCK LOSS TEST — Model vs Classical")
    print("=" * 60)
    print(f"  Observations:       {results['n_observations']}")
    print(f"  Quantum wins:       {results['wins']}  ({results['wins']/results['n_observations']*100:.1f}%)")
    print(f"  Losses:             {results['losses']}  ({results['losses']/results['n_observations']*100:.1f}%)")
    print(f"  Ties:               {results['ties']}")
    print(f"  Win rate:           {results['win_rate']:.4f}")
    print(f"  Raw bootstrap p:    {results['raw_p_value']:.4f}")
    print(f"  Bonferroni p:       {results['corrected_p_value']:.4f}  "
          f"(corrected for {results['n_tests_corrected']} tests)")
    print(f"  Interpretation:     {results['interpretation']}")
    if results['interpretation'] == 'HIGHLY_SIGNIFICANT':
        print("  -> Model outperforms classical (Bonferroni-corrected p<0.01)")
    elif results['interpretation'] == 'SIGNIFICANT':
        print("  -> Model outperforms classical (Bonferroni-corrected p<0.05)")
    else:
        print("  -> Not enough evidence after correction")
    print()


if __name__ == "__main__":
    main()
