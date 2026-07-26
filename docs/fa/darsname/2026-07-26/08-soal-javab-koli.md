# درس ۸ — بانک سوال و جواب (جامع)

## مشخصات نسخه

| فیلد | مقدار |
|------|--------|
| تاریخ درس | 2026-07-26 |
| snapshot | [SYSTEM_SNAPSHOT-2026-07-26.md](../SYSTEM_SNAPSHOT-2026-07-26.md) |
| پیش‌نیاز | L01–L07 (مرجع سریع) |

---

## بخش ۱ — مفاهیم پایه

**س: buy_ratio با «قیمت بالا می‌رود» چه فرقی دارد؟**  
**ج:** buy_ratio فشار خری/فروش در trades اخیر است (0–1). قیمت می‌تواند بالا برود در حالی که buy_ratio پایین است (فروش aggressive).

**س: resolve-later چرا مهم است؟**  
**ج:** اگر forecast را با همان fetch بسنجید، از آینده در همان لحظه «نشت» information می‌شود — امتیاز بی‌اعتبار.

**س: window=15 یعنی چه؟**  
**ج:** 15 observation آخر برای ساخت یک forecast.

---

## بخش ۲ — Exchange-Q و scope

**س: آیا این bot معامله‌گر است؟**  
**ج:** خیر. فقط research و evaluation؛ سفارش authenticated به صرافی نمی‌فرستد.

**س: چرا Born روی klines حذف شد؟**  
**ج:** target متفاوت + نتایج null روی داده تاریخی؛ مسیر live buy_ratio جایگزین شد.

**س: «کوانتوم» یعنی IBM Quantum؟**  
**ج:** نه. فرمول Born روی CPU.

---

## بخش ۳ — اجرا و run

**س: production چند وقت طول می‌کشد؟**  
**ج:** تا 720 resolve با horizon 1h ≈ 30 روز wall time (اگر quality OK).

**س: SKIP forecast خطا است؟**  
**ج:** نه. یعنی pending هنوز resolve نشده.

**س: دو run همزمان؟**  
**ج:** بله — `start_production_run.sh` + `start_exploratory_run.sh` در ترمینال‌های جدا.

**س: run v3 با 720 step معتبر است؟**  
**ج:** **خیر** برای claim 720 ساعته — fetch bug.

**س: resume چطور؟**  
**ج:** `--resume RUN_ID` با همان horizon/sample/window.

---

## بخش ۴ — Born و fallback

**س: born_active_rate پایین بد است؟**  
**ج:** لزوماً نه — ممکن است بازار flat باشد (`flat_history`).

**س: destructive_interference یعنی Born شکست خورد؟**  
**ج:** یعنی ترم تداخل منفی بود و به classical_part برگشت — design v3.

**س: δ چرا محدود [0,π/2]؟**  
**ج:** نسخه frozen `born_v3_constructive_gate` — تست symmetric کامل در این run نیست.

---

## بخش ۵ — آمار و claim

**س: 20 resolve در exploratory کافی است؟**  
**ج:** برای diagnostics بله؛ برای claim primary **خیر** (نیاز 720 در production config).

**س: win rate 55% = سود 55%؟**  
**ج:** **خیر.** فقط اکثریت گام‌های با خطای کمتر — نه PnL.

**س: چه زمانی «ثابت شد»؟**  
**ج:** n≥720 eligible + paired test + quality policy + production config — نه exploratory 60s.

**س: Bonferroni 5 hypothesis هنوز اعمال می‌شود؟**  
**ج:** live از `N_HYPOTHESES_LIVE=1` استفاده می‌کند؛ 5 برای legacy kline-era.

---

## بخش ۶ — عیب‌یابی

**س: monitor فایل v3 نشان می‌دهد؟**  
**ج:** race یا log قدیمی — `monitor_exploratory.sh` یا analyze با path صریح v4.

**س: NO DATA loops?**  
**ج:** Huobi down یا rate limit — sample را افزایش دهید.

**س: resolved eligible = 0 بعد از ساعت‌ها?**  
**ج:** در production طبیعی تا اولین horizon (1h) بگذرد؛ log RESOLVED را ببینید.

**س: analyze «need at least 3»?**  
**ج:** هنوز resolve eligible ندارید — صبر یا run exploratory سریع‌تر.

---

## بخش ۷ — نسخه و درسنامه

**س: چطور بفهمم درس قدیمی است؟**  
**ج:** تاریخ درس + SYSTEM_SNAPSHOT را با commit و RUNBOOK فعلی مقایسه کنید.

**س: درس جدید کی اضافه می‌شود؟**  
**ج:** وقتی schema، CLI، یا claim policy عوض شود — پوشه `YYYY-MM-DD` جدید.

---

## تمرین نهایی — خودارزیابی

بدون نگاه به متن، پاسخ دهید:

1. هدف primary metric چیست؟
2. تفاوت production و exploratory در horizon؟
3. حداقل n برای significance claim؟
4. چرا ensemble از stored prediction update می‌شود؟
5. سه quality flag که score را zero می‌کنند؟

<details>
<summary>پاسخ تمرین (کلیک)</summary>

1. paired absolute error روی buy_ratio  
2. 3600s vs 60s  
3. 720 eligible (production)  
4. جلوگیری از leakage اطلاعات آینده  
5. no_trades, crossed_market, endpoint_skew (+ late_resolution در exit)

</details>

---

**فهرست:** [../README.md](../README.md) | **snapshot:** [SYSTEM_SNAPSHOT-2026-07-26.md](../SYSTEM_SNAPSHOT-2026-07-26.md)
