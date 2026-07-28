# Exchange-Q Workflow Guide

These workflows intentionally produce different targets and evidence. Do not merge
their metrics or use a convenient result from one path to support a claim about
another.

## 1. Prepare

```bash
pip install -r requirements-dev.txt
make test
make compile
```

Runtime code is standard-library based; development checks use the development
requirements. Historical collection additionally needs `curl`.

## 2. Historical Classical Analysis

```bash
python3 core/data_historical.py
python3 core/backtest.py
python3 core/experiment_ablation.py
python3 core/validation_report.py --period 60min
```

This path evaluates classical methods on binary next-candle direction. Born-rule
market claims are deliberately out of scope, and its MAE is not comparable to live
trade-flow MAE.

## 3. Synthetic Diagnostics

```bash
python3 core/experiment.py
python3 core/visualize.py
```

Synthetic results can expose formula behavior and edge cases. They do not establish
out-of-sample market performance, profitability, or superiority over a baseline.

## 4. Production Live Evaluation

In terminal 1:

```bash
./scripts/start_production_run.sh
```

The script runs in the foreground. It starts the schema-v6r1 production configuration:

| Setting | Value |
|---|---:|
| Mode | `quantum` |
| Horizon | 3600 seconds |
| Capture interval | 60 seconds |
| Accepted-observation window | 15 |
| Completion target | 720 eligible resolutions |

In terminal 2 or later:

```bash
./scripts/monitor_live.sh
tail -f live_quantum_v3.log
```

The log filename is historical. The result contract is schema v6. `Ctrl-C` in
terminal 1 sends the intended graceful stop; use `./scripts/stop_all_runs.sh` only
when the owning terminal cannot be used.

## 5. Exploratory Infrastructure Run

```bash
./scripts/start_exploratory_run.sh
```

Then, from another terminal:

```bash
./scripts/monitor_exploratory.sh
tail -f live_exploratory.log
```

This 60-second profile is useful for collection, lifecycle, and observability
checks. It is exploratory and cannot replace the production primary corpus.

## 6. Interpret Live State

After warmup, the runner creates one pending forecast. It will then print:

```text
SKIP forecast — pending unresolved
```

until the forecast’s target is due and the future trade window can be resolved. This
is expected protocol behavior. The monitor’s SQLite-backed state is the authority;
JSON exports are inspectable snapshots.

A resolved record is primary eligible only when:

```text
resolved_label == "forward_window"
label_capture_complete == true
score_eligible == true
```

`label_unavailable`, partial capture, timing/quality failures, and stale data are
excluded from primary scoring but should be investigated as operational diagnostics.

## 7. Resume or Analyze

Resume only the same configuration and schema:

```bash
python3 core/pipeline_live_ensemble.py \
  --resume btcusdt-quantum-EPOCH \
  --horizon-s 3600 \
  --sample-interval-s 60 \
  --window 15 \
  --max-resolved 720
```

Analyze current v6r1 rows:

```bash
python3 core/analyze_live_results.py --schema-version 6 --exclude-collector
python3 core/analyze_live_results.py --schema-version 6 --run-id btcusdt-quantum-EPOCH
```

Archive legacy results separately:

```bash
./scripts/archive_legacy_results.sh
```

The archive command moves pre-hardening v6 and older formats to
`_archive/pre_v6r1/`. Historical v6 inspection requires
`--allow-pre-hardening-v6`.

## 8. Report Conservatively

| Eligible observations | Permitted conclusion |
|---:|---|
| `< 30` | Pipeline and data-quality diagnostics only |
| `30–719` | Exploratory descriptive comparison only |
| `≥ 720` | Frozen paired inference under `docs/STATISTICS.md` |

Always report the run identity, configuration hash, exclusions, model and classical
MAE, `MAE(constant 0.5)`, paired inference, and execution-path/fallback rates.
Win rate and price-return fields are secondary diagnostics; they do not demonstrate
trading profitability.
