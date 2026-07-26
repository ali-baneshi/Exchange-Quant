# Exchange-Q Runbook

Operational guide for live evaluation and result analysis.

See also: [docs/README.md](./README.md) | [SCHEMA_V5.md](./SCHEMA_V5.md) | [STATISTICS.md](./STATISTICS.md) | [فارسی](./fa/README.md)

## Pipeline Selection

| Use case | Command |
|----------|---------|
| Production evaluation | `./scripts/start_production_run.sh` (recommended) or `python3 core/pipeline_live_ensemble.py btcusdt 720 3600 quantum` |
| Parallel exploratory (fast samples) | `./scripts/start_exploratory_run.sh` — runs alongside production; separate PID/log |
| Adaptive ensemble | `python3 core/pipeline_live_ensemble.py btcusdt 720 3600 ensemble` |
| Born smoke (born_active check) | `python3 core/pipeline_live_ensemble.py btcusdt 220 60 quantum 10 15` |
| Cron / one-shot | `python3 core/pipeline_one_shot.py` |
| Smoke test (seconds) | `python3 core/pipeline_real.py btcusdt 10 1.0` |
| Legacy long run | `python3 core/pipeline_live_long.py` (prefer ensemble pipeline) |

## Live Ensemble Parameters

```bash
python3 core/pipeline_live_ensemble.py SYMBOL N_STEPS HORIZON_S MODE [SAMPLE_INTERVAL] [WINDOW]
```

Example (720 hourly forecasts, 60s sampling):

```bash
python3 core/pipeline_live_ensemble.py btcusdt 720 3600 quantum 60 15
```

### Semantics

- **One pending forecast at a time** — new forecasts are skipped until the current horizon resolves.
- **Resolve-later** — predictions score against future `buy_ratio`, not the next fetch.
- **Schema v5** — output JSON includes a frozen experiment manifest, durable run ID, quality flags, and label provenance.
- **Born bucketing** — if `buy_ratio` window is flat, retries `imbalance` (live skips `buy_ratio_volume` — high bias in exploratory data). Research/backtest may still use volume bucket via `skip_volume_bucket=False`.
- **Saturation gate** — when Born prediction exceeds `classical_part + 0.15` or `pred >= 0.99`, reverts to `classical_part` (`fallback_reason: saturation_gate`).
- **Forward-window label** — `resolved_actual` uses locally captured trades in **`[created_at_ms, target_at_ms]`**. Incomplete capture or too few trades produces `label_unavailable`, which is excluded from scoring and model updates.
- **Live δ** — order-book δ mapped to **[0, π/2]** via `compute_delta()` (2026-07-26).

### 720 steps vs 43200 sample iterations

With **one pending forecast at a time**, `n_steps` is the maximum number of Huobi fetches, not the number of resolves.

| Config | Resolves (approx.) | Wall time |
|--------|-------------------|-----------|
| `720 3600 quantum 60 15` | Up to ~720 hourly resolves | ~30 days |
| `43200 3600 quantum 60 15` | Same ~720 resolves (more fetch budget) | ~30 days |

Use **720** as the production default (`start_production_run.sh`). Use **43200** only if you need extra sample iterations for warmup gaps or API downtime — it does not create parallel forecasts.

## Expected Runtime

| Config | Wall time (approx.) |
|--------|---------------------|
| 720 steps, horizon 3600s, sample 60s | Up to ~30 days (one forecast per hour) |
| Smoke born check: 220 steps, horizon 60s, sample 10s | ~40 minutes |
| Exploratory parallel: 500 resolves, horizon 60s, sample 5s | ~8–10 hours |
| Smoke: 10 steps, horizon 1s | ~20 seconds |

## Parallel exploratory collection

Run **in a second terminal** while production continues untouched. Exploratory uses a different `config_hash` (horizon 60s vs 3600s) so analyzer keeps results separate.

```bash
./scripts/start_exploratory_run.sh    # live_exploratory.pid / live_exploratory.log
./scripts/monitor_exploratory.sh
tail -f live_exploratory.log
```

Profile: `--horizon-s 60 --sample-interval-s 5 --window 15 --max-resolved 500`

- Warmup ~75s (15 fetches × 5s), then ~1 resolve per minute.
- **Exploratory tier only** — not a substitute for the 720-hourly production claim.
- Resume if interrupted (use `run_id` from log or JSON):

