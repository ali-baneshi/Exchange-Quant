#!/usr/bin/env python3

"""
Shared configuration constants for Exchange-Q.
"""

# Historical data
HELD_OUT_FRAC = 0.2

# Ensemble weighting
RELATIVE_K = 10.0

# Live pipeline trading simulation
FEE_RATE = 0.001
LONG_THRESHOLD = 0.60
FLAT_THRESHOLD = 0.40

# Statistical testing (increment when adding a new pre-registered hypothesis).
# N=5 reflects historical kline-era comparisons.
N_HYPOTHESES_TOTAL = 5
# Live schema v5 primary test (single frozen hypothesis: quantum vs classical on buy_ratio).
N_HYPOTHESES_LIVE = 1
# Minimum resolved eligible predictions before production significance claims.
MIN_SIGNIFICANCE_N = 720

# Live protocol defaults
DEFAULT_WINDOW = 15
DEFAULT_HORIZON_S = 3600.0
LIVE_SCHEMA_VERSION = 6
LIVE_MODEL_VERSION = "born_constructive_v2"
DATA_POLICY_VERSION = 4
LIVE_IMPLEMENTATION_REVISION = "v6r1"
ACQUISITION_POLICY_VERSION = 1

# Raw trade capture for primary live labels.
TRADE_CAPTURE_SIZE = 2000
TRADE_RETENTION_DAYS = 30
MAX_TRADE_CAPTURE_GAP_FACTOR = 2

# Live feature buy_ratio uses only recent trades so the lookback matches the
# forecast horizon scale (full API pages span ~1h and flatten the signal).
FEATURE_LOOKBACK_FLOOR_S = 60.0
MAX_LOCAL_EXCHANGE_OFFSET_MS = 5000
MAX_FUTURE_TIMESTAMP_MS = 1000
DEFAULT_MAX_TRADE_AGE_S = 120.0
MAX_CONSECUTIVE_NO_DATA = 12


def feature_lookback_s(horizon_s=None):
    """Seconds of recent trades used for live buy_ratio features."""
    if horizon_s is None:
        return float(FEATURE_LOOKBACK_FLOOR_S)
    return float(max(FEATURE_LOOKBACK_FLOOR_S, float(horizon_s)))

# Reject observations when cross-endpoint timestamps differ by more than this (ms).
MAX_ENDPOINT_SKEW_MS = 5000

# Born rule: revert to classical when interference overshoots this much or pred >= SATURATION_THRESHOLD.
MAX_INTERFERENCE_BOOST = 0.15
SATURATION_THRESHOLD = 0.99

# Minimum trades in [created_at_ms, target_at_ms] for forward-window buy_ratio label.
MIN_FORWARD_WINDOW_TRADES = 3
MAX_FORWARD_WINDOW_MIN_TRADES = 15

# Quality flags that disqualify a forecast from scoring eligibility.
DISQUALIFYING_QUALITY_FLAGS = frozenset({
    "crossed_market",
    "no_trades",
    "empty_depth",
    "stale_trades",
    "missing_timestamp",
    "future_timestamp",
    "stale_ticker",
    "clock_skew",
    "malformed_market_data",
    "endpoint_skew",
    "late_resolution",
    "short_forward_window",
    "label_unavailable",
})


def min_forward_trades(horizon_s):
    """Horizon-scaled minimum trades for forward-window label (capped for production)."""
    return max(
        MIN_FORWARD_WINDOW_TRADES,
        min(int(horizon_s / 20), MAX_FORWARD_WINDOW_MIN_TRADES),
    )
