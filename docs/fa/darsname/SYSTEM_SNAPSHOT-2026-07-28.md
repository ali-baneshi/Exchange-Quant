# تصویر سیستم — ۲۸ ژوئیهٔ ۲۰۲۶

> **snapshot فعلی آموزشی.** مرجع عملیاتی نهایی `RUNBOOK.md`، `SCHEMA_V6.md`،
> `STATISTICS.md` و `EVIDENCE_STATUS.md` هستند.

## چه چیزی پیاده‌سازی شده است؟

| مورد | مقدار فعلی |
|---|---|
| schema زنده | v6r1 (`schema_version=6`، revision=`v6r1`) |
| هویت مدل ارزیابی‌شده | `born_constructive_v2` |
| data policy | v4 |
| acquisition policy | v1 |
| منبع پایدار حقیقت | SQLite برای هر run |
| export | JSON اتمیک schema v6 |
| هدف اصلی | `buy_ratio` آیندهٔ معاملات |
| معیار اصلی | تفاوت MAE جفت‌شده |
| هدف گزارش اصلی | ۷۲۰ forecast resolve و واجد شرایط |

پروژه دادهٔ عمومی بازار را جمع‌آوری می‌کند اما credential، سفارش یا اجرای معامله
ندارد.

## feature، forecast و label

featureِ `buy_ratio` فقط از معاملات گذشته در بازهٔ `max(60, horizon_s)` ساخته
می‌شود. پس از warmup، یک forecast pending ایجاد می‌شود. label بعداً فقط با
معاملات آینده‌ای که محلی capture شده‌اند و timestamp آن‌ها به‌صورت inclusive در
بازهٔ forecast است ساخته می‌شود.

اگر capture کامل نباشد، label اصلی جایگزین نمی‌گیرد: `label_unavailable` می‌شود و
از scoring کنار گذاشته می‌شود.

## gate و امتیازدهی

`prediction` ثبت‌شده خروجی واقعی سیاست gateدار است. مقدار خام Born، بخش کلاسیک،
interference، phase و `fallback_reason` ثبت می‌شوند. fallback بخشی از مسیر واقعی
اجراست و نباید در گزارش پنهان شود.

امتیاز اصلی فقط برای forward-window کامل و بدون quality flag disqualifying معتبر
است. کنترل‌ها شامل timestamp کهنه/آینده/ناموجود، clock و endpoint skew، دادهٔ
malformed، بازار crossed یا depth خالی، resolution دیر و label ناقص است.

## اجرا و ادعا

scriptهای start در foreground اجرا می‌شوند. start را در یک ترمینال و monitor/log
را در ترمینال دیگر اجرا کنید. `Ctrl-C` در ترمینال start cleanup تمیز انجام می‌دهد.
پیام `SKIP forecast — pending unresolved` تا زمان target طبیعی است.

SQLite برای monitor و recovery مرجع است؛ JSON export قابل مشاهده است و ممکن است
کمی عقب باشد. هنوز شواهد v6 برای برتری یا سودآوری وجود ندارد. MAE و آزمون
paired moving-block معیار اصلی‌اند؛ win rate و return فقط diagnostic هستند.
