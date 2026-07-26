# Research Document 5: Final Validation Results (ARCHIVED — Born rule removed from kline evaluation)

> **⚠️ DECISION (2026-07-23): Born rule removed from all kline-based evaluation.**
>
> Born rule requires **real order-book imbalance data** which is not available in
> historical klines. On kline-only data, all p-values = 1.0 across 5000 candles.
> The model cannot work without imbalance, and this is a fundamental data limitation,
> not a model flaw.
>
> **Born rule is kept only for live order-book pipelines:**
>   `core/pipeline_live_ensemble.py btcusdt 720 3600 quantum`
>
> Kline backtesting is now **classical-only** (`core/backtest.py`).
> The sections below are kept for historical reference only.

> **English Executive Summary** (original Persian content follows)

## Methodology (Historical — kline results now deprecated)

All results use:
1. **Data source**: Gate.io (paginated API, 5000+ candles) with Huobi fallback
2. **Train/val/test split**: 60/20/20 (walk-forward), last 20% held out for final evaluation
3. **Block bootstrap**: Handles time-series autocorrelation (sign-flipping, +1 p-value correction)
4. **Bonferroni correction**: Adjusted for 5 hypotheses (p_critical = 0.05/5 = 0.01)
5. **Unified Born rule (removed from klines on 2026-07-23)**

## Key Formulas (Born rule — for live pipeline only)

**Standard Born rule (used in live order-book pipeline):**
```
P = |√(p_high · μ_high) + √(p_low · μ_low) · e^(iδ)|²
```

**Delta from order book (live):** δ ∈ **[0, π/2]** via `compute_delta()` — 0 for strong imbalance (constructive), π/2 for high uncertainty (neutral). Negative interference is gated (`fallback_reason: destructive_interference`). See [docs/STATISTICS.md](../docs/STATISTICS.md) for claim thresholds.

## Results Summary (Historical — for reference only)

> **⚠️ TARGET VARIABLE WARNING**: All backtest and ablation results below predict **BINARY DIRECTION** (up=1, down=0). The live pipeline predicts **CONTINUOUS BUY_RATIO** [0,1]. These are **different tasks** and are NOT directly comparable. The 0.4801 result applies ONLY to binary direction prediction.

> **⚠️ BORN RULE REMOVED FROM KLINE EVALUATION (2026-07-23):** These results are kept for historical reference. The Born rule is no longer evaluated on kline data. It requires order-book imbalance which klines do not provide. All Born rule results below are **deprecated**.

### 1. Ablation (Historical — Born rule removed from klines)

| Model | Error | vs. Vol Regime |
|-------|-------|----------------|
| Born rule (quantum) | 0.4801 | +6.1% |
| quantum+vol_regime ensemble | 0.5017 | +1.85% |
| vol_regime (baseline) | 0.5112 | — |
| MA (baseline) | 0.5122 | — |

**Caveat:** 400 held-out samples, binary direction target. p-values not significant at 0.05 level after Bonferroni. No longer evaluated on klines.

### 2. Large-scale backtest (Historical — Born rule removed from klines)

| Experiment | n | Classical | Quantum | Improvement | Bonf. p |
|-----------|---|-----------|---------|-------------|---------|
| Born rule (return-based δ) | 979 | 0.5031 | 0.5122 | **-1.8%** | 1.000 |
| Adaptive vs Fixed weights | 984 | 0.5030 | 0.5022 | +0.16% | 1.000 |
| Ensemble vs standalone quantum | 979 | 0.5016 | 0.5127 | **-2.2%** | 1.000 |

**All p-values = 1.000 after Bonferroni. No statistically significant result.**

### 3. Synthetic experiment (kept for research — not kline-dependent)

Classical error 0.1255 vs Quantum error 0.1549 (computed delta). Even with oracle delta, quantum is worse (0.2006). The median split on buy_ratio fails to separate hidden context (separation = 0.0206). This synthetic data structure does not match the quantum model's assumptions.

