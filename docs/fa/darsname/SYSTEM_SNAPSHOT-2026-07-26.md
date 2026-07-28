# Snapshot وضعیت سیستم — 2026-07-26

> **Superseded:** نسخه فعلی: [SYSTEM_SNAPSHOT-2026-07-27.md](./SYSTEM_SNAPSHOT-2026-07-27.md) — schema **v5**.

**تاریخ snapshot:** 2026-07-26 08:38 (+0330)  
**Git commit (مرجع):** `5495b86` (worktree ممکن است dirty باشد)  
**Python تست‌شده:** 3.14 محلی؛ CI هدف 3.12  
**تعداد تست:** 81 passed

این فایل مرجع **همه درسنامه‌های پوشه `2026-07-26/`** است. اگر commit یا تنظیمات عوض شد، snapshot جدید بسازید.

---

## هدف پروژه (یک جمله)

پلتفرم **تحقیق و ارزیابی** برای مقایسه پیش‌بینی Born-rule با baseline کلاسیک روی **buy_ratio زنده** — **بدون** اجرای سفارش واقعی.

---

## مسیرهای معتبر (2026-07-26)

| مسیر | هدف | claim علمی |
|------|-----|------------|
| `pipeline_live_ensemble.py` + Huobi | buy_ratio پیوسته، resolve-later | **تنها مسیر primary** (با n≥720) |
| `start_exploratory_run.sh` | horizon 60s، نمونه سریع | exploratory فقط |
| `backtest.py` + klines | جهت باینری کندل | کلاسیک؛ **با live قابل مقایسه نیست** |
| `experiment.py` | شبیه‌ساز مصنوعی | تشخیصی |

---

## Schema و persistence

| مورد | مقدار |
|------|--------|
| schema خروجی live | **v4** |
| ذخیره canonical | SQLite WAL (`{run_id}.sqlite3`) |
| export JSON | `{run_id}.json` |
| model_version | `born_v3_constructive_gate` |
| فیلدهای کلیدی | `config_hash`, `run_id`, `lookback_observation_ids`, `quantum_raw` |

---

## تنظیمات live (config.py)

| ثابت | مقدار | معنی |
|------|--------|------|
| `DEFAULT_WINDOW` | 15 | تعداد observation برای یک forecast |
| `DEFAULT_HORIZON_S` | 3600 | افق resolve (ثانیه) |
| `MIN_SIGNIFICANCE_N` | 720 | حداقل resolve برای claim primary |
| `N_HYPOTHESES_LIVE` | 1 | Bonferroni در live |
| `FEE_RATE` | 0.001 | شبیه‌سازی هزینه (نه معامله واقعی) |
| `MAX_ENDPOINT_SKEW_MS` | 5000 | آستانه skew بین ticker/depth |

---

## Runهای عملیاتی پیش‌فرض

### Production (primary evidence)

```bash
./scripts/start_production_run.sh
# --horizon-s 3600 --sample-interval-s 60 --max-resolved 720
# log: live_quantum_v3.log  pid: live_quantum_v3.pid
```

### Exploratory (موازی، سریع)

```bash
./scripts/start_exploratory_run.sh
# --horizon-s 60 --sample-interval-s 5 --max-resolved 500
# log: live_exploratory.log  pid: live_exploratory.pid
```

---

## آمار (validation.py)

| n resolved eligible | سطح گزارش |
|---------------------|-----------|
| < 30 | فقط diagnostics |
| 30–719 | exploratory — بدون significance claim |
| ≥ 720 | primary analysis |

روش: paired moving-block bootstrap روی **میانگین اختلاف خطا** (نه «White's RC» کلاسیک روی win rate).

---

## باگ‌ها / محدودیت‌های شناخته‌شده (صادقانه)

1. Runهای v3 قدیمی با `n_steps=720` **نامعتبر** برای claim 720 ساعته (fetch ≠ resolve).
2. δ زنده به **[0, π/2]** محدود است — فرضیه تداخل کامل signed ارزیابی نمی‌شود.
3. `README.fa.md` هنوز schema v3 و 66 تست می‌گوید — **این snapshot v4 و 81 تست را مرجع بدانید**.
4. ادعای «سود معاملاتی» از pipeline **معتبر نیست** — فقط خطای buy_ratio و شبیه‌سازی signal.

---

## فایل‌های مرجع کد

| موضوع | فایل |
|-------|------|
| pipeline اصلی | `core/pipeline_live_ensemble.py` |
| Born rule | `core/quantum_core.py` |
| داده زنده | `core/data_fetcher.py` |
| تحلیل نتایج | `core/analyze_live_results.py` |
| آمار | `core/validation.py` |
| runbook | `docs/RUNBOOK.md` |
