#!/usr/bin/env python3

"""
Shared live forecast protocol.

Canonical contract (aligned with pipeline_live_ensemble):
  - Predict from the last `window` observations: history[-window:]
  - Score against a FUTURE observation after horizon_s (resolve-later)
  - Target is continuous buy_ratio (NOT binary kline direction)

Legacy nowcast (predict t from history[:-1], score vs history[-1] immediately)
is intentionally not used by live scripts anymore.
"""

from config import DEFAULT_HORIZON_S, DEFAULT_WINDOW


def ready_for_forecast(history, window=DEFAULT_WINDOW):
    return len(history) >= window


def forecast_lookback(history, window=DEFAULT_WINDOW):
    """Return the lookback used to create a forecast (includes latest obs)."""
    if not ready_for_forecast(history, window):
        return None
    return history[-window:]


def pending_due(pending, now_ms):
    """True if a pending prediction should be resolved at now_ms."""
    if not pending or pending.get("status") != "pending":
        return False
    return now_ms >= int(pending.get("target_at_ms", 0))


def make_pending(step, horizon_s, created_at_ms, prediction_fields):
    """Build a pending forecast record; prediction_fields merged into the dict."""
    rec = {
        "step": step,
        "status": "pending",
        "created_at_ms": created_at_ms,
        "target_at_ms": created_at_ms + int(horizon_s * 1000),
        "horizon_s": horizon_s,
    }
    rec.update(prediction_fields)
    return rec


def resolve_buy_ratio(pending, actual_buy_ratio, resolved_at_ms, extra=None):
    """Resolve a pending forecast against the future buy_ratio."""
    pending = dict(pending)
    pred = pending.get("prediction", pending.get("quantum", pending.get("ensemble")))
    classical = pending.get("classical")
    pending.update({
        "status": "resolved",
        "resolved_at_ms": resolved_at_ms,
        "resolved_actual": actual_buy_ratio,
        "actual": actual_buy_ratio,
    })
    if pred is not None:
        pending["prediction_error"] = abs(pred - actual_buy_ratio)
    if classical is not None:
        pending["classical_error"] = abs(classical - actual_buy_ratio)
    if extra:
        pending.update(extra)
    return pending
