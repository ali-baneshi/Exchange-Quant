# Schema v3 Live Results Reference (Legacy)

> Schema v3 is archived and is not eligible for primary analysis. Use
> [SCHEMA_V5.md](./SCHEMA_V5.md) for current runs.

Authoritative field reference for JSON written by [`pipeline_live_ensemble.py`](../core/pipeline_live_ensemble.py) and consumed by [`analyze_live_results.py`](../core/analyze_live_results.py).

See also: [RUNBOOK.md](./RUNBOOK.md), [STATISTICS.md](./STATISTICS.md).

---

## File location and corpus policy

| Location | Policy |
|----------|--------|
| `core/_live_results/*.json` | **Active** schema v3 runs for new claims |
| `core/_live_results/_archive/pre_v3/` | Legacy v2/v3 — do not mix in aggregates |
| `collected_*.json` | Raw feature lists — exclude with `--exclude-collector` |
| `state.json` | `pipeline_one_shot.py` state v2 — not schema v3 |

Default analyzer scan skips `_archive/`. Pass an explicit path to analyze archived files.

---

## Top-level document

Written atomically on each state change (`schema_version: 3`).

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | `3` | Required for definitive eval |
| `run_id` | string | e.g. `btcusdt-quantum-1785030717` |
| `symbol` | string | e.g. `btcusdt` |
| `mode` | string | `quantum` or `ensemble` |
| `horizon_s` | float | Forecast horizon in seconds |
| `sample_interval_s` | float | Seconds between Huobi fetches |
| `window` | int | Lookback size for forecasts |
| `observations` | array | All fetched feature snapshots |
| `predictions` | array | Forecast records (pending + resolved) |
| `ensemble_weights` | array | Optional; final weights in ensemble mode |
| `ensemble_performance` | object | Optional; recent error history per model |

---

## Observations

Each Huobi fetch appended to `observations[]`:

| Field | Description |
|-------|-------------|
| `timestamp` | Exchange ticker timestamp (ms) |
| `collected_at_ms` | Local wall clock when fetched |
| `price` | Close / last price |
| `buy_ratio` | Fraction of recent trades that were buys |
| `buy_ratio_volume` | Buy volume / total volume |
| `imbalance` | Order-book depth imbalance |
| `volatility` | Ticker high-low range / price |
| `spread` | Bid-ask spread / price |
| `quality_flags` | e.g. `no_trades`, `stale_trades`, `empty_depth` |
| `id`, `run_id`, `symbol`, `wall_time_ms`, `time` | Pipeline metadata |

Duplicate exchange timestamps get `duplicate_timestamp` flag and are not appended to forecast history.

---

## Predictions lifecycle

```
warmup (window observations) → create pending → wait horizon_s → resolve → repeat
```

Only **one pending** forecast at a time.

### Pending record (created)

| Field | Description |
|-------|-------------|
| `status` | `"pending"` |
| `created_at_ms` | Wall time when forecast created |
| `target_at_ms` | `created_at_ms + horizon_s * 1000` |
| `entry_price`, `entry_buy_ratio` | Snapshot at forecast time |
| `classical` | Classical ensemble prediction |
| `prediction` | Quantum (or ensemble) prediction |
| `signal` | `long` / `flat` / `no_trade` from thresholds |
| `delta`, `delta_source` | Interference phase metadata |
| `bucket_feature` | Which feature succeeded for bucketing |
| `fallback_reason` | See glossary below |
| `classical_part`, `interference_term` | Born diagnostics |
| `classical_models` | Per-model classical breakdown |

### Resolved record (added on resolve)

| Field | Description |
|-------|-------------|
| `status` | `"resolved"` |
| `resolved_at_ms`, `resolved_time` | When scored |
| `resolved_actual` | Future observation `buy_ratio` (target) |
| `exit_price` | Price at resolve |
| `classical_error` | \|classical − actual\| |
| `prediction_error` | \|prediction − actual\| |
| `score_eligible` | `false` if entry or exit had quality flags |
| `gross_return`, `cost`, `net_return` | Trading sim (long signals only) |

---

## `fallback_reason` glossary

| Value | Born active? | Meaning |
|-------|--------------|---------|
| `none` | **Yes** | Bucketing succeeded; interference term applied |
| `insufficient_history` | No | Fewer than `min_history` points; returns mean |
| `flat_history` | No | Variance too low to split buckets; returns mean |
| `single_bucket` | No | Median split produced empty high or low group |
| `destructive_interference` | No | Negative interference term; reverted to `classical_part` |

**Born active rate** in `analyze_live_results.py` = fraction with `fallback_reason == "none"` among eligible resolved predictions.

Bucketing tries, in order: `buy_ratio` → `buy_ratio_volume` → `imbalance`.

---

## `quality_flags` (observations)

| Flag | Effect |
|------|--------|
| `no_trades` | No recent trades for buy_ratio |
| `stale_trades` | Trade timestamps too clustered |
| `empty_depth` | No order-book liquidity |
| `missing_timestamp` | Ticker timestamp absent |
| `duplicate_timestamp` | Same exchange ts as prior obs — excluded from history |

Predictions with entry or exit quality flags get `score_eligible: false`.

---

## Example snippet

From a production v3 run (pending forecast):

```json
{
  "schema_version": 3,
  "run_id": "btcusdt-quantum-1785030717",
  "mode": "quantum",
  "horizon_s": 3600.0,
  "predictions": [{
    "status": "pending",
    "fallback_reason": "none",
    "bucket_feature": "buy_ratio",
    "delta": 2.03,
    "delta_source": "orderbook",
    "interference_term": -0.034,
    "classical": 0.299,
    "prediction": 0.197
  }]
}
```

Note: older runs may show δ > π/2 from before the 2026-07-26 live δ remap to [0, π/2].

---

## Analysis commands

```bash
# Active v3 corpus only
python3 core/analyze_live_results.py --schema-version 3 --exclude-collector

# Single run
python3 core/analyze_live_results.py --schema-version 3 --run-id btcusdt-quantum-XXXX

# Archived file (explicit path)
python3 core/analyze_live_results.py core/_live_results/_archive/pre_v3/btcusdt_quantum_1785028289.json
```
