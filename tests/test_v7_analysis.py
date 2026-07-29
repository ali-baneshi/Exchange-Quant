import math

import pytest

from exchange_q.analysis import paired_hac_test, required_sample_size, score_baselines, score_rows


def _row(probability, buys, total):
    return {
        "forecast": {
            "probability_buy": probability,
            "diagnostics": {
                "baseline_probabilities": {"baseline": 0.5},
            },
        },
        "label": {"buy_count": buys, "trade_count": total},
    }


def test_proper_scores_reward_better_probabilities():
    calibrated = score_rows([_row(0.65, 70, 100), _row(0.35, 30, 100), _row(0.55, 58, 100)] * 4)
    weak = score_rows([_row(0.5, 70, 100), _row(0.5, 30, 100), _row(0.5, 58, 100)] * 4)
    assert calibrated.negative_log_likelihood < weak.negative_log_likelihood
    assert calibrated.brier < weak.brier


def test_hac_test_detects_consistent_improvement():
    result = paired_hac_test([0.3] * 30, [0.2] * 30)
    assert result["mean_loss_difference"] < 0
    assert result["one_sided_p_value"] < 0.05


def test_baseline_scores_use_the_same_labels():
    rows = [_row(0.7, 70, 100), _row(0.3, 30, 100)] * 5
    reports = score_baselines(rows)
    assert reports["baseline"].n == len(rows)


def test_power_target_increases_with_autocorrelation():
    independent = required_sample_size(-0.01, 0.05, 0.0)
    dependent = required_sample_size(-0.01, 0.05, 0.7)
    assert dependent > independent


def test_invalid_probability_is_rejected_instead_of_clipped():
    with pytest.raises(ValueError):
        score_rows([_row(1.01, 1, 2)])


def test_impossible_certain_forecast_has_infinite_log_loss():
    report = score_rows([_row(1.0, 0, 2)])
    assert math.isinf(report.negative_log_likelihood)
