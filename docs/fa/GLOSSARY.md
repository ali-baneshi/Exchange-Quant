# واژه‌نامه Exchange-Q

**English schema reference:** [../SCHEMA_V5.md](../SCHEMA_V5.md)

---

## buy_ratio

نسبت معاملات خرید:

```
buy_ratio = تعداد خرید / (خرید + فروش)
```

هدف اصلی pipeline زنده — مقدار پیوسته در [0, 1]. با **جهت باینری** بک‌تست کندل قابل مقایسه **نیست**.

**Feature (v5 policy 3):** فقط trades در `max(60, horizon_s)` ثانیه اخیر — نه کل صفحه API (~80 دقیقه).

**Label (primary):** buy_ratio در پنجره `[created_at_ms, target_at_ms]` از trades capture‌شده محلی.

---

## feature_lookback_s / data_policy_version

| مورد | معنی |
|------|------|
| `DATA_POLICY_VERSION` | 3 — lookback feature هم‌مقیاس با horizon |
| `feature_lookback_s(60)` | 60 ثانیه |
| `feature_lookback_s(3600)` | 3600 ثانیه (1 ساعت) |

---

## forward_window / label_capture

| مورد | معنی |
|------|------|
| `resolved_label: forward_window` | label primary از trades capture‌شده |
| `label_capture_complete` | capture برای پنجره forward کامل |
| `capture_saturated` | صفحه API پر — **≠** همیشه hole (v5: فقط اگر frontier واقعاً hole) |
| `min_forward_trades(3600)` | 15 trade حداقل در پنجره 1 ساعته |

---

## imbalance

عدم تعادل عمق order-book (bid vs ask). برای محاسبه δ زنده و bucketing Born استفاده می‌شود.

---

## δ (delta)

فاز تداخل در قانون Born. δ زنده در **[0, π/2]** — منبع: order-book.

---

## Born rule / born_active / saturation_gate

- **Born active:** `fallback_reason == "none"`
- **saturation_gate:** overshoot یا pred≥0.99 → برگشت به `classical_part` (safeguard)
- **born_active_rate:** سهم eligible با Born فعال
- **model_version (فعلی):** `born_constructive_v2`

---

## fallback_reason

| مقدار | معنی |
|-------|------|
| `none` | Born فعال |
| `insufficient_history` | تاریخچه کم |
| `flat_history` | واریانس کم |
| `single_bucket` | split median یک طرف خالی |
| `destructive_interference` | تداخل منفی — `classical_part` |
| `saturation_gate` | overshoot سازنده — `classical_part` |

---

## null baseline

`MAE(constant 0.5)` — اگر هر دو مدل بدتر از این باشند، سیگنال ضعیف است (نه لزوماً باگ infra). exploratory 60s اغلب بدتر از null — طبیعی.

---

## resolve-later

پیش‌بینی در t؛ resolve در `target_at_ms` با label forward-window. فقط یک pending در هر لحظه.

---

## schema v6r1

فرمت JSON خروجی `pipeline_live_ensemble.py`:

- `schema_version: 6` همراه `implementation_revision: v6r1`،
  `acquisition_policy_version: 1`، `run_id`، `config_hash` و `experiment_manifest`
- `data_policy_version`, `label_policy`
- `observations[]`, `predictions[]` با `resolved_label`, `label_capture`, `forward_window_*`
- `score_eligible` — false برای quality flags یا label ناقص

مرجع: [../SCHEMA_V6.md](../SCHEMA_V6.md). schema v5 تاریخی است و با corpus v6
نباید مخلوط شود.

---

## quality_flags (disqualifying)

| پرچم | اثر |
|------|-----|
| `crossed_market` | bid/ask معکوس |
| `no_trades` | بدون معامله |
| `endpoint_skew` | skew ticker/depth |
| `late_resolution` | resolve دیر |
| `short_forward_window` | کمتر از min trades در forward |
| `label_unavailable` | capture ناقص |
| `duplicate_timestamp` | از history forecast حذف |

---

## corpus policy

| مسیر | سیاست |
|------|--------|
| `core/_live_results/*.json` (v6r1) | فعال — ادعاهای جدید |
| `_archive/pre_v6r1/` | legacy و pre-hardening — در aggregate مخلوط نکن |
| `collected_*.json` | collector خام — `--exclude-collector` |

---

## Bonferroni / win rate

- **Win:** `prediction_error < classical_error` در همان forecast
- **Primary:** n≥720 eligible + paired block bootstrap
- جزئیات: [../STATISTICS.md](../STATISTICS.md)
