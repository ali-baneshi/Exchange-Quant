# درس ۸ — بانک سوال و جواب (جامع)

> **درس تاریخی (schema v5/model v1).** برای فرمان، نسخه و محدودیت ادعای فعلی از
> snapshot ۲۸ ژوئیه و مراجع v6 استفاده کنید.

## مشخصات نسخه

| فیلد | مقدار |
|------|--------|
| تاریخ درس | 2026-07-27 |
| snapshot | [SYSTEM_SNAPSHOT-2026-07-27.md](../SYSTEM_SNAPSHOT-2026-07-27.md) |
| schema | v5 |

---

## بخش ۱ — مفاهیم

**س: buy_ratio چیست؟**  
**ج:** نسبت خرید در trades — هدف primary pipeline.

**س: feature vs label?**  
**ج:** feature از lookback اخیر (`max(60, horizon_s)`); label از trades capture‌شده در `[created_at, target_at]`.

**س: null baseline?**  
**ج:** MAE(constant 0.5) — اگر مدل‌ها بدتر باشند، سیگنال ضعیف است.

---

## بخش ۲ — اجرا

**س: production چند وقت؟**  
**ج:** ~720 eligible × 1h ≈ 30 روز.

**س: دو run همزمان؟**  
**ج:** بله — production + exploratory؛ lock فقط روی production script.

**س: run با n_steps قدیمی معتبر؟**  
**ج:** **خیر** — `--max-resolved` eligible resolve می‌شمارد.

**س: stop قبل از start?**  
**ج:** `./scripts/stop_all_runs.sh`

---

## بخش ۳ — Born و gate

**س: saturation_gate bug است؟**  
**ج:** نه — safeguard؛ ~78% روی exploratory ref؛ تا production n≥30 patch ممنوع.

**س: model_version?**  
**ج:** `born_constructive_v1`

---

## بخش ۴ — claim

**س: 50 resolve exploratory کافی؟**  
**ج:** diagnostics/exploratory فقط — primary نیاز n≥720 production.

**س: analyze command?**  
**ج:** `--schema-version 5`

**س: monitor فایل قدیمی؟**  
**ج:** monitor_live/exploratory یا path صریح v5 JSON.

---

## بخش ۵ — quality flags

**ineligible:** `crossed_market`, `no_trades`, `endpoint_skew`, `late_resolution`, `short_forward_window`, `label_unavailable`

---

## تمرین

1. primary metric? → paired MAE on buy_ratio  
2. production vs exploratory horizon? → 3600s vs 60s  
3. min n for primary? → 720 eligible  
4. null baseline role? → sanity check before MAE claims  
5. three ineligible flags? → no_trades, label_unavailable, short_forward_window (مثال)

---

**فهرست:** [../README.md](../README.md)
