# واژه‌نامه Exchange-Q

**English schema reference:** [../SCHEMA_V3.md](../SCHEMA_V3.md)

---

## buy_ratio

نسبت معاملات خرید در پنجره اخیر:

```
buy_ratio = تعداد خرید / (خرید + فروش)
```

هدف اصلی pipeline زنده — مقدار پیوسته در [0, 1]. با **جهت باینری** بک‌تست کندل قابل مقایسه **نیست**.

---

## imbalance

عدم تعادل عمق order-book (bid vs ask). برای محاسبه δ زنده و bucketing Born استفاده می‌شود.

---

## δ (delta)

فاز تداخل در قانون Born:

```
P = |√(p_high·μ_high) + √(p_low·μ_low)·e^(iδ)|²
```

| منبع | بازه | معنی |
|------|------|------|
| order-book زنده | **[0, π/2]** | 0 = سازنده، π/2 = خنثی |
| کندل (قدیمی) | حذف از eval | دیگر برای Born استفاده نمی‌شود |

محاسبه: `delta_adaptive.compute_delta()`.

---

## Born rule / born_active

- **Born active:** `fallback_reason == "none"` — bucketing موفق و تداخل اعمال شد.
- **born_active_rate:** سهم پیش‌بینی‌های eligible با Born فعال.

---

## fallback_reason

| مقدار | معنی |
|-------|------|
| `none` | Born فعال |
| `insufficient_history` | تاریخچه کم — fallback به میانگین |
| `flat_history` | واریانس کم — fallback |
| `single_bucket` | split median یک طرف خالی |
| `destructive_interference` | تداخل منفی — برگشت به `classical_part` |

---

## resolve-later

پیش‌بینی در زمان t ساخته می‌شود؛ در t + horizon_s با **buy_ratio واقعی آینده** امتیازدهی می‌شود. فقط یک pending در هر لحظه.

---

## schema v3

فرمت JSON خروجی `pipeline_live_ensemble.py`:

- `run_id`, `schema_version: 3`
- `observations[]` — fetchهای Huobi
- `predictions[]` — pending / resolved
- `score_eligible` — false اگر quality_flags در entry/exit

---

## quality_flags

| پرچم | اثر |
|------|-----|
| `no_trades` | بدون معامله اخیر |
| `stale_trades` | timestampهای معامله خوشه‌ای |
| `empty_depth` | order-book خالی |
| `duplicate_timestamp` | تکراری — از history forecast حذف |

---

## Bonferroni / win rate

- **Win:** خطای کوانتوم < خطای کلاسیک در همان گام
- **Bonferroni:** `raw_p × 5` (n=5 قرارداد تاریخی — لیست pre-register در repo نیست)
- جزئیات: [../STATISTICS.md](../STATISTICS.md)

---

## corpus policy

| مسیر | سیاست |
|------|--------|
| `core/_live_results/*.json` (v3) | فعال — ادعاهای جدید |
| `_archive/pre_v3/` | legacy — در aggregate مخلوط نکن |
| `collected_*.json` | collector خام — `--exclude-collector` |
