# سند تحقیقاتی ۴: معماری پیشنهادی
## Interference-Based Context Detection System (ICDS)

### ۴.۱ نمای کلی

```
┌──────────────────────────────────────────────────────────────┐
│  INPUT LAYER (کلاسیک ۱۰۰٪)                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │ Order    │ │ Price    │ │ Volume   │ │ Sentiment│        │
│  │ Flow     │ │ Feed     │ │ Profile  │ │ Signals  │        │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘        │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  FEATURE EXTRACTION (کلاسیک ۱۰۰٪)                            │
│                                                              │
│  • Rolling statistics (mean, var, skew)                      │
│  • Regime detection (HMM, GARCH)                             │
│  • Microstructure features                                   │
│  • Context group splitting (above/below median)              │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  ★ QUANTUM KERNEL (نقطه کوانتومی دقیق)                       │
│                                                              │
│  • Born rule with interference:                              │
│    P = |√(p₁μ₁) + √(p₂μ₂)·e^{iδ}|²                          │
│                                                              │
│  • δ optimization: minimize prediction variance               │
│                                                              │
│  • Output: P_quantum vs P_classical gap + optimal δ          │
│                                                              │
│  • Complexity: O(n) — ضرب ماتریس مختلط ۲×۲                   │
│    روی CPU معمولی اجرا می‌شود، بدون GPU                       │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  SIGNAL GENERATION (کلاسیک ۱۰۰٪)                             │
│                                                              │
│  • اگر |P_quantum - P_classical| > threshold → ALERT         │
│  • اگر δ → π → regime change imminent                        │
│  • اگر δ → 0 → normal market conditions                      │
└──────────────────────────────────────────────────────────────┘
```

### ۴.۲ الگوریتم محوری

```
Input:  history_window (array of buy_ratios)
Output: P_quantum, P_classical, delta_optimal, signal

Step 1: Compute classical prediction
  P_classical = mean(history_window)

Step 2: Split context
  median_val = median(history_window)
  group_high = [r for r in history if r > median_val]
  group_low  = [r for r in history if r <= median_val]
  
  p_high = len(group_high) / len(history)
  p_low  = len(group_low) / len(history)
  mu_high = mean(group_high)
  mu_low  = mean(group_low)

Step 3: Apply Born rule (optimize delta)
  best_error = INF
  for delta in [0, π/4, π/2, 3π/4, π]:
    amp_high = √(p_high · mu_high)
    amp_low  = √(p_low · mu_low) · exp(i·delta)
    P_quantum = |amp_high + amp_low|²
    
    error = |P_quantum - actual_last|
    if error < best_error: update best_delta, best_P

Step 4: Generate signal
  gap = |best_P - P_classical|
  if gap > 0.1 AND best_delta > π/4:
    signal = REGIME_CHANGE_ALERT
  elif gap > 0.05:
    signal = CAUTION
  else:
    signal = NORMAL

Step 5: Return (best_P, P_classical, best_delta, signal)
```

### ۴.۳ پیچیدگی محاسباتی

فضای حالت: ۲ بعد (high/low context)
ضرب ماتریس: ۲×۲ مختلط ← O(1)
جستجوی δ: معمولاً ۵ نقطه ← O(5)
ذخیره‌سازی: فقط یک پنجره sliding ← O(window)

**کل سیستم روی یک Raspberry Pi هم اجرا می‌شود.**

### ۴.۴ مشخصه‌های منحصربه‌فرد (Unique Selling Points)

| ویژگی | مدل کلاسیک | ICDS (پیشنهادی) |
|-------|-----------|-----------------|
| تشخیص context پنهان | ❌ | ✅ (از طریق δ) |
| سازگاری با پارادوکس‌ها | ❌ | ✅ (Born rule) |
| بدون نهاد امین | ✅ | ✅ |
| اجرا روی سخت‌افزار معمولی | ✅ | ✅ |
| هشدار زودهنگام | ❌ | ✅ (قبل از حرکت قیمت) |
| پیچیدگی | O(n) | O(n) |
| شفافیت (explainability) | بالا | بالا |
| مقاومت در برابر overfitting | کم | زیاد (یک پارامتر δ) |

### ۴.۵ نحوه استفاده در دنیای واقعی

۱. **پیش‌بینی نقدینگی**: ICDS هشدار می‌دهد که liquidity pool در آستانه تخلیه است
۲. **مسیریابی هوشمند سفارش**: ICDS مسیری را انتخاب می‌کند که تداخل سازنده دارد
۳. **تشخیص MEV**: ICDS تشخیص می‌دهد که bots در کمین هستند (hidden context بالا)
۴. **مدیریت ریسک**: ICDS هشدار می‌دهد که مدل‌های VaR در آستانه شکست هستند
