# درس ۵ — pipeline زنده: warmup، pending، resolve

> **درس تاریخی (schema v5/model v1).** برای فرمان، نسخه و محدودیت ادعای فعلی از
> snapshot ۲۸ ژوئیه و مراجع v6 استفاده کنید.

## مشخصات نسخه

| فیلد | مقدار |
|------|--------|
| تاریخ درس | 2026-07-27 |
| snapshot | [SYSTEM_SNAPSHOT-2026-07-27.md](../SYSTEM_SNAPSHOT-2026-07-27.md) |
| schema | **v5** |
| کد | `core/pipeline_live_ensemble.py`, `core/live_store.py` |

### تغییرات نسبت به 2026-07-26

- forecast record v5: `resolved_label`, `label_capture`, `forward_window_*`, `experiment_manifest`
- `data_policy_version` در config_hash

---

## CLI

```bash
python3 core/pipeline_live_ensemble.py \
  --symbol btcusdt --mode quantum \
  --horizon-s 3600 --sample-interval-s 60 \
  --window 15 --max-resolved 720
```

`--max-resolved` = تعداد **eligible resolve** — نه fetch. API قدیمی `n_steps` deprecated.

---

## forecast record (schema v5)

**pending:** `target_at_ms`, `lookback_observation_ids`, `quantum_raw`, `classical`, `config_hash`, `model_version`

**resolved:** `resolved_actual`, `resolved_label`, `label_capture`, `label_capture_complete`, `score_eligible`, errors

---

## persistence

| فایل | نقش |
|------|-----|
| `{run_id}.sqlite3` | canonical + trade_capture_batches |
| `{run_id}.json` | export |
| lock | `.live_quantum_v5.lock` (production script) |

---

## کار عملی

```bash
./scripts/stop_all_runs.sh
./scripts/start_production_run.sh
./scripts/monitor_live.sh
```

---

**بعد:** [L06](./06-dow-run-parallel.md)
