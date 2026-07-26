# Exchange-Q — خلاصه فارسی

**English:** [README.md](./README.md) | **فهرست مستندات:** [docs/fa/README.md](./docs/fa/README.md)

---

## هدف پروژه

Exchange-Q مدل‌های **تداخل Born** (الهام‌گرفته از احتمال کوانتومی) را برای پیش‌بینی رفتار بازار اعمال می‌کند — بدون نیاز به سخت‌افزار کوانتومی.

**وضعیت (۱۴۰۵/۰۵/۰۴ — ۲۰۲۶-۰۷-۲۶):**

- قانون Born از ارزیابی **کندل تاریخی** حذف شده است (p=1.0 روی ۵۰۰۰ کندل).
- مسیر معتبر کوانتومی: **pipeline زنده با order-book** (`pipeline_live_ensemble.py`).
- تعمیرات مدل: δ زنده در بازه **[0, π/2]**؛ در تداخل مخرب → `destructive_interference`.
- خروجی schema v3 با `run_id`؛ تحلیل فقط با `--schema-version 3`.

---

## دستورات اصلی

```bash
# داده تاریخی + بک‌تست کلاسیک
python3 core/data_historical.py
python3 core/backtest.py

# گزارش اعتبارسنجی (کلاسیک + وضعیت live)
python3 core/validation_report.py --period 60min

# آزمایش مصنوعی (کنترل‌شده)
python3 core/experiment.py

# اجرای تولید (تست‌ها + pipeline کوانتومی)
./scripts/start_production_run.sh

# پایش
./scripts/monitor_live.sh

# تحلیل نتایج v3
python3 core/analyze_live_results.py --schema-version 3 --exclude-collector
```

---

## مسیر معتبر Born

| مسیر | هدف | وضعیت |
|------|-----|--------|
| `pipeline_live_ensemble.py` | `buy_ratio` پیوسته از Huobi | **فعال — تنها مسیر کوانتومی معتبر** |
| `backtest.py` | جهت باینری کندل | کلاسیک فقط |
| `experiment.py` | شبیه‌ساز مصنوعی | تشخیصی — کوانتوم معمولاً بدتر |

---

## وضعیت تجربی

- داده live قدیمی (v2): کوانتوم ~۲× بدتر از کلاسیک.
- re-run تمیز schema v3 در جریان است؛ قبل از n≥۳۰ resolved eligible ادعای برد مطرح نکنید.
- جزئیات: [verification_report.md](./verification_report.md)، [docs/STATISTICS.md](./docs/STATISTICS.md).

---

## مستندات

| سند | موضوع |
|-----|--------|
| [docs/fa/darsname/README.md](./docs/fa/darsname/README.md) | **درسنامه‌های فارسی** (نسخه‌بندی + Q&A) |
| [docs/fa/QUICKSTART.md](./docs/fa/QUICKSTART.md) | راهنمای عملیاتی گام‌به‌گام |
| [docs/fa/GLOSSARY.md](./docs/fa/GLOSSARY.md) | واژه‌نامه (δ، buy_ratio، fallback) |
| [docs/RUNBOOK.md](./docs/RUNBOOK.md) | عملیات pipeline زنده (انگلیسی) |
| [core/research_INDEX.md](./core/research_INDEX.md) | پل تحقیقات فارسی → کد |

---

## تست‌ها

```bash
make test   # ۶۶ تست
```
