# راهنمای سریع عملیاتی

**English:** [../../WORKFLOW.md](../../WORKFLOW.md) | **واژه‌نامه:** [GLOSSARY.md](./GLOSSARY.md)

---

## پیش‌نیاز

```bash
python3 --version   # ۳.۸+
command -v curl     # برای data_historical.py
cd Exchange-Q
make test           # ۶۶ تست سبز
```

---

## گام ۱: داده تاریخی

```bash
python3 core/data_historical.py
```

خروجی در `core/_kline_cache/` — ۵۰۰۰ کندل برای ۱۵min، ۶۰min، ۱day.

---

## گام ۲: بک‌تست کلاسیک

```bash
python3 core/backtest.py
python3 core/experiment_ablation.py
```

هدف: **جهت باینری** کندل بعدی. قانون Born در این مسیر **حذف شده** (۲۰۲۶-۰۷-۲۳).

---

## گام ۳: گزارش اعتبارسنجی

```bash
python3 core/validation_report.py --period 60min
python3 core/validation_report.py --period 60min --output report_60min.json
```

کلاسیک روی کندل + وضعیت فایل‌های live روی دیسک.

---

## گام ۴: آزمایش مصنوعی (اختیاری)

```bash
python3 core/experiment.py
python3 core/visualize.py
```

در داده مصنوعی کوانتوم معمولاً **بدتر** از کلاسیک است — فقط تشخیصی.

---

## گام ۵: pipeline زنده (مسیر معتبر Born)

### شروع تولید (توصیه‌شده)

```bash
./scripts/start_production_run.sh
```

این اسکریپت `make test` را اجرا می‌کند و سپس:

```bash
python3 core/pipeline_live_ensemble.py btcusdt 720 3600 quantum 60 15
```

### پارامترها

| آرگومان | مثال | معنی |
|---------|------|------|
| symbol | btcusdt | جفت معاملاتی |
| n_steps | 720 | حداکثر تکرار نمونه‌گیری |
| horizon | 3600 | افق پیش‌بینی (ثانیه) |
| mode | quantum | حالت کوانتومی خالص |
| sample_interval | 60 | فاصله fetch از Huobi |
| window | 15 | اندازه lookback |

### معنی ۷۲۰ در برابر ۴۳۲۰۰

- فقط **یک forecast pending** در هر لحظه.
- با `horizon=3600` و `sample_interval=60`، هر ساعت یک forecast resolve می‌شود.
- **۷۲۰ n_steps** ≈ حداکثر ۷۲۰ resolve (حدود ۳۰ روز).
- **۴۳۲۰۰ n_steps** = ۷۲۰ ساعت × ۶۰ fetch/ساعت — همان تعداد resolve، با حاشیه بیشتر برای warmup و تأخیر.

---

## گام ۶: پایش و تحلیل

```bash
./scripts/monitor_live.sh
tail -f live_quantum_v3.log

python3 core/analyze_live_results.py --schema-version 3 --exclude-collector
python3 core/analyze_live_results.py --schema-version 3 --run-id btcusdt-quantum-XXXX
```

### آستانه ادعا

| n (resolved eligible) | گزارش |
|----------------------|--------|
| < 30 | فقط تشخیصی |
| ≥ 30 | خلاصه exploratory مجاز |
| ≥ 720 | ادعای معناداری تولید |

---

## چک‌لیست قبل از ادعای جدید

1. فقط JSON با `schema_version: 3`
2. `--exclude-collector` — فایل‌های collector را حذف کن
3. `born_active_rate` (`fallback_reason=none`) را گزارش کن
4. p-value Bonferroni را ذکر کن
5. v2 آرشیو را با v3 مخلوط نکن

---

## عیب‌یابی سریع

| علامت | اقدام |
|-------|-------|
| `NO DATA` | API Huobi — `quality_flags` را ببین |
| forecast نمی‌سازد | pending هنوز resolve نشده — صبر کن |
| `born_active_rate` ≈ 0 | `fallback_reason` را در analyze ببین |
| `destructive_interference` | تداخل منفی — پیش‌بینی به classical_part برگشت |

جزئیات: [../RUNBOOK.md](../RUNBOOK.md)
