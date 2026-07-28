# Snapshot وضعیت سیستم — 2026-07-27

> **snapshot تاریخی است.** این سند مربوط به schema v5/model v1 است. برای وضعیت
> فعلی به [snapshot ۲۸ ژوئیه](./SYSTEM_SNAPSHOT-2026-07-28.md) و مراجع v6 رجوع کنید.

**تاریخ snapshot:** 2026-07-27  
**Git commit (مرجع):** `5495b86` (worktree ممکن است dirty باشد)  
**Python تست‌شده:** 3.14 محلی؛ CI هدف 3.12  
**تعداد تست:** 94 passed

این فایل مرجع **همه درسنامه‌های پوشه `2026-07-27/`** است.

---

## هدف پروژه (یک جمله)

پلتفرم **تحقیق و ارزیابی** برای مقایسه پیش‌بینی Born-rule با baseline کلاسیک روی **buy_ratio زنده** — **بدون** اجرای سفارش واقعی.

---

## مسیرهای معتبر (2026-07-27)

| مسیر | هدف | claim علمی |
|------|-----|------------|
| `pipeline_live_ensemble.py` + Huobi | buy_ratio پیوسته، forward-window label | **تنها مسیر primary** (با n≥720، horizon 3600s) |
| `start_exploratory_run.sh` | horizon 60s، smoke infra | exploratory فقط — نه جایگزین production |
| `backtest.py` + klines | جهت باینری کندل | کلاسیک؛ **با live قابل مقایسه نیست** |
| `experiment.py` | شبیه‌ساز مصنوعی | تشخیصی |

---

## Schema و persistence

| مورد | مقدار |
|------|--------|
| schema خروجی live | **v5** |
| `label_policy` | `captured_trade_window_v1` |
| `data_policy_version` | **3** — feature lookback = `max(60, horizon_s)` |
| ذخیره canonical | SQLite WAL (`{run_id}.sqlite3`) |
| export JSON | `{run_id}.json` |
| `model_version` | `born_constructive_v1` |
| lock production | `.live_quantum_v5.lock` |
| archive legacy | `core/_live_results/_archive/pre_v5/` |
| فیلدهای کلیدی | `config_hash`, `run_id`, `resolved_label`, `label_capture_complete`, `forward_window_*`, `quantum_raw` |

---

## تنظیمات live (config.py)

| ثابت | مقدار | معنی |
|------|--------|------|
| `DEFAULT_WINDOW` | 15 | تعداد observation برای یک forecast |
| `DEFAULT_HORIZON_S` | 3600 | افق resolve (ثانیه) |
| `MIN_SIGNIFICANCE_N` | 720 | حداقل resolve برای claim primary |
| `MIN_FORWARD_WINDOW_TRADES` | 3 | حداقل trade در پنجره forward (60s) |
| `min_forward_trades(3600)` | 15 | حداقل trade برای label production |
| `FEATURE_LOOKBACK_FLOOR_S` | 60 | کف lookback feature |
| `N_HYPOTHESES_LIVE` | 1 | Bonferroni در live |
| `MAX_INTERFERENCE_BOOST` | 0.15 | آستانه saturation_gate |
| `MAX_ENDPOINT_SKEW_MS` | 5000 | آستانه skew بین ticker/depth |

---

## Runهای مرجع

| Run | نقش |
|-----|-----|
| `btcusdt-quantum-1785124007` | production (3600s) — stopped 2026-07-27، 4 resolve |
| `btcusdt-quantum-1785124079` | exploratory (60s) — **280 resolve** — [L09](./2026-07-27/09-tahlil-run-1785124079.md) |
| `btcusdt-quantum-1785119130` | exploratory ref (60s، post-fix) — آرشیو `_archive/exploratory-post-fix/` |

Baseline: [`artifacts/baseline-2026-07-26.md`](../../../artifacts/baseline-2026-07-26.md)  
Gate status: [`artifacts/production-gate-status-2026-07-27.md`](../../../artifacts/production-gate-status-2026-07-27.md)  
Exploratory summary: [`artifacts/exploratory-run-1785124079-2026-07-27.md`](../../../artifacts/exploratory-run-1785124079-2026-07-27.md)

---

## Runهای عملیاتی پیش‌فرض

### Production (primary evidence)

```bash
./scripts/stop_all_runs.sh
make test
./scripts/start_production_run.sh
# horizon=3600s sample=60s max-resolved=720
# log: live_quantum_v3.log  pid: live_quantum_v3.pid
./scripts/monitor_live.sh
```

### Exploratory (موازی، smoke)

```bash
./scripts/start_exploratory_run.sh
# horizon=60s sample=5s max-resolved=500
./scripts/monitor_exploratory.sh
```

---

## آمار و baseline

| n resolved eligible | سطح گزارش |
|---------------------|-----------|
| < 30 | diagnostics — بدون تفسیر aggregate |
| 30–719 | exploratory MAE — بدون significance claim |
| ≥ 720 | primary paired inference |

**Null baseline:** `MAE(constant 0.5)` — روی exploratory ref 60s ≈ 0.252 و هر دو مدل بدتر بودند (نویز microstructure، نه باگ infra).

تحلیل: `python3 core/analyze_live_results.py --schema-version 5`

---

## باگ‌ها / محدودیت‌های شناخته‌شده (صادقانه)

1. Runهای v3/v4 قدیمی و run با `n_steps` به‌جای `--max-resolved` **نامعتبر** برای claim.
2. `capture_saturated` روی API Huobi ≠ همیشه hole — v5 فقط وقتی frontier واقعاً hole دارد label را رد می‌کند.
3. `saturation_gate` ~78% روی exploratory ref — تا production n≥30 تغییر Born/gate **ممنوع**.
4. ادعای «سود معاملاتی» از pipeline **معتبر نیست** — price sim فقط diagnostic.

---

## فایل‌های مرجع

| موضوع | فایل |
|-------|------|
| schema | `docs/SCHEMA_V5.md` |
| pipeline | `core/pipeline_live_ensemble.py` |
| Born rule | `core/quantum_core.py` |
| داده زنده | `core/data_fetcher.py` |
| store / labels | `core/live_store.py` |
| تحلیل | `core/analyze_live_results.py` |
| runbook | `docs/RUNBOOK.md` |
