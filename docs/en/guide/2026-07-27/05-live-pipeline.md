# Lesson 05 — Live Pipeline

> **Historical lesson (schema v5/model v1).** Use the July 28, 2026 snapshot and
> current v6 references for commands, identities, and evidence limits.

| Date | 2026-07-27 | Schema | v5 |

---

## Loop

1. Fetch observation (+ capture trades)
2. Warmup until `window` observations
3. Create one **pending** forecast
4. Wait until `target_at_ms` → resolve with forward-window label
5. Stop at `--max-resolved` **eligible** resolves

Only one pending forecast at a time → `SKIP forecast — pending unresolved` is normal.

---

## CLI (named flags)

```bash
python3 core/pipeline_live_ensemble.py \
  --symbol btcusdt --mode quantum \
  --horizon-s 3600 --sample-interval-s 60 \
  --window 15 --max-resolved 720
```

Legacy positional `n_steps` API is deprecated.

---

## v5 forecast fields

`experiment_manifest`, `data_policy_version`, `resolved_label`, `label_capture`, `forward_window_min_trades`, `score_eligible`

---

## Production start

```bash
./scripts/stop_all_runs.sh
./scripts/start_production_run.sh
./scripts/monitor_live.sh
```

**Next:** [06-parallel-runs.md](./06-parallel-runs.md)
