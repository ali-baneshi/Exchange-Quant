# فهرست مستندات Exchange-Q

**English:** [../README.md](../README.md) | **خلاصه فارسی:** [../../README.fa.md](../../README.fa.md)

---

## از کجا شروع کنم؟

| هدف | سند |
|-----|-----|
| **درسنامه (آموزش فارسی، Q&A)** | **[darsname/README.md](./darsname/README.md)** ← شروع یادگیری |
| اجرای اولیه پروژه | [QUICKSTART.md](./QUICKSTART.md) |
| درک اصطلاحات | [GLOSSARY.md](./GLOSSARY.md) |
| pipeline زنده (جزئیات) | [../RUNBOOK.md](../RUNBOOK.md) |
| معماری سیستم | [../../ARCHITECTURE.md](../../ARCHITECTURE.md) |
| JSON خروجی و fallback | [../SCHEMA_V3.md](../SCHEMA_V3.md) |
| آمار و p-value | [../STATISTICS.md](../STATISTICS.md) |
| حکم تجربی | [../../verification_report.md](../../verification_report.md) |

---

## مستندات عملیاتی (فارسی)

| سند | توضیح |
|-----|--------|
| [../../README.fa.md](../../README.fa.md) | خلاصه اجرایی + دستورات |
| [QUICKSTART.md](./QUICKSTART.md) | گام‌های WORKFLOW به فارسی |
| [GLOSSARY.md](./GLOSSARY.md) | Born rule، δ، schema v3 |

---

## تحقیقات (فارسی — تئوری)

| سند | موضوع |
|-----|--------|
| [../../core/research_INDEX.md](../../core/research_INDEX.md) | نگاشت تحقیق → کد |
| research_01 | سه‌گانه قصد (Intent Trilemma) |
| research_02 | مکانیزم‌های الهام‌گرفته از کوانتوم |
| research_03 | پارادوکس‌های تصمیم‌گیری |
| research_04 | ICDS (چشم‌انداز — با پیاده‌سازی فرق دارد) |
| research_05 | آرشیو نتایج |

---

## فقط مطالعه پس‌زمینه (برای ops استفاده نکنید)

- `quantum_inspired_programming.md` — برنامه‌نویسی الهام‌گرفته از کوانتوم (عمومی)
- `ai_research_study_guide_fa.md` — PHCA / FEP (پروژه دیگر)
- `code_audit_v1/` — ممیزی تاریخی ۲۰۲۶-۰۷-۲۰

---

## اسکریپت‌ها

| اسکریپت | کاربرد |
|---------|--------|
| `scripts/start_production_run.sh` | شروع اجرای تولید v3 |
| `scripts/monitor_live.sh` | پایش log و JSON |
| `scripts/archive_legacy_results.sh` | آرشیو JSON قدیمی |
