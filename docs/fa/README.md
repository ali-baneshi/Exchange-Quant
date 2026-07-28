# فهرست مستندات فارسی Exchange-Q

**English:** [../README.md](../README.md) | **خلاصه فارسی:** [../../README.fa.md](../../README.fa.md)

## منابع فعلی

| نیاز | سند |
|---|---|
| اجرای، پایش، توقف و resume | [../RUNBOOK.md](../RUNBOOK.md) |
| معماری و جریان داده | [../../ARCHITECTURE.md](../../ARCHITECTURE.md) |
| قرارداد خروجی v6 | [../SCHEMA_V6.md](../SCHEMA_V6.md) |
| آمار و محدودیت ادعا | [../STATISTICS.md](../STATISTICS.md) |
| وضعیت صادقانهٔ شواهد | [../EVIDENCE_STATUS.md](../EVIDENCE_STATUS.md) |
| راهنمای سریع فارسی | [QUICKSTART.md](QUICKSTART.md) |
| واژه‌نامه | [GLOSSARY.md](GLOSSARY.md) |
| درسنامه فارسی | [darsname/README.md](darsname/README.md) |

مسیر live معتبر:

```text
pipeline_live_ensemble.py → SQLite منبع حقیقت → JSON schema v6r1
→ analyze_live_results.py --schema-version 6
```

## وضعیت اسناد قدیمی

فایل‌های v6 پیش از revision `v6r1` و همچنین درس‌های تاریخ‌دار، schema v3/v5،
artifactها، گزارش audit و verification برای حفظ
سابقه نگه‌داری می‌شوند. آن‌ها دستور عملیاتی فعلی یا شاهد v6 نیستند.

مطالعه‌های عمومی کوانتوم، PHCA و شناخت کوانتومی نیز پس‌زمینه‌اند؛ برای اجرای
Exchange-Q یا اثبات عملکرد مدل به آن‌ها استناد نکنید.
