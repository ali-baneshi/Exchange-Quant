# Schema v6 — Live Evaluation Contract

> **Current v6r1 contract as of July 28, 2026.** Runtime values are defined by
> `core/config.py`; the canonical writer is `core/pipeline_live_ensemble.py`.
> This is a research-evaluation format, not a trading or order-execution format.

## Identity and Eligibility

| Invariant | Requirement |
|---|---|
| Schema | `schema_version == 6` |
| Model | `model_version == "born_constructive_v2"` |
| Data policy | `data_policy_version == 4` |
| Implementation | `implementation_revision == "v6r1"` |
| Acquisition | `acquisition_policy_version == 1` |
| Label policy | `experiment_manifest.label_policy == "captured_trade_window_v1"` |
| Primary target | Trade-count `buy_ratio` from locally captured future trades |
| Primary metric | Paired MAE difference versus the recorded classical comparator |
| Primary eligibility | `status == "resolved"`, `resolved_label == "forward_window"`, `label_capture_complete == true`, and `score_eligible == true` |
| Corpus isolation | Never combine pre-hardening v6 or v2–v5 rows with v6r1 primary analysis |

The primary sample target is 720 eligible resolved forecasts. This is a reporting
threshold, not evidence that any run has met it.

## Storage and Recovery

```text
core/_live_results/<run_id>.sqlite3  authoritative state
core/_live_results/<run_id>.json     atomic, inspectable export
```

SQLite stores run state, accepted observations, forecasts, raw trades, and capture
batches. It uses WAL mode, full synchronous writes, unique exchange timestamps for
observations, deduplicated raw trades, and a partial unique index that permits only
one pending forecast. The JSON export is a convenience view and can lag a recent
SQLite transaction.

A resumed run must have schema v6r1 and the same configuration hash. The runner locks
the run database for its lifetime; a second process for the same run fails instead
of sharing state.

## Top-Level Document

| Field | Meaning |
|---|---|
| `run_id`, `experiment_id` | Stable run identity |
| `config_hash` | Hash of the frozen runtime configuration |
| `model_version`, `data_policy_version` | Model and data-policy identities |
| `implementation_revision`, `acquisition_policy_version` | Reliability and acquisition identities |
| `experiment_manifest` | Label policy, metric, horizon, and minimum eligible count |
| `symbol`, `mode` | Exchange pair and `quantum` or `ensemble` configuration |
| `horizon_s`, `sample_interval_s`, `window` | Forecast, polling, and accepted-observation lookback settings |
| `status`, `stop_reason` | Current or terminal run lifecycle state |
| `observations`, `predictions` | Exported durable records |
| `ensemble_weights`, `ensemble_performance` | Present for ensemble-mode state |

## Observation Contract

An accepted observation combines ticker, depth, and recent-trade features. The
feature `buy_ratio` uses trades from the recent `max(60, horizon_s)` seconds; it is
not the later forecast label. Raw exchange trade pages are separately captured for
future-label reconstruction.

Key fields include:

| Field | Meaning |
|---|---|
| `timestamp` / `exchange_timestamp_ms` | Exchange timestamp used for alignment where available |
| `wall_time_ms`, `collected_at_ms`, `clock_offset_ms` | Local collection clock and exchange/local offset |
| `price`, `buy_ratio`, `buy_ratio_volume` | Market price and recent-flow features |
| `imbalance`, `volatility`, `spread` | Depth and market-context features |
| `trade_count`, `feature_lookback_s` | Feature-window evidence |
| `quality_flags` | Validation and timing diagnostics |
| `acquisition` | Per-endpoint success, error, latency, and retry diagnostics |

Duplicate exchange timestamps are retained only as diagnostics and are not accepted
into forecast history. Observations can be flagged for `crossed_market`,
`no_trades`, `empty_depth`, `stale_trades`, `missing_timestamp`,
`future_timestamp`, `stale_ticker`, `clock_skew`, `malformed_market_data`, or
`endpoint_skew`.

## Forecast Lifecycle

```text
accepted observations → warmup → one pending forecast
pending forecast → target time reached → future-trade label attempt
resolved forecast → eligibility decision → analysis or diagnostics only
```

The pending record is anchored to the exchange timestamp when present, otherwise the
local collection time. `target_at_ms` is `created_at_ms + horizon_s`. While any
forecast remains pending, the runner logs `SKIP forecast — pending unresolved`; this
is expected behavior, not a deadlock.

| Pending field | Meaning |
|---|---|
| `classical`, `prediction` | Recorded comparator and evaluated-policy prediction |
| `quantum_raw`, `classical_part`, `interference_term` | Born-path diagnostics |
| `delta`, `delta_source`, `bucket_feature` | Born-rule construction metadata |
| `fallback_reason` | Actual execution path, including gate/fallback outcomes |
| `signal`, `w_quantum`, `w_vol_regime` | Diagnostic signal and mode weights |
| `lookback_observation_ids` | Inputs used at forecast creation |

The evaluated prediction is the gated policy output. A raw Born value is not
automatically the scored output: negative/destructive behavior and constructive
overshoot or near-saturation can fall back to the classical component. Report
`fallback_reason` and active/fallback rates whenever interpreting results.

## Resolution and Label Contract

For a due forecast, the runner reads locally captured trades whose exchange
timestamps are **inclusively** within `[created_at_ms, target_at_ms]`. It computes
the future trade-count `buy_ratio` only when capture coverage is complete and the
window contains the horizon-scaled minimum number of trades.

| Field | Meaning |
|---|---|
| `resolved_actual` | Future-window target, or a diagnostic snapshot fallback |
| `resolved_label` | `forward_window` when valid; otherwise `label_unavailable` |
| `label_capture_complete`, `label_capture` | Coverage conclusion and batch metadata |
| `forward_window_*` | Window bounds, count, and required minimum |
| `classical_error`, `prediction_error` | Absolute errors against `resolved_actual` |
| `gross_return`, `cost`, `net_return`, `direction_up` | Secondary price/signal diagnostics only |
| `resolution_lag_s`, `entry_quality_flags`, `exit_quality_flags` | Timing and quality audit fields |
| `score_eligible` | Final primary-scoring decision |

`label_unavailable` uses the contemporaneous feature value only to preserve a
diagnostic record. It is never a substitute primary label and is not eligible for
score updates.

Disqualifying conditions include the observation quality flags above and
`late_resolution`, `short_forward_window`, or `label_unavailable`. A sparse but
otherwise complete window is retained as a diagnostic flag; eligibility remains
governed by the explicit disqualifying set.

## Historical Schemas

`SCHEMA_V3.md` and `SCHEMA_V5.md` describe past formats only. Pre-hardening v6
files without revision `v6r1` are also historical diagnostics. They may be inspected
with `--allow-pre-hardening-v6` but cannot establish claims for the v6r1 contract.
