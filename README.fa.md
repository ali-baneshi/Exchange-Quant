# Exchange-Q — خلاصه فارسی

**English:** [README.md](README.md) | **فهرست فارسی:** [docs/fa/README.md](docs/fa/README.md)

Exchange-Q یک ارزیاب پژوهشی پایدار برای یک فرضیه پیش‌بینی الهام‌گرفته از کوانتوم
است. این پروژه ربات معامله‌گر نیست: کلید صرافی، اجرای سفارش، مدیریت پورتفو یا ادعای
سودآوری ندارد.

## وضعیت فعلی — ۲۸ ژوئیهٔ ۲۰۲۶

- قرارداد فعال: schema **v6r1**، مدل `born_constructive_v2`، data policy **v4**،
  implementation revision برابر `v6r1` و acquisition policy برابر ۱ است.
- خروجی ارزیابی‌شده یک سیاست ترکیبیِ دارای gate است؛ مقدار خام Born همیشه همان
  مقدار امتیازدهی‌شده نیست و `fallback_reason` باید در گزارش دیده شود.
- هنوز corpus معتبر v6 وجود ندارد که برتری نسبت به baseline کلاسیک یا سودآوری
  معاملاتی را ثابت کند.

پیش از نقل نتیجه، [وضعیت شواهد](docs/EVIDENCE_STATUS.md) را بخوانید.

## اجرای زنده

در ترمینال اول:

```bash
./scripts/start_production_run.sh
```

این فرمان عمداً در foreground می‌ماند. در ترمینال دیگر:

```bash
./scripts/monitor_live.sh
tail -f live_quantum_v3.log
```

برای خروج تمیز، در همان ترمینال اول `Ctrl-C` بزنید. اگر آن ترمینال در دسترس نیست:

```bash
./scripts/stop_all_runs.sh
```

نام log قدیمی است؛ خروجی فعلی schema v6 است. تحلیل:

```bash
python3 core/analyze_live_results.py --schema-version 6 --exclude-collector
```

فایل‌های v6 پیش از hardening فقط تاریخی‌اند و تنها با
`--allow-pre-hardening-v6` قابل بررسی هستند؛ با corpus فعلی مخلوط نمی‌شوند.

## مسیرها را مخلوط نکنید

| مسیر | هدف | وضعیت |
|---|---|---|
| kline تاریخی | جهت باینری کندل | بررسی کلاسیک؛ شواهد Born نیست |
| order-book زنده | `buy_ratio` آینده | مسیر اصلی v6 |
| دادهٔ مصنوعی | هدف شبیه‌ساز | فقط تشخیصی |

برای امتیاز اصلی باید `resolved_label == "forward_window"`،
`label_capture_complete == true` و `score_eligible == true` برقرار باشد. نرخ برد
و return شبیه‌سازی‌شده فقط diagnostics هستند، نه دلیل سودآوری.