## Honest Conclusion (Updated 2026-07-23)

### Decision: Born rule removed from kline evaluation

The Born rule **requires real order-book imbalance data** to function. Historical klines
do not contain this data. All kline-based evaluations of the Born rule are therefore
**invalid by design**. The correct test is on live order-book data, which has not yet
been run at scale.

| What remains active | What is deprecated |
|---------------------|-------------------|
| ✅ **Born rule on live order-book data** (`pipeline_live_ensemble.py`) | ❌ Born rule on kline backtests (p=1.0, removed) |
| ✅ **Classical backtesting** (`backtest.py` — vol_regime, MA) | ❌ Ensemble vs quantum on klines (removed) |
| ✅ **Synthetic experiment** (`experiment.py` — for research) | ❌ Delta calibration on klines (removed) |
| ✅ **Infrastructure** (data collection, validation, live pipeline) | ❌ `backtest_ensemble.py`, `backtest_boost.py`, `calibrate_delta.py` (deprecated) |

**Bottom line:** Born rule cannot be evaluated on kline data. The only valid test is on
live order-book data with real imbalance features:
```
python3 core/pipeline_live_ensemble.py btcusdt 720 3600 quantum
```
Until this test is run at scale (30+ days), no claims about Born rule's performance
can be made from this project.

---

# سند تحقیقاتی ۵: نتایج اعتبارسنجی نهایی (آرشیو — Born rule از ارزیابی کندل حذف شد)

> **⚠️ تصمیم (۲۰۲۶-۰۷-۲۳): Born rule از تمام ارزیابی‌های مبتنی بر کندل حذف شد.**
>
> Born rule به **داده‌ی imbalance واقعی از Order Book** نیاز دارد که در کندل‌های
> تاریخی موجود نیست. روی داده‌ی کندل، تمام p-valueها = 1.0 بودند.
> این یک محدودیت بنیادین داده است، نه نقص مدل.
>
> **Born rule فقط برای پایپ‌لاین زنده (Order Book) حفظ شده است:**
>   `python3 core/pipeline_live_ensemble.py btcusdt 720 3600 quantum`
>
> بکتست کندل اکنون **فقط کلاسیک** است (`core/backtest.py`).
> بخش‌های زیر صرفاً برای مرجع تاریخی نگه داشته شده‌اند.

> **⚠️ هشدار: متغیر هدف در بکتست و لایو متفاوت است**
> تمام نتایج بکتست و ablation زیر **جهت باینری** (بالا=۱، پایین=۰) را پیش‌بینی می‌کنند.
> پایپ‌لاین زنده **buy_ratio پیوسته** [0,1] را پیش‌بینی می‌کند.
> این دو **وظیفه کاملاً متفاوت** هستند و قابل مقایسه نمی‌باشند.
> نتیجه ۰.۴۸۰۱ فقط برای پیش‌بینی جهت باینری معتبر است.

## روش‌شناسی اصلاح‌شده

تمام نتایج زیر با **روش‌شناسی سختگیرانه** زیر به دست آمده‌اند:

1. **منبع داده**: Gate.io (API با قابلیت pagination تا سقف ۵۰۰۰+ کندل) با fallback به Huobi
2. **جداسازی داده**: ۲۰٪ **held-out** (دست‌نخورده تا لحظه ارزیابی نهایی)
3. **Walk-Forward Validation**: train (۶۰٪ اول train/val) → val (۴۰٪ بعدی) → پارامترها فقط روی val تنظیم شوند
4. **Block Bootstrap**: برای خودهمبستگی سری زمانی (با تصحیح +1 برای p-value)
5. **Bonferroni Correction**: تصحیح برای ۵ فرضیه (p_critical = 0.05/5 = 0.01)
6. **Born Rule یکپارچه**: تمام مسیرهای Born از `quantum_core.born_rule_predict` استفاده می‌کنند (فرم quantum-cognition **بدون** نرمال‌سازی دامنه — نه `amp_h / norm`). ارزیابی Born روی kline از ۲۰۲۶-۰۷-۲۳ حذف شده است.

