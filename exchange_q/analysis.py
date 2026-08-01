from __future__ import annotations

import math
import warnings
from dataclasses import dataclass

import numpy as np
import statsmodels.api as sm
from scipy.special import xlogy
from statsmodels.tools.sm_exceptions import PerfectSeparationWarning


@dataclass(frozen=True)
class ScoreReport:
    n: int
    total_trades: int
    negative_log_likelihood: float
    brier: float
    mae: float
    calibration_intercept: float | None
    calibration_slope: float | None


def score_rows(rows: list[dict]) -> ScoreReport:
    if not rows:
        raise ValueError("eligible rows are required")
    probabilities = np.array([row["forecast"]["probability_buy"] for row in rows], dtype=float)
    return _score_probabilities(rows, probabilities)


def score_baselines(rows: list[dict]) -> dict[str, ScoreReport]:
    if not rows:
        raise ValueError("eligible rows are required")
    baseline_names = set.intersection(
        *(
            set(row["forecast"].get("diagnostics", {}).get("baseline_probabilities", {}))
            for row in rows
        )
    )
    reports = {}
    for name in sorted(baseline_names):
        probabilities = np.array(
            [row["forecast"]["diagnostics"]["baseline_probabilities"][name] for row in rows],
            dtype=float,
        )
        reports[name] = _score_probabilities(rows, probabilities)
    return reports


def _score_probabilities(rows, probabilities) -> ScoreReport:
    buy_counts = np.array([row["label"]["buy_count"] for row in rows], dtype=float)
    total_counts = np.array([row["label"]["trade_count"] for row in rows], dtype=float)
    if np.any(total_counts <= 0):
        raise ValueError("eligible labels require trades")
    if (
        not np.all(np.isfinite(probabilities))
        or np.any(probabilities < 0.0)
        or np.any(probabilities > 1.0)
    ):
        raise ValueError("forecast probabilities must be finite and within [0, 1]")
    ratios = buy_counts / total_counts
    nll = -np.sum(
        xlogy(buy_counts, probabilities) + xlogy(total_counts - buy_counts, 1.0 - probabilities)
    ) / np.sum(total_counts)
    brier = float(np.mean((probabilities - ratios) ** 2))
    mae = float(np.mean(np.abs(probabilities - ratios)))
    intercept, slope = calibration_parameters(probabilities, buy_counts, total_counts)
    return ScoreReport(
        n=len(rows),
        total_trades=int(np.sum(total_counts)),
        negative_log_likelihood=float(nll),
        brier=brier,
        mae=mae,
        calibration_intercept=intercept,
        calibration_slope=slope,
    )


def calibration_parameters(probabilities, buy_counts, total_counts):
    if (
        len(probabilities) < 10
        or np.allclose(probabilities, probabilities[0])
        or np.any(probabilities <= 0.0)
        or np.any(probabilities >= 1.0)
    ):
        return None, None
    logits = np.log(probabilities / (1.0 - probabilities))
    successes = buy_counts / total_counts
    model = sm.GLM(
        successes,
        sm.add_constant(logits),
        family=sm.families.Binomial(),
        freq_weights=total_counts,
    )
    intercept = slope = None
    with warnings.catch_warnings():
        warnings.simplefilter("error", PerfectSeparationWarning)
        try:
            result = model.fit()
            intercept = float(result.params[0])
            slope = float(result.params[1])
        except PerfectSeparationWarning:
            intercept = slope = None
    if (
        intercept is not None
        and slope is not None
        and math.isfinite(intercept)
        and math.isfinite(slope)
        and slope > 0
    ):
        return intercept, slope
    return _calibration_parameters_positive_slope(logits, successes, total_counts)


def _calibration_parameters_positive_slope(logits, successes, total_counts):
    from scipy.optimize import minimize

    weights = np.asarray(total_counts, dtype=float)
    logits = np.asarray(logits, dtype=float)
    successes = np.asarray(successes, dtype=float)

    def objective(values):
        intercept, raw_slope = values
        slope = math.exp(raw_slope)
        scores = intercept + slope * logits
        pos = np.minimum(np.maximum(1.0 / (1.0 + np.exp(-scores)), 1e-9), 1.0 - 1e-9)
        loss = -(
            weights * (successes * np.log(pos) + (1.0 - successes) * np.log(1.0 - pos))
        ).sum()
        return float(loss)

    result = minimize(objective, np.array([0.0, 0.0], dtype=float), method="L-BFGS-B")
    if not result.success or not np.all(np.isfinite(result.x)):
        return None, None
    intercept = float(result.x[0])
    slope = float(math.exp(result.x[1]))
    if slope <= 0 or not math.isfinite(intercept):
        return None, None
    return intercept, slope


