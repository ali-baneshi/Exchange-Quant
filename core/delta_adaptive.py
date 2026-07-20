#!/usr/bin/env python3

"""
Adaptive delta (interference phase) computation for the Born rule.

Provides three strategies:
  - compute_delta: auto-select order-book or kline proxy features
  - compute_delta_from_orderbook_features: imbalance + volatility live data
  - compute_delta_from_kline_features: OHLCV/proxy features
  - compute_delta_from_klines: raw OHLCV candles
  - delta_signals: interpret a series of delta values

Usage:
    from delta_adaptive import compute_delta, compute_delta_from_klines
    delta, confidence = compute_delta(history)
"""

import math
import statistics


def _clamp(value, lo=0.0, hi=1.0):
    return min(hi, max(lo, value))


def _has_real_imbalance(history):
    has_candle_fields = any(
        any(k in h for k in ("open", "close", "return", "direction", "body_ratio"))
        for h in history
    )
    return not has_candle_fields and any("imbalance" in h and h.get("imbalance") is not None for h in history)


def compute_delta(history, lambda_smooth=0.3):
    """
    Auto-select the best available delta estimate.
    """
    if not history:
        return 0.0, 0.0
    if _has_real_imbalance(history):
        return compute_delta_from_orderbook_features(history, lambda_smooth=lambda_smooth)
    return compute_delta_from_kline_features(history)


def compute_delta_from_orderbook_features(history, lambda_smooth=0.3):
    """
    Compute delta from market context (order book imbalance + volatility).

    Maps market context to an interference phase:
      - Strong directional conviction (|imbalance| -> 1) => delta -> 0 (constructive)
      - Uncertainty (|imbalance| -> 0, high vol) => delta -> pi (destructive)
      - Mixed => delta -> pi/2 (no interference)

    Returns:
        delta: interference phase in [0, 2*pi]
        confidence: magnitude of interference effect |cos(delta)|
    """
    if not history:
        return 0.0, 0.0

    recent = history[-min(len(history), 10):]
    avg_imbalance = statistics.mean(abs(h.get("imbalance", 0)) for h in recent)
    avg_vol = statistics.mean(h.get("volatility", 0) for h in recent)

    avg_imbalance = _clamp(avg_imbalance)
    avg_vol = _clamp(avg_vol)

    context_factor = avg_imbalance * (1 - avg_vol)
    context_factor = _clamp(context_factor)

    delta = math.pi * (1 - context_factor)

    confidence = abs(math.cos(delta))

    return delta, confidence


def compute_delta_from_kline_features(history):
    """
    Compute delta from candle-derived proxy features.

    Directional, clean candles get constructive interference. Choppy/high-vol
    candles move toward destructive interference; neutral/noisy candles land
    near pi/2 instead of silently disabling delta.
    """
    if not history:
        return 0.0, 0.0

    recent = history[-min(len(history), 10):]
    returns = []
    volatilities = []
    bodies = []
    signed = []

    for h in recent:
        if "return" in h:
            ret = h.get("return", 0.0)
        elif h.get("open"):
            ret = (h.get("close", 0.0) - h.get("open", 0.0)) / h.get("open", 1.0)
        else:
            ret = h.get("direction", 0.5) - 0.5
        returns.append(ret)
        volatilities.append(h.get("volatility", abs(ret)))
        body = h.get("body_ratio")
        if body is None and h.get("high", 0) != h.get("low", 0):
            body = abs(h.get("close", 0.0) - h.get("open", 0.0)) / (h.get("high", 0.0) - h.get("low", 0.0))
        bodies.append(_clamp(body if body is not None else abs(ret) * 100))
        signed.append((1.0 if ret >= 0 else -1.0) * bodies[-1])

    avg_return = statistics.mean(returns)
    avg_vol = statistics.mean(volatilities)
    avg_body = statistics.mean(bodies)
    trend = abs(statistics.mean(1.0 if r >= 0 else 0.0 for r in returns) - 0.5) * 2
    signed_conviction = abs(statistics.mean(signed))

    directional_conviction = _clamp((trend * 0.45) + (avg_body * 0.35) + (signed_conviction * 0.20))
    vol_penalty = _clamp(avg_vol * 25)

    context_factor = _clamp(directional_conviction * (1 - vol_penalty))
    uncertainty = _clamp((1 - directional_conviction) * 0.7 + vol_penalty * 0.3)

    if abs(avg_return) < 1e-12 and avg_body < 1e-8:
        delta = math.pi / 2
    else:
        delta = math.pi * (1 - context_factor)
        delta = (delta + (math.pi / 2) * uncertainty) / (1 + uncertainty)

    confidence = abs(math.cos(delta)) * max(0.1, 1 - vol_penalty)
    return _clamp(delta, 0.0, math.pi), _clamp(confidence)


def compute_delta_adaptive(history, lambda_decay=0.7):
    """
    Legacy wrapper — delegates to compute_delta for consistency.
    """
    return compute_delta(history)


def compute_delta_from_klines(klines):
    """
    Compute delta from kline features.
    Calibration shows optimal delta is NEVER pi/2 — always 0 or pi.
    Uses recent return direction to choose: positive return → 0, negative → pi.
    """
    if not klines:
        return 0.0, 0.0
    return compute_delta_from_kline_features(klines)


def delta_signals(delta_series, threshold_gap=0.2):
    """
    Interpret recent delta values.
    """
    if not delta_series:
        return {"signal": "NEUTRAL", "alert": False}

    recent = delta_series[-5:]
    mean_delta = statistics.mean(recent)

    gap_from_pi = abs(mean_delta - math.pi)
    gap_from_zero = abs(mean_delta)

    if gap_from_pi < threshold_gap:
        return {"signal": "REGIME_SHIFT_RISK", "delta": mean_delta, "alert": True}
    if gap_from_zero < threshold_gap:
        return {"signal": "CONSTRUCTIVE", "delta": mean_delta, "alert": False}
    if abs(mean_delta - math.pi / 2) < threshold_gap:
        return {"signal": "MAX_UNCERTAINTY", "delta": mean_delta, "alert": True}

    return {"signal": "NORMAL", "delta": mean_delta, "alert": False}


if __name__ == "__main__":
    demos = [
        {"imbalance": 0.8, "volatility": 0.001},
        {"imbalance": -0.7, "volatility": 0.002},
        {"imbalance": 0.1, "volatility": 0.05},
        {"imbalance": 0.0, "volatility": 0.1},
        {"imbalance": 0.5, "volatility": 0.01},
    ]
    for d in demos:
        delta, conf = compute_delta([d])
        sig = delta_signals([delta])
        print(f"imb={d['imbalance']:+.1f} vol={d['volatility']:.3f}  "
              f"delta={delta:.3f}  conf={conf:.2f}  {sig['signal']}")
