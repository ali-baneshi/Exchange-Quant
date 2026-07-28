# Exchange-Q Runbook

This runbook is for operating the schema-v6r1 research evaluator. It is not a trading playbook.

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

If a previous run must be stopped before a fresh production start:

```bash
./scripts/stop_all_runs.sh
```

Evidence gates: [../artifacts/production-gate-status-2026-07-27.md](../artifacts/production-gate-status-2026-07-27.md)

## Canonical Production Run

```bash
./scripts/start_production_run.sh
```

The script runs tests, starts the v6r1 quantum study in the foreground, writes a PID
file for its lifetime, and appends output to `live_quantum_v3.log` (the filename is
legacy). Press `Ctrl-C` in the launching terminal for graceful shutdown; the PID
file is removed after the process exits.

| Parameter | Value | Operational meaning |
|---|---:|---|
| Symbol | `btcusdt` | Exchange pair |
| Mode | `quantum` | Frozen gated Born-policy arm |
| Horizon | `3600s` | Future label interval |
| Sample interval | `60s` | Feature and raw-trade capture cadence |
| Window | `15` | Accepted-observation warmup size |
| Completion | `720` eligible resolutions | Minimum primary-study target |

Live `buy_ratio` features use only the most recent `max(60, horizon_s)` seconds of
trades (`data_policy_version` 4). Raw trade pages are separately captured for
forward-window labels.

## What the Runner Stores

For each run:

```text
core/_live_results/<run_id>.sqlite3  authoritative durable data
core/_live_results/<run_id>.json     atomic schema-v6 export
```

SQLite stores accepted observations, forecast records, raw trade batches, and deduplicated raw trades. Raw trade capture is retained locally for 30 days. Do not delete a database while a run may need resume or audit.

## Monitoring

```bash
./scripts/monitor_live.sh
tail -f live_quantum_v3.log
```

Inspect:

- process/PID state;
- SQLite-backed schema/model/policy and `run_id`;
- number of observations, pending forecasts, and eligible resolutions;
- execution-path/fallback reasons and label status;
- capture failures, `label_unavailable`, endpoint skew, or repeated `NO DATA`.

## Label-Coverage Health

The primary target is valid only when the evaluator has locally captured enough trades across the full forecast interval.

| Signal | Meaning | Action |
|---|---|---|
| `resolved_label: forward_window` | Valid label source | Normal |
| `label_unavailable` | Incomplete capture or insufficient future trades | Excluded; inspect API/cadence/liquidity |
| `short_forward_window` | Too few trades | Excluded; do not substitute a snapshot |
| `capture_saturated` | Trade response reached configured limit | Diagnostic; excludes only when the full page does not overlap the prior capture frontier (possible missed trades). If holes appear, increase capture capacity or reduce interval |
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

The fast 60-second profile validates collection and label coverage. It is **not** a replacement for the one-hour, 720-resolution primary study, because market regime and microstructure differ. Exploratory 60s runs may show high buy_ratio noise: compare models against `MAE(constant 0.5)` before interpreting paired MAE. Price-based long simulation (`net_return`, hit rate) is diagnostic only and must not be treated as the primary metric.

The launcher remains in the foreground. Press `Ctrl-C` in the same terminal to stop
it gracefully; use the monitor and log-tail commands from another terminal only for
observation. `SKIP forecast — pending unresolved` is normal while the one permitted
pending forecast awaits its target time.

## Stop and Recover

```bash
./scripts/stop_all_runs.sh
```

The stop script sends `SIGTERM`, waits up to 15 seconds, then escalates only if necessary. It verifies process identities before signalling them. After stopping:

1. inspect the SQLite-backed monitor state and final JSON `status`/`stop_reason`;
2. keep the SQLite database;
3. use resume only with the same configuration;
4. archive a failed run separately rather than mixing it with a completed primary corpus.

## Analyze Results

```bash
python3 core/analyze_live_results.py --schema-version 6 --exclude-collector
python3 core/analyze_live_results.py --schema-version 6 --run-id btcusdt-quantum-EPOCH
```

The analyzer filters out historical files by default and includes only v6 records
with complete `forward_window` labels and `score_eligible: true`. JSON is an
inspectable export; SQLite remains authoritative for an active or recoverable run.

## Archive Legacy Results

```bash
./scripts/archive_legacy_results.sh
```

This moves pre-hardening v6 and older JSON from the active directory to
`_archive/pre_v6r1/`. Archive files may be inspected explicitly with
`--allow-pre-hardening-v6`, but they must not be aggregated with v6r1 primary data.

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
| Analyzer finds no files | Wrong schema/path or archived corpus | Use v6 command and verify result directory |
