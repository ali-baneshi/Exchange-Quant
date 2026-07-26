# درس ۴ — قانون Born به زبان ساده (+ محدودیت‌های واقعی)

## مشخصات نسخه

| فیلد | مقدار |
|------|--------|
| تاریخ درس | 2026-07-26 |
| snapshot | [SYSTEM_SNAPSHOT-2026-07-26.md](../SYSTEM_SNAPSHOT-2026-07-26.md) |
| model_version | `born_v3_constructive_gate` |
| کد | `core/quantum_core.py`, `core/delta_adaptive.py` |
| پیش‌نیاز | [L03](./03-dade-zande-buy-ratio.md) |

---

## سوالات این درس

1. Born rule اینجا ورودی می‌گیرد و چه خروجی می‌دهد؟
2. bucketing high/low چطور کار می‌کند؟
3. δ (delta) از کجا می‌آید و چرا فقط [0, π/2]؟
4. fallback_reason یعنی چه — چند درصد Born «واقعاً» فعال است؟
5. چرا destructive interference به classical برمی‌گردد؟

---

## تدریس — الگوریتم در پنج قدم

**ورودی:** 15 observation اخیر (window) با buy_ratio (و imbalance برای δ).

```text
1. تاریخچه را به high (بالای median) و low (پایین/مساوی median) تقسیم کن
2. p_high = تعداد high / N کل    — باید p_high + p_low = 1
3. μ_high = میانگین buy_ratio در high؛ μ_low در low
4. δ = compute_delta(history)     — از imbalance و volatility
5. P = |√(p_h·μ_h) + √(p_l·μ_l)·e^(iδ)|²  → clamp به [0,1]
```

**خروجی:** `prediction` (عدد بین 0 و 1).

---

## δ زنده

| δ | تفسیر تقریبی (live) |
|---|---------------------|
| 0 | تداخل «سازنده» بیشتر |
| π/2 | خنثی‌تر |
| > π/2 | **در live map نمی‌شود** — gate سازنده |

**نگاه انتقادی:** فرضیه «تداخل منفی» روی live **به‌طور کامل تست نمی‌شود** — نسخه frozen: `born_v3_constructive_gate`.

---

## fallback_reason — صادقانه بخوانید

| مقدار | یعنی |
|-------|------|
| `none` | Born کامل — **born_active** |
| `insufficient_history` | window پر نشده |
| `flat_history` | همه buy_ratio تقریباً یکی |
| `single_bucket` | فقط یک طرف median |
| `destructive_interference` | ترم تداخل منفی → برگشت به classical_part |

**born_active_rate** پایین ≠ «مدل بد» — ممکن است بازار flat باشد.

---

## مقایسه با baseline

همان window → `classical_ensemble` → `classical`  
Born → `prediction` (یا quantum در ensemble mode)

در resolve:  
`classical_error = |classical − actual|`  
`prediction_error = |prediction − actual|`

---

## کار عملی

```bash
cd core && python3 quantum_core.py   # اگر demo دارد
# یا در log live خط fallback= را بشمارید
grep -o 'fallback=[^ ]*' ../live_quantum_v3.log | sort | uniq -c
```

---

## پاسخ سوالات

**۱. I/O?**  
In: window history. Out: prediction [0,1] + meta (δ, fallback, buckets).

**۲. bucketing?**  
median split؛ همه observation در یک bucket؛ جمع احتمال = 1.

**۳. δ?**  
order-book imbalance + vol؛ mapped [0,π/2] در live.

**۴. fallback?**  
هر چیز غیر `none` = Born کامل نبود؛ نرخ را از analyzer بگیرید.

**۵. destructive?**  
طراحی v3: منفی → classical_part — عمدی برای gate سازنده.

---

**بعد:** [L05](./05-pipeline-zende.md)