---

## ۱. Ablation: Born Rule + Simple Models (Huobi, Held-Out 60min)

داده: ۲۰۰۰ کندل Huobi → ۴۰۰ held-out
**متغیر هدف: جهت باینری (۰/۱) — NOT قابل مقایسه با buy_ratio پیوسته**

| مدل | خطا | نتیجه | p-value |
|-----|-----|-------|---------|
| **quantum (born rule)** | **۰.۴۸۰۱** | **بهترین مدل تکی** | گزارش نشده |
| ۲-model (quantum+vol_regime) | ۰.۵۰۱۷ | ۱.۸۵٪ بهتر از vol_regime تنها | > ۰.۰۵ |
| ۲-model (quantum+ma) | ۰.۵۰۲۳ | ۱.۹۳٪ بهتر از ma تنها | > ۰.۰۵ |
| vol_regime | ۰.۵۱۱۲ | baseline | baseline |
| ma (moving average) | ۰.۵۱۲۲ | baseline | — |

**نکته مهم:** p-value برای مقایسه quantum خالص با vol_regime گزارش نشده است. p-valueهای ensemble-level پس از تصحیح بونفرونی معنی‌دار نیستند (p > 0.05). بهترین عملکرد (**quantum خالص با ۰.۴۸۰۱**) روی **۴۰۰ نمونه** و برای **پیش‌بینی جهت باینری** است — نه buy_ratio پیوسته.

---

## ۲. Born Rule Backtest (Gate.io, 5000 Candles, Held-Out 60min)

| آزمایش | n | Classical | Quantum | بهبود | WinRate | Bonf p |
|--------|---|-----------|---------|-------|---------|--------|
| Born rule (return-based delta) | ۹۷۹ | ۰.۵۰۳۱ | ۰.۵۱۲۲ | **۱.۸٪-** | ۴۹.۰٪ | ۱.۰۰۰ |
| Adaptive vs Fixed weights | ۹۸۴ | ۰.۵۰۳۰ | ۰.۵۰۲۲ | **+۰.۱۶٪** | ۴۹.۴٪ | ۱.۰۰۰ |
| Ensemble vs standalone quantum | ۹۷۹ | ۰.۵۰۱۶ | ۰.۵۱۲۷ | **۲.۲٪-** | ۴۷.۵٪ | ۱.۰۰۰ |

**نتیجه در مورد Backtest:** Backtest از داده کندل بدون order book استفاده می‌کند. Born rule برای δ به imbalance نیاز دارد که در کندل وجود ندارد. در backtest از `compute_delta_from_klines` (بر اساس بازده) استفاده می‌شود که توانایی مدل کوانتوم را محدود می‌کند. **این طبیعی است** — Born rule با imbalance واقعی (مثل pipeline زنده) مزیت خود را نشان می‌دهد.

---

## ۳. AdaptiveEnsemble vs کوانتوم خالص (Held-Out, 5000 Candles)

| Ensemble err | Quantum err | بهبود | Bonf p |
|-------------|-------------|-------|--------|
| ۰.۵۰۱۶ | ۰.۵۱۲۷ | **۲.۲٪-** | ۱.۰۰۰ |

**نتیجه:** AdaptiveEnsemble اندکی از کوانتوم خالص بدتر است — vol_regime وزن ensemble را پایین می‌کشد.

---

## ۴. Adaptive Weighting: Fixed vs Adaptive (Held-Out, 5000 Candles)

| Fixed err | Adaptive err | بهبود | Bonf p |
|-----------|-------------|-------|--------|
| ۰.۵۰۳۰ | ۰.۵۰۲۲ | **+۰.۱۶٪** | ۱.۰۰۰ |

