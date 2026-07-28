# راهنمای سریع عملیاتی

**English:** [../../WORKFLOW.md](../../WORKFLOW.md) | **قرارداد:** [../SCHEMA_V6.md](../SCHEMA_V6.md)

## آماده‌سازی

```bash
pip install -r requirements-dev.txt
make test
make compile
```

## Production

در ترمینال اول:

```bash
./scripts/start_production_run.sh
```

در ترمینال دوم:

```bash
./scripts/monitor_live.sh
tail -f live_quantum_v3.log
```

فرآیند start در foreground است. `Ctrl-C` در ترمینال اول خروج تمیز انجام می‌دهد.
برای توقف اضطراری یا وقتی ترمینال اول در دسترس نیست:

```bash
./scripts/stop_all_runs.sh
```

تنظیم production: `horizon=3600s`، interval=`60s`، window=`15` و هدف
`720` resolve واجد شرایط است. نام log قدیمی است اما قرارداد خروجی فعلی v6r1 است.

## Exploratory

```bash
./scripts/start_exploratory_run.sh
```

از ترمینال دیگر:

```bash
./scripts/monitor_exploratory.sh
tail -f live_exploratory.log
```

این run با horizon 60 ثانیه فقط برای بررسی زیرساخت، cadence و کیفیت label است؛
جای production و شواهد اصلی را نمی‌گیرد.

## وقتی «گیر کرده» به نظر می‌رسد

بعد از warmup فقط یک forecast pending مجاز است. بنابراین پیام زیر تا رسیدن target
طبیعی است:

```text
SKIP forecast — pending unresolved
```

monitor مبتنی بر SQLite را بررسی کنید: target pending، تعداد labelهای eligible،
دلیل exclusion و خطاهای capture. JSON فقط export قابل مشاهده است و ممکن است
لحظه‌ای عقب‌تر باشد.

## تحلیل و ادعا

```bash
python3 core/analyze_live_results.py --schema-version 6 --exclude-collector
```

برای مشاهدهٔ فایل v6 پیش از hardening باید صریحاً
`--allow-pre-hardening-v6` را اضافه کنید. این فایل‌ها وارد aggregate فعلی نمی‌شوند.

فقط رکوردهای `forward_window` با capture کامل و `score_eligible == true` برای
امتیاز اصلی معتبرند. MAE معیار اصلی است. win rate، `net_return` و شبیه‌سازی قیمت
diagnostic هستند و اثبات سودآوری نیستند.
