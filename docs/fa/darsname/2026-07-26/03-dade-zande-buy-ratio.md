# درس ۳ — داده زنده: از Huobi تا observation

## مشخصات نسخه

| فیلد | مقدار |
|------|--------|
| تاریخ درس | 2026-07-26 |
| snapshot | [SYSTEM_SNAPSHOT-2026-07-26.md](../SYSTEM_SNAPSHOT-2026-07-26.md) |
| پیش‌نیاز | [L01](./01-pishzamineh.md), [L02](./02-exchange-q-chist.md) |
| کد مرجع | `core/data_fetcher.py` |

---

## سوالات این درس

1. هر 60 ثانیه (یا 5 ثانیه) دقیقاً چه چیزی fetch می‌شود؟
2. buy_ratio چطور محاسبه می‌شود و چرا «ثبت trade window» مهم است؟
3. quality_flags یعنی چه — کدام‌ها forecast را بی‌اعتبار می‌کنند؟
4. endpoint_skew چیست؟
5. چرا duplicate_timestamp از history forecast حذف می‌شود؟

---

## تدریس — یک fetch چه می‌کند؟

`HuobiData.fetch_features(symbol)` همزمان می‌گیرد:

| منبع | خروجی |
|------|--------|
| ticker | قیمت، high/low |
| depth | bids/asks |
| trades | لیست معاملات اخیر |
| klines 1min | برای volume_change |

سپس `compute_live_features()` یک **observation** می‌سازد.

---

## فیلدهای مهم observation

```text
price, buy_ratio, buy_ratio_volume
imbalance, spread, volatility, volume_change
trade_window_start_ms, trade_window_end_ms
ticker_timestamp_ms, depth_timestamp_ms
quality_flags[]
```

**buy_ratio** از trades:

```text
buy_ratio = (# buys) / (total trades)   # اگر خالی → 0.5 پیش‌فرض
```

---

## quality_flags (snapshot 2026-07-26)

| پرچم | معنی | اثر روی score |
|------|------|----------------|
| `no_trades` | بدون trade | **ineligible** |
| `stale_trades` | timestamp تکراری زیاد | warning |
| `empty_depth` | order-book خالی | warning |
| `crossed_market` | ask < bid | **ineligible** |
| `endpoint_skew` | ticker vs depth > 5s | **ineligible** |
| `duplicate_timestamp` | تکرار exchange ts | از history حذف |

لیست disqualify در `config.DISQUALIFYING_QUALITY_FLAGS`.

---

## نگاه انتقادی — provenance

**سوال سخت:** buy_ratio واقعاً «یک ساعت آینده بازار» را نشان می‌دهد؟

**پاسخ صادق:** نه لزوماً. snapshot trades **اخیر** است؛ horizon 3600s یعنی actual در **اولین observation مناسب بعد از target_at** resolve می‌شود. اگر API کند باشد → `late_resolution` → ineligible.

این **feature** است نه bug — سیستم کیفیت پایین را از امتیاز حذف می‌کند.

---

## کار عملی

```bash
# اگر run فعال دارید — آخرین JSON v4:
python3 -c "
import json, glob
p=sorted(glob.glob('core/_live_results/btcusdt-quantum-*.json'))[-1]
d=json.load(open(p))
o=d['observations'][-1]
print('buy_ratio', o.get('buy_ratio'))
print('flags', o.get('quality_flags'))
print('trade span ms', o.get('trade_window_span_ms'))
"
```

---

## پاسخ سوالات

**۱. fetch?**  
ticker + depth + trades + klines → observation با feature و flags.

**۲. buy_ratio?**  
نسبت خرید در trades اخیر؛ window در trade_window_* ثبت می‌شود.

**۳. flags?**  
no_trades, crossed_market, endpoint_skew, late_resolution → score_eligible=false.

**۴. skew?**  
|ticker_ts − depth_ts| > 5000ms.

**۵. duplicate?**  
همان exchange timestamp دوباره → تکرار در history مدل گمراه می‌کند.

---

**بعد:** [L04](./04-born-rule-sade.md)
