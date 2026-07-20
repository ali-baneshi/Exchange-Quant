#!/usr/bin/env python3

"""
Classical baseline models for the Exchange-Q project.

Provides SMA, EMA, momentum, and linear-regression+sigmoid models.
The `classical_ensemble` function averages all models for a combined prediction.

Usage:
    from baselines import classical_ensemble
    pred, preds = classical_ensemble(history)
"""

import math
import statistics


def sma_model(history, window=10):
    """Simple Moving Average — predicts the mean of recent buy_ratios."""
    ratios = [h["buy_ratio"] for h in history[-window:]]
    return statistics.mean(ratios) if ratios else 0.5


def ema_model(history, alpha=0.3):
    """Exponential Moving Average — more weight to recent observations."""
    ratios = [h["buy_ratio"] for h in history]
    if not ratios:
        return 0.5
    ema = ratios[0]
    for r in ratios[1:]:
        ema = alpha * r + (1 - alpha) * ema
    return ema


def momentum_model(history, window=5):
    """
    Simple momentum: if recent trend is up, predict higher buy_ratio.
    Uses linear regression slope on last `window` points.
    """
    ratios = [h["buy_ratio"] for h in history[-window:]]
    if len(ratios) < 2:
        return statistics.mean(ratios) if ratios else 0.5
    xs = list(range(len(ratios)))
    n = len(xs)
    sx = sum(xs)
    sy = sum(ratios)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ratios))
    denom = n * sxx - sx * sx
    slope = (n * sxy - sx * sy) / denom if denom != 0 else 0
    base = statistics.mean(ratios)
    pred = base + slope * (window + 1)
    return max(0, min(1, pred))


def linear_regression_sigmoid_model(history, window=10):
    """
    Linear regression on (imbalance, volatility) → buy_ratio,
    passed through a sigmoid to constrain output to [0,1].
    This is NOT true logistic regression (no log-likelihood optimization).
    """
    features = history[-window:]
    if len(features) < 3:
        return sma_model(history)

    X = []
    y = []
    for f in features:
        X.append([f.get("imbalance", 0), f.get("volatility", 0)])
        y.append(f["buy_ratio"])

    n = len(X)
    if n < 2:
        return statistics.mean(y)

    mean_x0 = statistics.mean([x[0] for x in X])
    mean_x1 = statistics.mean([x[1] for x in X])
    mean_y = statistics.mean(y)

    cov_x0_y = sum((X[i][0] - mean_x0) * (y[i] - mean_y) for i in range(n))
    var_x0 = sum((X[i][0] - mean_x0) ** 2 for i in range(n)) or 1
    cov_x1_y = sum((X[i][1] - mean_x1) * (y[i] - mean_y) for i in range(n))
    var_x1 = sum((X[i][1] - mean_x1) ** 2 for i in range(n)) or 1

    w0 = cov_x0_y / var_x0
    w1 = cov_x1_y / var_x1
    bias = mean_y - w0 * mean_x0 - w1 * mean_x1

    latest = history[-1]
    z = bias + w0 * latest.get("imbalance", 0) + w1 * latest.get("volatility", 0)
    pred = 1 / (1 + math.exp(-z))
    return pred


def classical_ensemble(history):
    """
    Ensemble of all classical models.
    Returns the average prediction plus metadata.
    """
    preds = {
        "sma": sma_model(history),
        "ema": ema_model(history),
        "momentum": momentum_model(history),
        "logistic": linear_regression_sigmoid_model(history),
    }
    ensemble = statistics.mean(preds.values())
    return ensemble, preds
