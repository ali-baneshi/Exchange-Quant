# FINAL HARDENING PLAN

## Implementation Status (updated 2026-07-26)

| Priority | Total | Fixed | Remaining |
|----------|-------|-------|-----------|
| **P0** | 4 | 4 | 0 |
| **P1** | 4 | 4 | 0 |
| **P2** | 2 | 2 | 0 |
| **Total** | **10** | **10** | **0** |

**P1 state versioning:** Done in `pipeline_one_shot.py` (`STATE_VERSION = 2`, backup before reset, 2-model performance keys).

**Post-hardening (2026-07-23 / 2026-07-26):** Born rule removed from kline evaluation; classical-only backtest/report; live forecast protocol unified; `data_historical` ascending contract fixed.

---

## Priority Overview

| Priority | Count | Description |
|----------|-------|-------------|
| **P0** | 4 | Must fix — causes crashes, wrong results, or invalid metrics |
| **P1** | 4 | Should fix — causes inconsistent behavior across pipelines |
| **P2** | 2 | Nice to fix — minor bugs, code clarity |

---

## P0 — URGENT (crashes / wrong results) — ✅ ALL DONE

### FIX 1: `_quantum_predict` AttributeError Crash  ✅ DONE

**File:** `core/pipeline_live_ensemble.py:92`
**Problem:** Calls `ensemble._quantum_predict(lookback)` but `_quantum_predict` is a module-level function, not a method.
**Fix:**

```python
# Replace line 92
from ensemble import _quantum_predict
q_pred, q_delta = _quantum_predict(lookback)
```

---

### FIX 2: Unify Born Rule Normalization Across All Files  ✅ DONE

**Files:**
- `core/ensemble.py:45-48` — remove normalization
- `core/ensemble_adaptive.py:36-38` — remove normalization
- `core/backtest.py:137-139` — remove normalization
- `core/backtest_ensemble.py:76-78` — remove normalization
- `core/calibrate_delta.py:66-67` — remove normalization

**Standard form to use everywhere** (matches `market_sim.py`, `pipeline_live_long.py`, `pipeline_real.py`):

```python
# Standard Born rule (quantum cognition formulation)
amp_h = math.sqrt(p_high * mu_high)
amp_l = math.sqrt(p_low * mu_low) * cmath.exp(1j * delta)
pred = abs(amp_h + amp_l) ** 2
return max(0, min(1, pred))
```

**Remove these lines** from each file:
```python
# BEFORE (BAD — has normalization):
norm = math.sqrt(max(0, p_h * mu_h + p_l * mu_l)) or 1.0
amp_h = math.sqrt(max(0, p_h * mu_h)) / norm
amp_l = math.sqrt(max(0, p_l * mu_l)) / norm * cmath.exp(1j * delta)
pred = abs(amp_h + amp_l) ** 2

# AFTER (GOOD — standard Born rule):
amp_h = math.sqrt(p_h * mu_h)
amp_l = math.sqrt(p_l * mu_l) * cmath.exp(1j * delta)
pred = abs(amp_h + amp_l) ** 2
```

---

### FIX 3: Fix Sharpe Ratio Periods Per Year  ✅ DONE

**Files:**
- `core/backtest.py:181`
- `core/backtest_ensemble.py:115`
- `core/backtest_boost.py` (if it calls comprehensive_report)

**Fix:** Pass correct period based on data interval:

```python
# In main() of backtest.py:
PERIODS = {
    "15min": 35040,  # 4 * 24 * 365
    "60min": 8760,   # 1 * 24 * 365
    "1day": 365,
}

for period, n in [("15min", 5000), ("60min", 5000), ("1day", 5000)]:
    # ... fetch data ...
    _, report_ho = run_backtest(held_out, f" [held-out {period}]",
                                periods_per_year=PERIODS[period])
```

Similarly update `run_backtest` to accept and pass through `periods_per_year`.

---

### FIX 4: Standardize Target Variable  ✅ DONE (documentation)