def paired_hac_test(losses_baseline, losses_model, max_lags: int | None = None):
    if len(losses_baseline) != len(losses_model) or len(losses_model) < 3:
        raise ValueError("at least three aligned paired losses are required")
    differences = np.asarray(losses_model, dtype=float) - np.asarray(losses_baseline, dtype=float)
    if not np.all(np.isfinite(differences)):
        raise ValueError("losses must be finite")
    lags = max_lags if max_lags is not None else max(1, int(len(differences) ** (1 / 3)))
    result = sm.OLS(differences, np.ones((len(differences), 1))).fit(
        cov_type="HAC", cov_kwds={"maxlags": lags}
    )
    estimate = float(result.params[0])
    standard_error = float(result.bse[0])
    statistic = estimate / standard_error if standard_error > 0 else 0.0
    one_sided_p = (
        float(result.pvalues[0] / 2) if statistic < 0 else float(1 - result.pvalues[0] / 2)
    )
    critical = 1.959963984540054
    return {
        "n": len(differences),
        "mean_loss_difference": estimate,
        "standard_error_hac": standard_error,
        "ci_95": [
            estimate - critical * standard_error,
            estimate + critical * standard_error,
        ],
        "one_sided_p_value": one_sided_p,
        "max_lags": lags,
        "method": "OLS intercept with Newey-West HAC covariance",
    }


def paired_block_bootstrap_test(
    losses_baseline,
    losses_model,
    *,
    block_length: int | None = None,
    iterations: int = 4000,
    seed: int = 42,
):
    if len(losses_baseline) != len(losses_model) or len(losses_model) < 3:
        raise ValueError("at least three aligned paired losses are required")
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    differences = np.asarray(losses_model, dtype=float) - np.asarray(losses_baseline, dtype=float)
    if not np.all(np.isfinite(differences)):
        raise ValueError("losses must be finite")
    n = len(differences)
    block_length = block_length or max(1, round(n ** (1 / 3)))
    if not 1 <= block_length <= n:
        raise ValueError("block length must be within the sample size")
    rng = np.random.default_rng(seed)
    starts = np.arange(n)
    observed = float(np.mean(differences))
    centered = differences - observed
    bootstrap_means = np.empty(iterations, dtype=float)
    for index in range(iterations):
        sampled: list[float] = []
        while len(sampled) < n:
            start = int(rng.choice(starts))
            sampled.extend(float(centered[(start + offset) % n]) for offset in range(block_length))
        bootstrap_means[index] = float(np.mean(sampled[:n]))
    p_value = float(np.mean(bootstrap_means <= observed))
    return {
        "n": n,
        "mean_loss_difference": observed,
        "one_sided_p_value": p_value,
        "block_length": block_length,
        "iterations": iterations,
        "seed": seed,
        "method": "centered circular moving-block bootstrap",
    }


def required_sample_size(
    expected_mean_difference: float,
    standard_deviation: float,
    autocorrelation: float,
    alpha: float = 0.05,
    power: float = 0.8,
) -> int:
    if expected_mean_difference >= 0:
        raise ValueError("expected improvement must be a negative loss difference")
    if (
        standard_deviation <= 0
        or not -0.99 < autocorrelation < 0.99
        or not 0 < alpha < 1
        or not 0 < power < 1
    ):
        raise ValueError("invalid variance or autocorrelation")
    from scipy.stats import norm

    inflation = (1.0 + autocorrelation) / (1.0 - autocorrelation)
    independent_n = (
        (norm.ppf(1.0 - alpha) + norm.ppf(power))
        * standard_deviation
        / abs(expected_mean_difference)
    ) ** 2
    return math.ceil(independent_n * inflation)
