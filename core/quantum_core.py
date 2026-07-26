#!/usr/bin/env python3

"""
Shared Born-rule prediction core.

The public helper returns both the prediction and diagnostics so live runs can
distinguish a real interference prediction from a mean/fallback prediction.
"""

import cmath
import math
import statistics

from config import MAX_INTERFERENCE_BOOST, SATURATION_THRESHOLD
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


def _effective_variance_floor(mu, variance_floor):
    """Relative floor for discrete buy_ratio (e.g. k/30 trade counts)."""
    discrete = (0.01 * mu * (1.0 - mu)) ** 2 if 0.0 < mu < 1.0 else 0.0
    return max(variance_floor, discrete)


def _split_bucket_values(vals):
    """
    Split vals into high/low groups at median.
    Returns (high, low) or (None, None, reason) on failure.
    """
    if len(vals) < 2:
        return None, None, "insufficient_history"

    mu = _mean(vals)
    var = statistics.variance(vals) if len(vals) > 1 else 0.0
    floor = _effective_variance_floor(mu, 1e-8)
    if var < floor:
        return None, None, "flat_history"

    med = statistics.median(vals)
    high = [v for v in vals if v > med]
    low = [v for v in vals if v <= med]
    if not high or not low:
        return None, None, "single_bucket"
    return high, low, "none"


def _split_by_imbalance(history):
    """
    High/low groups by |imbalance|; target means from buy_ratio in each group.
    """
    if not history:
        return None, None, "insufficient_history"
    imbs = [abs(float(h.get("imbalance", 0.0))) for h in history]
    targets = [_feature_value(h) for h in history]
    if len(imbs) < 2:
        return None, None, "insufficient_history"

    mu_i = _mean(imbs)
    var_i = statistics.variance(imbs) if len(imbs) > 1 else 0.0
    if var_i < 1e-10:
        return None, None, "flat_history"

    med = statistics.median(imbs)
    high_idx = [i for i, v in enumerate(imbs) if v > med]
    low_idx = [i for i, v in enumerate(imbs) if v <= med]
    if not high_idx or not low_idx:
        return None, None, "single_bucket"

    high = [targets[i] for i in high_idx]
    low = [targets[i] for i in low_idx]
    return high, low, "none"


def _apply_saturation_gate(pred, classical_part, meta):
    """Revert constructive overshoot to classical_part when Born prediction saturates."""
    clamped = max(0.0, min(1.0, pred))
    if classical_part is None:
        return clamped, meta
    overshoot = clamped - classical_part
    if clamped >= SATURATION_THRESHOLD or overshoot > MAX_INTERFERENCE_BOOST:
        meta = dict(meta)
        meta["interference_overshoot"] = overshoot
        meta["raw_born_prediction"] = clamped
        meta["fallback_reason"] = "saturation_gate"
        return max(0.0, min(1.0, classical_part)), meta
    return clamped, meta


def _apply_born_rule(high, low, n_total, delta, meta, apply_saturation_gate=True):
    p_h = len(high) / n_total
    p_l = len(low) / n_total
    if not math.isclose(p_h + p_l, 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("Born buckets must partition the complete history")
    mu_h = _mean(high, 0.0)
    mu_l = _mean(low, 0.0)
    classical_part = p_h * mu_h + p_l * mu_l
    interference = 2 * math.sqrt(max(0.0, p_h * p_l * mu_h * mu_l)) * math.cos(delta)

    amp_h = math.sqrt(p_h * mu_h)
    amp_l = math.sqrt(p_l * mu_l) * cmath.exp(1j * delta)
    pred = abs(amp_h + amp_l) ** 2

    meta.update({
        "fallback_reason": "none",
        "classical_part": classical_part,
        "interference_term": interference,
        "p_high": p_h,
        "p_low": p_l,
        "mu_high": mu_h,
        "mu_low": mu_l,
    })
    clamped = max(0.0, min(1.0, pred))
    if apply_saturation_gate:
        return _apply_saturation_gate(pred, classical_part, meta)
    return clamped, meta


def _try_born_bucketing(history, delta, meta, bucket_feature="buy_ratio", value_key=None,
                        apply_saturation_gate=True):
    """
    Attempt Born bucketing with a specific feature for split (and mu unless imbalance).
    """
    meta = dict(meta)
    meta["bucket_feature"] = bucket_feature

    if bucket_feature == "imbalance":
        high, low, reason = _split_by_imbalance(history)
    elif bucket_feature == "buy_ratio_volume":
        vals = [_feature_value(h, key="buy_ratio_volume") for h in history]
        high, low, reason = _split_bucket_values(vals)
    elif value_key:
        vals = [_feature_value(h, key=value_key) for h in history]
        high, low, reason = _split_bucket_values(vals)
    else:
        vals = [_feature_value(h) for h in history]
        high, low, reason = _split_bucket_values(vals)

    if reason != "none":
        meta["fallback_reason"] = reason
        return None, meta

    return _apply_born_rule(
        high, low, len(history), delta, meta, apply_saturation_gate=apply_saturation_gate,
    )


def born_rule_predict(history, value_key=None, min_history=4, variance_floor=1e-8,
                      delta_override=None, skip_volume_bucket=False):
    """
    Predict a bounded [0, 1] value with the Born-rule interference formula.

    delta_override: if set, skip compute_delta and use this phase (for synthetic
    diagnostics / hidden-sign probes). Does not claim to be a true optimum.

    Metadata fields:
      - delta_source: orderbook, kline_proxy, fallback, or override
      - fallback_reason: none, insufficient_history, flat_history, single_bucket,
        destructive_interference, saturation_gate
      - skip_volume_bucket: when True, omit buy_ratio_volume from live bucket chain
      - bucket_feature: buy_ratio, buy_ratio_volume, or imbalance
      - classical_part: p_h*mu_h + p_l*mu_l before interference
      - interference_term: 2*sqrt(...)*cos(delta)
    """
    source = _infer_delta_source(history)
    meta = {
        "delta": 0.0,
        "confidence": 0.0,
        "delta_source": source,
        "fallback_reason": "none",
        "bucket_feature": "buy_ratio",
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

    if len(history) < min_history:
        vals = [_feature_value(h, key=value_key) for h in history] if value_key else [_feature_value(h) for h in history]
        meta["fallback_reason"] = "insufficient_history"
        pred = _mean(vals)
        meta["classical_part"] = pred
        return max(0.0, min(1.0, pred)), meta

    chain = ["buy_ratio"]
    has_imbalance = any(h.get("imbalance") is not None for h in history)
    if not skip_volume_bucket:
        has_volume = any(h.get("buy_ratio_volume") is not None for h in history)
        if has_volume:
            chain.append("buy_ratio_volume")
    if has_imbalance:
        chain.append("imbalance")

    last_meta = meta
    apply_gate = delta_override is None
    for feature in chain:
        pred, attempt_meta = _try_born_bucketing(
            history, delta, meta, bucket_feature=feature, value_key=value_key,
            apply_saturation_gate=apply_gate,
        )
        last_meta = attempt_meta
        if pred is not None:
            if (
                delta_override is None
                and attempt_meta.get("interference_term", 0) < 0
            ):
                attempt_meta["fallback_reason"] = "destructive_interference"
                pred = attempt_meta["classical_part"]
            return pred, attempt_meta

    vals = [_feature_value(h, key=value_key) for h in history] if value_key else [_feature_value(h) for h in history]
    pred = _mean(vals)
    last_meta["classical_part"] = pred
    return max(0.0, min(1.0, pred)), last_meta