```bash
python3 core/pipeline_live_ensemble.py --resume btcusdt-quantum-EPOCH \
  --horizon-s 60 --sample-interval-s 5 --window 15 --max-resolved 500
```

Analyze exploratory only:

```bash
python3 core/analyze_live_results.py --schema-version 5 \
  core/_live_results/btcusdt-quantum-EPOCH.json
```

If Huobi rate-limits (`NO DATA` loops), increase sample interval to 10s in a manual command or edit the start script.

## Monitoring

```bash
./scripts/monitor_live.sh
./scripts/monitor_exploratory.sh   # if exploratory run active
tail -f live_quantum_v3.log
```

### Stop all runs

```bash
./scripts/stop_all_runs.sh
```

Stops production (`live_quantum_v3.pid`), exploratory (`live_exploratory.pid`), and any stray `pipeline_live_ensemble.py` processes.

**Do not restart production** until post-fix checks pass:

1. `make test` — all tests green
2. Exploratory gates after **30 resolves**:
   - `forward_window` label rate **> 80%**
   - `short_forward_window` **< 20%**
   - `saturation` at q>=0.99 **< 10%**
   - `bias pred-act` near zero
3. Monitor shows healthy forward-window coverage via `./scripts/monitor_exploratory.sh`

Restart criteria after exploratory validation:

```bash
./scripts/start_production_run.sh
# optional fast feedback (second terminal):
./scripts/start_exploratory_run.sh
```

Check output JSON in `core/_live_results/` (schema v5 only for new claims):

- `quality_flags` on observations — alert if rate > 5%
- `status: pending` vs `resolved` — resolve should occur near `target_at_ms`
- `score_eligible: false` — excluded from aggregate metrics (stale trades, empty depth)
- `fallback_reason: none` — Born interference active; track `born_active_rate`
- `fallback_reason: saturation_gate` — constructive overshoot capped; prediction reverted to classical part
- `fallback_reason: destructive_interference` — negative interference term; prediction reverted to classical part

Post-run summary:

```bash
python3 core/analyze_live_results.py --schema-version 5 --exclude-collector
python3 core/analyze_live_results.py --schema-version 5 --run-id btcusdt-quantum-XXXX
```

Legacy results live in `core/_live_results/_archive/pre_v5/` — do not include in aggregates. Default `analyze_live_results.py` scan skips `_archive/`; pass an explicit path to analyze an archived file:

```bash
python3 core/analyze_live_results.py core/_live_results/_archive/pre_v5/btcusdt_quantum_1785028289.json
```

## Interpreting Results

**Do not compare** kline backtest direction MAE to live buy_ratio MAE — different targets.

Report sample size, `born_active_rate`, and Bonferroni p-value with any new claim. Segmented output (all vs born_active_only) appears when n≥30.

## Clean Re-run Checklist

Before starting a new definitive run:

1. `make test` — all tests green
2. Archive legacy JSON to `_live_results/_archive/pre_v5/` if needed
3. Choose single protocol: `pipeline_live_ensemble.py` quantum mode
4. Record `run_id` from output JSON header
5. Analyze with `--schema-version 5 --exclude-collector` only
6. Wait for ≥30 resolved eligible predictions before exploratory summaries
7. Wait for ≥720 resolved eligible before significance claims

Production start (recommended):

```bash
./scripts/start_production_run.sh
```

Manual alternative:

```bash
nohup python3 core/pipeline_live_ensemble.py btcusdt 720 3600 quantum 60 15 \
  > live_quantum_v3.log 2>&1 &
echo $! > live_quantum_v3.pid
```

## Troubleshooting

| Symptom | Action |
|---------|--------|
| `NO DATA` loops | Huobi API down or rate-limited; check `quality_flags` |
| No forecasts after warmup | Pending still unresolved — wait for horizon |
| Empty bid/ask | Ticker incomplete; fetch retries automatically |
| High classical/quantum MAE both | Normal for buy_ratio; compare relative improvement |
| Born active rate near 0% | Check `fallback_reason` breakdown; bucketing retries volume/imbalance |
| Many `saturation_gate` | Constructive Born overshoot — check monitor `saturation` rate; should be <10% after fix |
| Many `destructive_interference` | Negative interference gated to classical — expected in mixed regimes; track rate in segmented analyze output |
| Low `born_active_rate` (<30%) | Flat buy_ratio windows — verify Huobi trade feed; check `quality_flags` rate |
