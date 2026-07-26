# Schema v5 Live Results

Schema v5 is the only live-result format eligible for primary research analysis.
It is emitted by `core/pipeline_live_ensemble.py` and analyzed with:

```bash
python3 core/analyze_live_results.py --schema-version 5 --exclude-collector
```

## Primary-evaluation contract

- `model_version` is frozen as `born_constructive_v1`.
- `experiment_manifest` records the model, label policy, metric, horizon, and
  resolved-forecast threshold for the run.
- Forecasts are scored only when `resolved_label` is `forward_window` and
  `score_eligible` is `true`.
- `resolved_label: label_unavailable` means the forward window did not have
  complete local trade capture or enough trades. It is diagnostic only.

## Required top-level fields

| Field | Meaning |
|---|---|
| `schema_version` | Always `5` |
| `run_id` | Durable run identifier |
| `config_hash` | Hash of the immutable runtime configuration |
| `experiment_manifest` | Frozen primary-study contract |
| `observations` | Accepted live feature snapshots |
| `predictions` | Pending and resolved forecasts |

## Resolved forecast fields

| Field | Meaning |
|---|---|
| `forward_window_start_ms` / `forward_window_end_ms` | Exact target interval |
| `forward_window_trade_count` | Locally captured trades used for the label |
| `label_capture_complete` | Whether capture coverage was complete |
| `label_capture` | Capture batch count, maximum gap, and saturation status |
| `resolved_label` | `forward_window` or `label_unavailable` |
| `score_eligible` | Whether the forecast is allowed in primary metrics |

## Retention

Raw trades and capture batches are held in the run SQLite database for 30 days.
The JSON result is an export of durable SQLite state; it is not the source of
truth for label reconstruction.
