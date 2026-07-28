# درس ۳ — داده زنده: از Huobi تا label

> **درس تاریخی (schema v5/model v1).** برای فرمان، نسخه و محدودیت ادعای فعلی از
> snapshot ۲۸ ژوئیه و مراجع v6 استفاده کنید.

## مشخصات نسخه

| فیلد | مقدار |
|------|--------|
| تاریخ درس | 2026-07-27 |
| snapshot | [SYSTEM_SNAPSHOT-2026-07-27.md](../SYSTEM_SNAPSHOT-2026-07-27.md) |
| schema | v5 |
| پیش‌نیاز | L01, L02 |
| کد | `core/data_fetcher.py`, `core/live_store.py` |

### تغییرات نسبت به 2026-07-26

- feature buy_ratio فقط از `feature_lookback_s = max(60, horizon_s)` ثانیه اخیر
- label primary از trades **capture‌شده** در `[created_at_ms, target_at_ms]`
- `capture_saturated` ≠ همیشه label رد

---

## سوالات این درس

1. fetch چه می‌کند و feature با label چه فرقی دارد؟
2. `feature_lookback_s` چرا مهم است؟
3. resolve چطور actual را می‌سازد؟
4. کدام quality_flags score را zero می‌کنند؟

---

## fetch و feature (data_policy v3)

`fetch_features_with_trades()` می‌گیرد: ticker, depth, trades, klines.

**Feature buy_ratio:** فقط trades در `max(60, horizon_s)` ثانیه اخیر — نه کل صفحه API (~80 دقیقه).

| horizon | lookback feature |
|---------|------------------|
| 60s | 60s |
| 3600s | 3600s (1h) |

---

## label primary (forward_window)

در resolve، `live_store.trade_window()` trades capture‌شده بین `created_at_ms` و `target_at_ms` را فیلتر می‌کند:

```text
actual = buy_count / (buy_count + sell_count)
resolved_label = "forward_window"
```

شرط eligibility:

- `label_capture_complete == true`
- trades ≥ `min_forward_trades(horizon_s)` (3600s → 15 trade)
- بدون disqualifying quality flag

---

## capture_saturated (v5)

Huobi اغلب صفحه 2000 trade پر برمی‌گرداند. **v5:** saturation فقط وقتی coverage را می‌شکند که oldest trade **بعد از** frontier قبلی باشد (hole واقعی) — نه روی هر full page.

---

## quality_flags

| پرچم | اثر |
|------|-----|
| `crossed_market`, `no_trades`, `endpoint_skew` | ineligible |
| `late_resolution`, `short_forward_window`, `label_unavailable` | ineligible |
| `duplicate_timestamp` | از history forecast حذف |

---

## null baseline (نگاه انتقادی)

روی exploratory 60s ref، MAE(0.5)≈0.252 بهتر از هر دو مدل بود — **نویز microstructure**، نه لزوماً باگ. production 3600s معیار primary است.

---

## کار عملی

```bash
python3 core/analyze_live_results.py --schema-version 5 \
  core/_live_results/_archive/exploratory-post-fix/btcusdt-quantum-1785119130.json
```

---

**بعد:** [L04](./04-born-rule-sade.md)
