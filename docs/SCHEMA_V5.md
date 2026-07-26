# Schema v5 — Live Evaluation Contract

Schema v5 is the only result format eligible for the current primary live study. It is written by `core/pipeline_live_ensemble.py`, stored durably in SQLite through `core/live_store.py`, and analyzed with:

```bash
python3 core/analyze_live_results.py --schema-version 5 --exclude-collector
```

## Contract and Invariants

| Rule | Requirement |
|---|---|
| Model identity | `model_version == "born_constructive_v1"` |
| Label policy | `experiment_manifest.label_policy == "captured_trade_window_v1"` |
| Primary target | Trade-count `buy_ratio` from the exact future interval |
| Primary score eligibility | `resolved_label == "forward_window"`, `label_capture_complete == true`, and `score_eligible == true` |
| Corpus isolation | Never aggregate schema v2–v4 with v5 |
| Durable source | SQLite is authoritative; JSON is an inspectable export |

## Top-Level Document

| Field | Type | Description |
|---|---|---|
| `schema_version` | integer | Always `5` for current runs |
| `run_id` / `experiment_id` | string | Stable identifier used for resume and reporting |
| `config_hash` | string | SHA-256 hash of the runtime configuration |
| `model_version` | string | Frozen model identity |
| `data_policy_version` | integer | Data/label policy revision |
| `experiment_manifest` | object | Frozen study contract: model, label policy, metric, horizon, threshold |
| `symbol`, `mode` | string | Exchange pair and `quantum` or `ensemble` mode |
| `horizon_s`, `sample_interval_s`, `window` | number/integer | Forecast and collection configuration |
| `status`, `stop_reason` | string | Run lifecycle state |
| `observations` | array | Accepted feature snapshots |
| `predictions` | array | Pending and resolved forecast records |

## Observation Fields

An observation is accepted once per exchange timestamp. Duplicate timestamps are retained for diagnostics but excluded from forecast history.

| Field | Meaning |
|---|---|
| `timestamp`, `wall_time_ms`, `collected_at_ms` | Exchange and local collection clocks |
| `price`, `buy_ratio`, `buy_ratio_volume` | Market and trade-flow features |
| `imbalance`, `volatility`, `spread` | Order-book and market-context features |
| `trade_count`, `trade_window_*` | Properties of the latest fetched trade response |
| `quality_flags` | Data-quality diagnostics |

Important flags include `no_trades`, `stale_trades`, `empty_depth`, `crossed_market`, `endpoint_skew`, and `duplicate_timestamp`.

## Forecast Lifecycle

```text
accepted observations → warmup → pending forecast
pending forecast + locally captured future trades → resolved forecast
resolved forecast + valid label/quality → primary-eligible score
```

Only one pending forecast is allowed. A forecast stores its original raw model predictions so later ensemble updates do not leak future information.

### Pending Record

| Field | Meaning |
|---|---|
| `id`, `step`, `status: "pending"` | Stable forecast identity |
| `created_at_ms`, `target_at_ms`, `horizon_s` | Exact label interval |
| `lookback_observation_ids` | Inputs used at forecast creation |
| `classical`, `prediction` | Classical and active-model forecasts |
| `quantum_raw`, `vol_regime_raw` | Frozen component predictions |
| `delta`, `delta_source`, `bucket_feature` | Born-rule diagnostics |
| `fallback_reason`, `classical_part`, `interference_term` | Interference behavior |

### Resolved Record

| Field | Meaning |
|---|---|
| `resolved_actual` | Label used for diagnostics or scoring |
| `resolved_label` | `forward_window` or `label_unavailable` |
| `forward_window_start_ms`, `forward_window_end_ms` | Inclusive trade-label interval |
| `forward_window_trade_count`, `forward_window_min_trades` | Label sample-size evidence |
| `label_capture_complete` | Whether local trade capture covered the full interval |
| `label_capture` | Capture batch count, max gap, and saturation state |
| `classical_error`, `prediction_error` | Paired absolute errors |
| `score_eligible` | Final primary-analysis inclusion decision |
| `entry_quality_flags`, `exit_quality_flags` | Reasons a record may be excluded |

## Label and Quality Policy

`forward_window` is the only valid primary label. The pipeline rejects a primary score if:

- fewer than `min_forward_trades(horizon_s)` trades occur in the interval;
- local capture does not cover the interval;
- a captured response is saturated at the request limit;
- capture gaps exceed the allowed sampling tolerance;
- entry or exit carries a disqualifying quality flag;
- resolution is excessively late.

The record may still contain a snapshot value for diagnosis, but `resolved_label: "label_unavailable"` and `score_eligible: false` prevent it from changing statistics or ensemble weights.

## Migration and Compatibility

| Version | Status | Handling |
|---|---|---|
| v2 | Legacy | Archive; never aggregate with v5 |
| v3 | Legacy | Historical resolve-later format; labels are not v5-verifiable |
| v4 | Legacy | Durable run format before strict local-label policy |
| v5 | Current | Required for primary analysis |

Use `scripts/archive_legacy_results.sh` to move non-v5 JSON out of the active corpus. `docs/SCHEMA_V3.md` remains only as a historical field reference.
