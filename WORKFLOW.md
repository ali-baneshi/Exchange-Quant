# Exchange-Q Workflow Guide

This guide describes the complete research workflow. Start with the section matching your goal; do not treat every command as part of one comparable experiment.

## 1. Prepare the Environment

```bash
python3 --version
command -v curl
pip install -r requirements-dev.txt
make test
make compile
```

Runtime code uses the Python standard library. `pytest` is a development dependency. Historical collection requires `curl`.

## 2. Classical Historical Analysis

Use this path to check data ordering and classical baselines on historical OHLCV.

```bash
python3 core/data_historical.py
python3 core/backtest.py
python3 core/experiment_ablation.py
python3 core/validation_report.py --period 60min
```

### What this path means

- Data source: Gate.io OHLCV cache with Huobi fallback.
- Target: binary next-candle direction.
- Born rule: intentionally excluded.
- Output: classical MAE and diagnostic validation statistics.

Do not compare this MAE to live `buy_ratio` MAE. The target, data source, and difficulty are different.

## 3. Synthetic Diagnostics

```bash
python3 core/experiment.py
python3 core/visualize.py
```

The simulator is useful for checking formulas and failure modes. It is not an out-of-sample market test and must not be used to support a trading or model-efficacy claim.

## 4. Start the Frozen Live Study

The only primary Born-rule path is the durable schema-v5 evaluator.

```bash
./scripts/start_production_run.sh
```

Equivalent explicit command:

```bash
python3 core/pipeline_live_ensemble.py \
  --symbol btcusdt \
  --mode quantum \
  --horizon-s 3600 \
  --sample-interval-s 60 \
  --window 15 \
  --max-resolved 720
```

### Configuration semantics

| Option | Production value | Meaning |
|---|---:|---|
| `--horizon-s` | `3600` | Future label interval in seconds |
| `--sample-interval-s` | `60` | Feature/trade capture cadence |
| `--window` | `15` | Accepted observation lookback |
| `--max-resolved` | `720` | Eligible resolved forecasts required before successful completion |
| `--mode` | `quantum` | Frozen Born-only model; `ensemble` is a separate configuration |

Only one forecast is pending at a time. With a one-hour horizon, 720 eligible resolutions usually require about 30 days, plus any excluded data-quality intervals.

## 5. Monitor, Resume, and Stop

```bash
./scripts/monitor_live.sh
./scripts/stop_all_runs.sh
```

To resume an interrupted run, use the `run_id` printed at startup:

```bash
python3 core/pipeline_live_ensemble.py \
  --resume btcusdt-quantum-EPOCH \
  --horizon-s 3600 \
  --sample-interval-s 60 \
  --window 15 \
  --max-resolved 720
```

Resume succeeds only if the stored configuration hash matches the requested configuration.

## 6. Analyze Results

```bash
python3 core/analyze_live_results.py --schema-version 5 --exclude-collector
python3 core/analyze_live_results.py --schema-version 5 --run-id btcusdt-quantum-EPOCH
```

The analyzer includes only v5 records that have:

```text
resolved_label == "forward_window"
label_capture_complete == true
score_eligible == true
```

Legacy v2–v4 files are historical artifacts. Move them out of the active corpus with:

```bash
./scripts/archive_legacy_results.sh
```

## 7. Interpret Results Safely

| Eligible sample size | Allowed conclusion |
|---:|---|
| `< 30` | Pipeline/data-quality diagnostics only |
| `30–719` | Exploratory descriptive comparison only |
| `≥ 720` | Run the frozen paired statistical analysis |

Every report must state the run ID, configuration hash, model version, eligible sample count, excluded-label reasons, MAE comparison, and corrected p-value. See `docs/STATISTICS.md`.

## 8. Common Mistakes

| Mistake | Correct practice |
|---|---|
| Comparing kline and live MAE | Treat them as different tasks |
| Using a snapshot label after a missing trade window | Keep as diagnostic; exclude from score |
| Mixing old JSON with v5 data | Archive v2–v4 before aggregate analysis |
| Restarting with changed parameters | Start a new run; do not resume |
| Reading an exploratory win rate as evidence | Wait for the frozen threshold and paired inference |
