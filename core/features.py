#!/usr/bin/env python3

"""
Shared kline feature computation for classical backtests / ablations.
"""

import math
import statistics


def compute_features(candle, prev_candles):
    """
    Build a feature dict from one OHLCV candle and prior feature rows.

    prev_candles may be prior feature dicts (with close/vol) or raw candles;
    both expose close and vol.
    """
    features = {
        "ts": candle.get("ts", candle.get("id", 0)),
        "price": candle["close"],
        "open": candle["open"],
        "high": candle["high"],
        "low": candle["low"],
        "close": candle["close"],
        "vol": candle["vol"],
        "amount": candle.get("amount", 0.0),
        "count": candle.get("count", 0),
    }
    candle_range = candle["high"] - candle["low"]
    body = abs(candle["close"] - candle["open"])
    features["body_ratio"] = body / candle_range if candle_range > 0 else 0.0
    features["direction"] = 1.0 if candle["close"] > candle["open"] else 0.0
    features["volatility"] = candle_range / candle["close"] if candle["close"] else 0.0

    signed_direction = 1.0 if candle["close"] > candle["open"] else -1.0
    features["avg_trade_size"] = candle.get("amount", 0.0) / max(1, candle.get("count", 1))
    amount = candle.get("amount", 0.0)
    features["price_impact"] = (
        (candle["close"] - candle["open"]) / amount if amount > 0 else 0.0
    )
    # Kline-derived proxy only — NOT real order-book imbalance (invalid for Born rule).
    features["imbalance"] = (features["direction"] - 0.5) * features["body_ratio"] * 2

    if prev_candles:
        prev_close = prev_candles[-1]["close"]
        features["return"] = (candle["close"] - prev_close) / prev_close if prev_close else 0.0
        features["log_return"] = (
            math.log(candle["close"] / prev_close) if prev_close > 0 else 0.0
        )
        if len(prev_candles) >= 3:
            vols = [c["vol"] for c in prev_candles[-3:]]
            vol_prev = statistics.mean(vols[:-1]) if len(vols) > 1 else vols[0]
            features["volume_change"] = (
                (candle["vol"] - vol_prev) / vol_prev if vol_prev > 0 else 0.0
            )
        else:
            features["volume_change"] = 0.0
        if len(prev_candles) >= 5:
            recent_vols = [c["vol"] for c in prev_candles[-5:]]
            features["vol_percentile"] = (
                sum(1 for v in recent_vols if v <= candle["vol"]) / len(recent_vols)
            )
        else:
            features["vol_percentile"] = 0.5
    else:
        features["return"] = 0.0
        features["log_return"] = 0.0
        features["volume_change"] = 0.0
        features["vol_percentile"] = 0.5

    features["conviction"] = features["direction"] * features["body_ratio"]
    features["buy_ratio"] = features["conviction"]
    features["signed_conviction"] = signed_direction * features["body_ratio"]
    features["abs_return"] = abs(features["return"])

    return features
