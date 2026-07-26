#!/usr/bin/env python3

"""
Shared Born-rule prediction core.

The public helper returns both the prediction and diagnostics so live runs can
distinguish a real interference prediction from a mean/fallback prediction.
"""

import cmath
import math
import statistics

from delta_adaptive import compute_delta


def _mean(values, default=0.5):
    return statistics.mean(values) if values else default


def _feature_value(h, key=None):
    """Extract a bounded feature value; treat explicit None as missing."""
    if key:
        v = h.get(key)
    else:
        v = h.get("buy_ratio")
        if v is None:
            v = h.get("conviction")
    if v is None:
        return 0.0
    return max(0.0, min(1.0, float(v)))


def _infer_delta_source(history):
    if any(k in h for h in history for k in ("open", "close", "return", "direction", "body_ratio")):
        return "kline_proxy"
    if any("imbalance" in h and h.get("imbalance") is not None for h in history):
        return "orderbook"
    return "fallback"


def born_rule_predict(history, value_key=None, min_history=4, variance_floor=1e-8,
                      delta_override=None):
    """
    Predict a bounded [0, 1] value with the Born-rule interference formula.

    delta_override: if set, skip compute_delta and use this phase (for synthetic
    diagnostics / hidden-sign probes). Does not claim to be a true optimum.

    Metadata fields:
      - delta_source: orderbook, kline_proxy, fallback, or override
      - fallback_reason: none, insufficient_history, flat_history, single_bucket
      - classical_part: p_h*mu_h + p_l*mu_l before interference
      - interference_term: 2*sqrt(...)*cos(delta)
    """
    source = _infer_delta_source(history)
    meta = {
        "delta": 0.0,
        "confidence": 0.0,
        "delta_source": source,
        "fallback_reason": "none",
        "classical_part": None,
        "interference_term": 0.0,
        "p_high": None,
        "p_low": None,
        "mu_high": None,
        "mu_low": None,
    }

    if not history:
        meta["fallback_reason"] = "insufficient_history"
        return 0.5, meta

    if delta_override is not None:
        delta, confidence = float(delta_override), 1.0
        meta["delta_source"] = "override"
    else:
        delta, confidence = compute_delta(history)
        meta["delta_source"] = source
    meta["delta"] = delta
    meta["confidence"] = confidence

    if value_key:
        vals = [_feature_value(h, key=value_key) for h in history]
    else:
        vals = [_feature_value(h) for h in history]

    if len(vals) < min_history:
        meta["fallback_reason"] = "insufficient_history"
        pred = _mean(vals)
        meta["classical_part"] = pred
        return max(0.0, min(1.0, pred)), meta

    mu = _mean(vals)
    var = statistics.variance(vals) if len(vals) > 1 else 0.0
    if var < variance_floor:
        meta["fallback_reason"] = "flat_history"
        meta["classical_part"] = mu
        return max(0.0, min(1.0, mu)), meta

    med = statistics.median(vals)
    eps = math.sqrt(var) / 4
    high = [v for v in vals if v > med + eps]
    low = [v for v in vals if v <= med - eps]
    if not high or not low:
        high = [v for v in vals if v > med]
        low = [v for v in vals if v <= med]
    if not high or not low:
        meta["fallback_reason"] = "single_bucket"
        meta["classical_part"] = mu
        return max(0.0, min(1.0, mu)), meta

    p_h = len(high) / len(vals)
    p_l = len(low) / len(vals)
    mu_h = _mean(high, 0.0)
    mu_l = _mean(low, 0.0)
    classical_part = p_h * mu_h + p_l * mu_l
    interference = 2 * math.sqrt(max(0.0, p_h * p_l * mu_h * mu_l)) * math.cos(delta)

    amp_h = math.sqrt(p_h * mu_h)
    amp_l = math.sqrt(p_l * mu_l) * cmath.exp(1j * delta)
    pred = abs(amp_h + amp_l) ** 2

    meta.update({
        "classical_part": classical_part,
        "interference_term": interference,
        "p_high": p_h,
        "p_low": p_l,
        "mu_high": mu_h,
        "mu_low": mu_l,
    })
    return max(0.0, min(1.0, pred)), meta