**Decision:** Standardize on **direction prediction** for all backtest pipelines (keep existing), and clearly **document the difference** between backtest (binary direction) and live (continuous buy_ratio) targets.

**Action:** Add a prominent comment in research_05_results.md and all report outputs:

```
WARNING: Backtest results predict BINARY DIRECTION (0/1).
Live pipeline results predict CONTINUOUS BUY_RATIO [0,1].
These are DIFFERENT TASKS and are NOT directly comparable.
```

If time permits, create a unified evaluation that maps both tasks to the same metric (e.g., classification accuracy for buy_ratio thresholded at 0.5).

---

## P1 — IMPORTANT (inconsistent behavior) — ✅ 3/4 DONE

### FIX 5: Unify Delta Computation  ✅ DONE

**Action:** Make `backtest_ensemble.py:quantum_model_klines` use `compute_delta_from_klines` instead of hardcoded return-based delta.

```python
# In backtest_ensemble.py, replace lines 73-75:
# OLD:
recent_returns = [h.get("return", 0) for h in history[-10:]]
avg_ret = statistics.mean(recent_returns) if recent_returns else 0
delta = 0.0 if avg_ret >= 0 else math.pi

# NEW:
from delta_adaptive import compute_delta_from_klines
delta, _ = compute_delta_from_klines([{...}])  # needs kline dicts
```

**Note:** `quantum_model_klines` in `backtest_ensemble.py` takes feature dicts (with `conviction`, `return`), not raw klines. Need to either:
1. Convert features to kline-like format before calling `compute_delta_from_klines`
2. Or create a `compute_delta_from_features` function

Recommend option 2: add a wrapper that computes delta from features.

---

### FIX 6: Serialization Format Compatibility  ✅ DONE (P1)

**Files:** `core/pipeline_one_shot.py`, `_live_results/state.json`, `_live_results/results_ensemble.json`

**Status (2026-07-26):** `pipeline_one_shot.py` uses `STATE_VERSION = 2` with backup-on-migration. Live ensemble output uses schema v3 with `run_id`.

---

### FIX 7: Unify Weight Computation Strategy  ✅ DONE

**Decision:** Standardize on `ensemble.py`'s strategy (relative gap) with `RELATIVE_K = 10`. Either:
1. Make `AdaptiveEnsemble` delegate to `Ensemble`'s weight logic, or
2. Update `AdaptiveEnsemble` to use the same relative-gap formula

**If keeping both classes:** Update `ensemble_adaptive.py:98`:
```python
# OLD:
self.weights[i] = math.exp(-mean_err * RELATIVE_K)  # K=30, absolute
# NEW:
min_err = min(mean_errs)
gap = mean_err - min_err
self.weights[i] = math.exp(-gap * 10.0)  # K=10, relative
```

---

### FIX 8: Standardize Feature Names  ✅ DONE

**Create a unified feature schema.** All feature dicts should contain BOTH `conviction` and `buy_ratio` where possible, with a single canonical name.

**Quick fix:** Update `data_fetcher.py:compute_features` to also store `conviction`:
```python
return {
    ...
    "buy_ratio": round(buy_ratio, 4),
    "conviction": round(buy_ratio, 4),  # alias
    ...
}
```

And update `backtest.py:compute_features` to also store `buy_ratio`:
```python
features = {
    "conviction": conviction,
    "buy_ratio": conviction,  # alias
    ...
}
```

This eliminates the need for the fragile `h.get("buy_ratio", h.get("conviction", 0))` fallback pattern.

---

## P2 — DESIRABLE (cleanup, minor) — ✅ ALL DONE

### FIX 9: Fix Block Length Ceiling  ✅ DONE

**File:** `core/validation.py:115`
```python
# OLD:
block_len = max(1, int(n ** (1/3) + 1e-10))

# NEW:
block_len = max(1, int(n ** (1 / 3)) + 1)
```

---

### FIX 10: Fix Seed in Market Simulator  ✅ DONE

