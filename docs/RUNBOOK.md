# Exchange-Q Runbook

Operational guide for live evaluation and result analysis.

## Pipeline Selection

| Use case | Command |
|----------|---------|
| Production evaluation | `python3 core/pipeline_live_ensemble.py btcusdt 720 3600 quantum` |
| Adaptive ensemble | `python3 core/pipeline_live_ensemble.py btcusdt 720 3600 ensemble` |
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
- **Schema v3** — output JSON includes `run_id`, `quality_flags`, and ensemble weights when applicable.

## Expected Runtime

| Config | Wall time (approx.) |
|--------|---------------------|
| 720 steps, horizon 3600s, sample 60s | Up to ~30 days (one forecast per hour) |
| Smoke: 10 steps, horizon 1s | ~20 seconds |

## Monitoring

Check output JSON in `core/_live_results/`:

- `quality_flags` on observations — alert if rate > 5%
- `status: pending` vs `resolved` — resolve should occur near `target_at_ms`
- `score_eligible: false` — excluded from aggregate metrics (stale trades, empty depth)

Post-run summary:

```bash
python3 core/analyze_live_results.py
```

## Interpreting Results

**Do not compare** kline backtest direction MAE to live buy_ratio MAE — different targets.

As of 2026-07-26, aggregate live quantum runs show **negative** improvement vs classical. Report sample size and Bonferroni p-value with any new claim.

## Clean Re-run Checklist

Before starting a new definitive run:

1. `make test` — all 52 tests green
2. Choose single protocol: `pipeline_live_ensemble.py` quantum mode
3. Record `run_id` from output JSON header
4. Do not mix pre-2026-07-26 corpus with schema v3 runs in aggregates
5. Wait for ≥30 resolved eligible predictions before exploratory summaries

## Troubleshooting

| Symptom | Action |
|---------|--------|
| `NO DATA` loops | Huobi API down or rate-limited; check `quality_flags` |
| No forecasts after warmup | Pending still unresolved — wait for horizon |
| Empty bid/ask | Ticker incomplete; fetch retries automatically |
| High classical/quantum MAE both | Normal for buy_ratio; compare relative improvement |