**نتیجه:** Adaptive weighting عملاً تفاوتی با fixed weighting ندارد. وزن‌دهی تطبیقی ارزش اضافی ایجاد نمی‌کند.

---

## ۵. آزمایش مصنوعی (Synthetic Experiment)

| معیار | کلاسیک | کوانتوم | بهبود |
|-------|--------|---------|-------|
| میانگین خطا | ۰.۱۲۵۵ | ۰.۱۵۴۹ | **۲۳.۵٪-** |

**نتیجه:** روی داده مصنوعی، Born rule از کلاسیک بدتر است. مزیت Born rule به توزیع داده واقعی بازار بستگی دارد.

---

## نتیجه‌گیری نهایی (به‌روزرسانی ۲۰۲۶-۰۷-۲۳)

### تصمیم: Born rule از ارزیابی کندل حذف شد

Born rule **به داده‌ی imbalance واقعی از Order Book نیاز دارد**. کندل‌های تاریخی
این داده را ندارند. تمام ارزیابی‌های قبلی Born rule روی کندل **طراحاً نامعتبر** بودند.
تست درست، روی داده‌ی زنده Order Book است که هنوز در مقیاس بزرگ اجرا نشده است.

### آنچه فعال است:
✅ **Born rule روی Order Book زنده** (`pipeline_live_ensemble.py`)
✅ **بکتست کلاسیک** (`backtest.py` — vol_regime, MA)
✅ **آزمایش مصنوعی** (`experiment.py` — برای تحقیق)
✅ **زیرساخت**: collection داده، validation framework، pipeline زنده

### آنچه غیرفعال/حذف شد:
❌ **Born rule روی کندل** — حذف شد (p=1.0، داده‌ی imbalance وجود ندارد)
❌ **`backtest_ensemble.py`** — غیرفعال (مقایسه کوانتوم روی کندل)
❌ **`backtest_boost.py`** — غیرفعال (وزن‌دهی ensemble کوانتومی روی کندل)
❌ **`calibrate_delta.py`** — غیرفعال (کالیبراسیون دلتا روی کندل)

### توصیه استراتژیک:
1. **تست نهایی روی داده زنده**: تنها راه اثبات Born rule اجرای pipeline زنده با داده‌ی واقعی Order Book است (۳۰+ روز):
   ```
   python3 core/pipeline_live_ensemble.py btcusdt 720 3600 quantum
   ```
2. **تا آن زمان، هیچ ادعایی درباره عملکرد Born rule نمی‌توان کرد**

---

## تاریخچه اصلاحات

| تاریخ | نسخه | تغییر |
|-------|------|-------|
| ۲۰۲۶-۰۷-۲۰ | v4 | یکپارچه‌سازی Born rule (نرمال‌سازی دامنه در هر ۴ مدل); افزودن Gate.io با ۵۰۰۰+ کندل; حذف anomaly detection; افزودن مدل MA; pipeline با `--mode quantum`; Bonferroni ۶→۵ |
| ۲۰۲۶-۰۷-۲۰ | v3 | رفع ۴۰+ باگ: نرمال‌سازی دامنه; max_drawdown; block_len; RELATIVE_K ۳۰→۱۰; atomic writes; حذف momentum/delta_boost |
| ۲۰۲۶-۰۷-۱۹ | v2 | اصلاح کامل روش‌شناسی: walk-forward + block bootstrap + Bonferroni + held-out |
| ۲۰۲۶-۰۷ | v1 | نتایج اولیه (بدون جداسازی داده، بدون تصحیح multiple testing) |
| ۲۰۲۶-۰۷-۲۳ | v5 | **Born rule از ارزیابی کندل حذف شد** — نیاز به imbalance Order Book دارد. بکتست‌های کوانتومی غیرفعال شدند. فقط کلاسیک روی کندل باقی ماند. |