**File:** `core/market_sim.py`
```python
# At the top of __init__ (or just before agent creation):
import random
random.seed(42)  # or accept seed as parameter
```

---

## Data Collection Protocol

### Step 1: Collect Historical Data (done in seconds)
```bash
python3 core/data_historical.py
```
Collects 5000 candles for 15min, 60min, 1day from Gate.io. Cached in `_kline_cache/`.

### Step 2: Run Backtests on Historical Data
```bash
python3 core/backtest.py          # Classical vs quantum
python3 core/backtest_ensemble.py # Ensemble backtest
python3 core/backtest_boost.py    # Adaptive vs fixed
python3 core/validation_report.py --period 60min
```

### Step 3: Collect Live Data (overnight)
Create and run `core/data_collector.py` (see empirical_gaps_pass2.md):
```bash
nohup python3 core/data_collector.py btcusdt 1500 60 &
```

### Step 4: Run Live Pipeline
After Fix 1 is applied:
```bash
# Quantum-only mode (pure Born rule evaluation)
python3 core/pipeline_live_ensemble.py btcusdt 720 3600 quantum

# Or ensemble mode
python3 core/pipeline_live_ensemble.py btcusdt 720 3600 ensemble
```

---

## Validation Checklist

Before any result is accepted as reliable:

- [ ] **Error stability**: Classical error within ±0.01 of previous run on same dataset
- [ ] **p-value honesty**: All Bonferroni-corrected p-values > 0.05 are reported as "NOT SIGNIFICANT"
- [ ] **Block bootstrap**: n_bootstrap >= 10000, block_len uses ceiling
- [ ] **Held-out integrity**: Held-out set is the last 20%, never touched during training
- [ ] **Numerical determinism**: Same dataset produces same results (±1e-6) on re-run
- [ ] **Sharpe period**: periods_per_year matches data frequency
- [ ] **Feature consistency**: All feature dicts contain required keys (no silent fallback to 0)
- [ ] **Delta source documented**: Report whether delta was from imbalance (live) or returns (historical)
- [ ] **Sample size**: n > 100 for any claim, n > 500 for statistical significance claims
- [ ] **No data leakage**: No lookahead in window construction (lookback excludes current step)

---

## Summary of All Code Changes

| # | File | Change Type | Priority | Status |
|---|------|-------------|----------|--------|
| 1 | `pipeline_live_ensemble.py:92` | Fix function call | P0 | ✅ DONE |
| 2 | `ensemble.py:45-48` | Remove normalization | P0 | ✅ DONE |
| 3 | `ensemble_adaptive.py:36-38` | Remove normalization | P0 | ✅ DONE |
| 4 | `backtest.py:137-139` | Remove normalization | P0 | ✅ DONE |
| 5 | `backtest_ensemble.py:76-78` | Remove normalization | P0 | ✅ DONE |
| 6 | `calibrate_delta.py:66-67` | Already correct (no normalization) | P0 | ✅ N/A |
| 7 | `backtest.py:181` | Pass correct periods_per_year | P0 | ✅ DONE |
| 8 | `backtest_ensemble.py:115` | Pass correct periods_per_year | P0 | ✅ DONE |
| 9 | `backtest_ensemble.py:73-75` | Use compute_delta_from_klines | P1 | ✅ DONE |
| 10 | `pipeline_one_shot.py` | Add version to state.json | P1 | ✅ DONE |
| 11 | `ensemble_adaptive.py:98` | Use relative-gap weighting | P1 | ✅ DONE |
| 12 | `data_fetcher.py:149-157` | Add conviction alias | P1 | ✅ DONE |
| 13 | `backtest.py:22-61` | Add buy_ratio alias | P1 | ✅ DONE |
| 14 | `validation.py:115` | Fix block_len ceiling | P2 | ✅ DONE |
| 15 | `market_sim.py` | Add random.seed(42) | P2 | ✅ DONE |

**Total: 15 changes across 15 files. All applied.**
