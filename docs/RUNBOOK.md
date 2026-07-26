# Exchange-Q Runbook

This runbook is for operating the schema-v5 research evaluator. It is not a trading playbook.

## Before You Start

```bash
pip install -r requirements-dev.txt
make test
make compile
```

Confirm no production run is already active:

```bash
./scripts/monitor_live.sh
```

## Canonical Production Run

```bash
./scripts/start_production_run.sh
```

The script runs tests, holds a production lock for the process lifetime, starts the v5 quantum study, writes a PID file, and appends output to `live_quantum_v3.log` (the filename is legacy; the result schema is v5).

| Parameter | Value | Operational meaning |
|---|---:|---|
| Symbol | `btcusdt` | Exchange pair |
| Mode | `quantum` | Frozen Born-only arm |
| Horizon | `3600s` | Future label interval |
| Sample interval | `60s` | Feature and raw-trade capture cadence |
| Window | `15` | Accepted-observation warmup size |
| Completion | `720` eligible resolutions | Minimum primary-study target |

## What the Runner Stores

For each run:

```text
core/_live_results/<run_id>.sqlite3  authoritative durable data
core/_live_results/<run_id>.json     atomic schema-v5 export
```

SQLite stores accepted observations, forecast records, raw trade batches, and deduplicated raw trades. Raw trade capture is retained locally for 30 days. Do not delete a database while a run may need resume or audit.

## Monitoring

```bash
./scripts/monitor_live.sh
tail -f live_quantum_v3.log
```

Inspect:

- process/PID state;
- current JSON schema and `run_id`;
- number of observations, pending forecasts, and eligible resolutions;
- `born_active_rate`, fallback reasons, and label status;
- capture failures, `label_unavailable`, endpoint skew, or repeated `NO DATA`.

## Label-Coverage Health

The primary target is valid only when the evaluator has locally captured enough trades across the full forecast interval.

| Signal | Meaning | Action |
|---|---|---|
| `resolved_label: forward_window` | Valid label source | Normal |
| `label_unavailable` | Incomplete capture or insufficient future trades | Excluded; inspect API/cadence/liquidity |
| `short_forward_window` | Too few trades | Excluded; do not substitute a snapshot |
| `capture_saturated` | Trade response reached configured limit | Excluded; increase capture capacity or reduce interval |
| `late_resolution` | Resolution missed the timing tolerance | Excluded; inspect process/API health |

Before relying on an exploratory run, verify that eligible labels—not merely resolved records—are accumulating.

## Resume

Find the `run_id` in the log or JSON export:

```bash
python3 core/pipeline_live_ensemble.py \
  --resume btcusdt-quantum-EPOCH \
  --horizon-s 3600 \
  --sample-interval-s 60 \
  --window 15 \
  --max-resolved 720
```

The runner refuses resume when the requested configuration hash differs from the stored run. Start a new run instead of changing model, horizon, interval, or window mid-study.

## Exploratory Runs

```bash
./scripts/start_exploratory_run.sh
./scripts/monitor_exploratory.sh
```

The fast 60-second profile is useful for validating collection and label coverage. It is **not** a replacement for the one-hour, 720-resolution primary study, because market regime and microstructure differ.

## Stop and Recover

```bash
./scripts/stop_all_runs.sh
```

The stop script sends `SIGTERM`, waits, then escalates if necessary. After stopping:

1. inspect the final JSON `status` and `stop_reason`;
2. keep the SQLite database;
3. use resume only with the same configuration;
4. archive a failed run separately rather than mixing it with a completed primary corpus.

## Analyze Results

```bash
python3 core/analyze_live_results.py --schema-version 5 --exclude-collector
python3 core/analyze_live_results.py --schema-version 5 --run-id btcusdt-quantum-EPOCH
```

The analyzer filters out v2–v4 files by default and includes only v5 records with complete `forward_window` labels and `score_eligible: true`.

## Archive Legacy Results

```bash
./scripts/archive_legacy_results.sh
```

This moves non-v5 JSON from the active directory to `_archive/pre_v5/`. Archive files may be inspected explicitly, but they must not be aggregated with v5 primary data.

## Go / No-Go Rules

| Condition | Decision |
|---|---|
| Tests/compile/shell checks fail | No-go: fix before collection |
| Repeated `NO DATA`, skew, or capture saturation | No-go: diagnose feed/cadence |
| Labels are mostly `label_unavailable` | No-go: do not interpret model metrics |
| Fewer than 30 eligible resolutions | Diagnostics only |
| 30–719 eligible resolutions | Exploratory only |
| 720+ eligible resolutions, frozen config | Run paired primary inference |

## Troubleshooting

| Symptom | Likely cause | Response |
|---|---|---|
| No forecast after warmup | Existing forecast is pending | Wait until target time |
| Run exits with configuration error | Resume arguments differ | Use exact original settings or start new |
| Eligible count does not increase | Labels/quality are being rejected | Inspect flags and capture diagnostics |
| Many `saturation_gate` records | Constructive Born output is capped | Treat as model diagnostic, not a data error |
| Many `destructive_interference` records | Negative interference reverts to classical part | Expected safeguard; inspect as exploratory segment |
| Analyzer finds no files | Wrong schema/path or archived corpus | Use v5 command and verify result directory |
