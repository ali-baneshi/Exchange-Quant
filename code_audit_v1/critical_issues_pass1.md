# Critical Issues — Pass 1 (Logical & Mathematical)

**Status (2026-07-20):** Most P0-P2 issues have been fixed in code. See `FINAL_HARDENING_PLAN.md` for the detailed implementation status.

| Status | Count | Meaning |
|--------|-------|---------|
| ✅ FIXED | 9 | Code change applied and verified |
| ⏳ REMAINS | 1 | `pipeline_one_shot.py` state versioning (low impact) |

---

## CRITICAL BUG — P0

### Issue 1: `_quantum_predict` AttributeError Crash
**File:** `core/pipeline_live_ensemble.py:92`
```python
q_pred, q_delta = ensemble._quantum_predict(lookback)
```
**Problem:** `_quantum_predict` is a **module-level function** defined in `ensemble.py:19-49`, NOT a method of the `Ensemble` class. Python raises `AttributeError: 'Ensemble' object has no attribute '_quantum_predict'` on this line.

**Root cause:** The function was refactored out of the class (or never moved in), but the caller in `pipeline_live_ensemble.py` was not updated.

**Fix:** 
```python
# Line 92 of pipeline_live_ensemble.py
from ensemble import _quantum_predict
q_pred, q_delta = _quantum_predict(lookback)
```

---

## CRITICAL MATHEMATICAL INCONSISTENCY — P0

### Issue 2: Born Rule Normalization Inconsistent Across Files

**Files with normalization** (divide amplitude by `norm`):
| File | Line | Code |
|------|------|------|
| `ensemble.py` | 45-48 | `norm = sqrt(max(0, p_h*mu_h + p_l*mu_l)) or 1.0` |
| `ensemble_adaptive.py` | 36-38 | Same pattern |
| `backtest.py` | 137-139 | Same pattern |
| `backtest_ensemble.py` | 76-78 | Same pattern |
| `calibrate_delta.py` | 66-67 | Same pattern |

**Files WITHOUT normalization** (raw Born rule):
| File | Line | Code |
|------|------|------|
| `market_sim.py` | 114-115 | `amp_high = sqrt(p_high*mu_high); amp_low = sqrt(p_low*mu_low)*exp(i*delta)` |
| `pipeline_live_long.py` | 51-52 | Same |
| `pipeline_real.py` | 47-48 | Same |

**Why normalization is wrong:**

After normalization, the Born rule becomes:
```
P = 1 + 2*sqrt(p_h*mu_h*p_l*mu_l)*cos(delta) / (p_h*mu_h + p_l*mu_l)
```

When the classical prediction (`p_h*mu_h + p_l*mu_l`) is very small (e.g., 0.01), the interference term can dominate, pushing P far above 1. The subsequent `max(0, min(1, P))` clamp loses all interference information.

Without normalization, the Born rule correctly produces:
```
P = p_h*mu_h + p_l*mu_l + 2*sqrt(p_h*mu_h*p_l*mu_l)*cos(delta)
```

This is always in [0, 1] when mu_h, mu_l in [0, 1] and p_h, p_l are probabilities.

**Fix:** Remove normalization from ALL 5 files. Use the standard quantum cognition formulation consistently.

---

## CRITICAL DESIGN FLAW — P0

### Issue 3: Target Variable Mismatch Between Backtest and Live Pipelines

**Backtest targets** (binary):
- `backtest.py:159`: `target = next_candle["direction"]` (0 or 1)
- `backtest_ensemble.py:95`: `target = 1.0 if next_close > next_open else 0.0` (0 or 1)
- `backtest_boost.py:72`: same

**Live pipeline targets** (continuous):
- `pipeline_live_ensemble.py:87`: `actual = history[-1]["buy_ratio"]` (continuous in [0,1])
- `pipeline_live_long.py:100`: same
- `pipeline_real.py:75`: same

**Backtest models predict**:
- `conviction` = direction * body_ratio (continuous in [0,1])
- Error = `|continuous_prediction - binary_target|`
- A model predicting 0.51 for an up-candle has error 0.49
- A model predicting 0.99 for an up-candle has error 0.01

**Live models predict**:
- `buy_ratio` (continuous in [0,1])
- Error = `|continuous_prediction - continuous_target|`
- This is a fundamentally different, harder task

**Impact:** The reported "Born rule error 0.4801" is for binary direction prediction, NOT for continuous buy_ratio prediction. These results are **not comparable**. A 6% improvement on the direction task does NOT imply 6% improvement on the buy_ratio task.

**Fix:** Either:
1. (Recommended) Standardize on buy_ratio prediction for all pipelines, with backtests computing buy_ratio from klines (e.g., using volume-weighted direction)
2. Or clearly document that backtest and live results measure different things

---

## CRITICAL METRIC ERROR — P0

### Issue 4: Sharpe Ratio Annualization Period Mismatch

**File:** `backtest.py:181`:
```python
report = comprehensive_report(c_errs, q_errs, label, periods_per_year=8760)
```

**File:** `backtest_ensemble.py:115`:
```python
report = comprehensive_report(e_errs, q_errs, label, periods_per_year=8760)
```

Both hardcode `periods_per_year=8760` (hourly), but are called with 15min, 60min, AND 1day data:
- For 15min: should be 35040 (4 * 24 * 365)
- For 60min: 8760 is correct
- For 1day: should be 365

**Impact:** Sharpe ratios for 15min data are undervalued by ~2x; for 1day data they are overvalued by ~24x.

**Fix:** Pass the correct period based on the candle interval.

---

## IMPORTANT INCONSISTENCIES — P1

### Issue 5: Delta Computation Strategy Divergence

Three different delta strategies exist:

| Strategy | Function | Used By | Key Used |
|----------|----------|---------|----------|
| Imbalance + Volatility | `delta_adaptive.py:compute_delta()` | Live pipelines | `imbalance`, `volatility` |
| Return-based | `delta_adaptive.py:compute_delta_from_klines()` | `backtest.py` | `close`, `open` |
| Hardcoded return check | inline in `backtest_ensemble.py:75` | `backtest_ensemble.py` | `return` key |
| Context-based lookup | `calibrate_delta.py` | `calibrate_delta.py` | conviction features |

**File:** `backtest_ensemble.py:73-75`:
```python
recent_returns = [h.get("return", 0) for h in history[-10:]]
avg_ret = statistics.mean(recent_returns) if recent_returns else 0
delta = 0.0 if avg_ret >= 0 else math.pi
```
This duplicates (with slight differences) what `compute_delta_from_klines` already does, but bypasses the shared function. The `compute_delta_from_klines` has confidence computation (`* (1 - min(1, avg_vol * 10))`) while the hardcoded version doesn't.

**Fix:** Unify all delta computations to use `compute_delta_from_klines` for kline data and `compute_delta` for order-book data.

### Issue 6: Weight Computation Divergence

**`ensemble.py:86-113`** (`Ensemble`):
```python
gap = mean_errs[i] - min_err
self.weights[i] = math.exp(-gap * RELATIVE_K)  # RELATIVE_K = 10
```

**`ensemble_adaptive.py:93-104`** (`AdaptiveEnsemble`):
```python
mean_err = statistics.mean(recent)
self.weights[i] = math.exp(-mean_err * RELATIVE_K)  # RELATIVE_K = 30
```

These use DIFFERENT strategies:
- `Ensemble`: weight based on **relative** gap to best model (K=10)
- `AdaptiveEnsemble`: weight based on **absolute** error (K=30)

The `_EnsembleBase` in `experiment_ablation.py` uses yet another: `math.exp(-mean_err * 4)`.

**Impact:** The same input data produces different ensemble predictions depending on which class is used.

### Issue 7: Feature Name Fragility

Multiple quantum model functions access features via fallback chains:
```python
h.get("buy_ratio", h.get("conviction", 0))
```

This is necessary because backtest features use `conviction` while live features use `buy_ratio`. However:
- `backtest.py:57`: stores `conviction` (NOT `buy_ratio`)
- `data_fetcher.py:149-157`: stores `buy_ratio` (NOT `conviction`)
- `ensemble.py:23`: expects either via fallback
- `market_sim.py:53`: stores `buy_ratio`

The fallback silently hides bugs. If a feature dict is missing BOTH keys, it defaults to 0 with no warning.

### Issue 8: Serialization Format Incompatibility

**File:** `_live_results/state.json` contains:
- 3-element `weights`: `[0.583, 0.208, 0.208]`
- 3-element `performance` dict with keys: `quantum`, `momentum`, `vol_regime`
- Result entries with `momentum_raw`, `w_momentum`, `delta_boost`

**Current code:** `Ensemble.MODEL_NAMES = ["quantum", "vol_regime"]` (2 models).

**File:** `pipeline_one_shot.py:52-57`:
```python
def _restore_ensemble(ens, state):
    if state.get("performance"):
        for name in ens.MODEL_NAMES:
            if name in state["performance"]:
                ens.performance[name] = state["performance"][name]
    ens._refresh_weights()
```

This only restores 2 of 3 models from the saved state. The restored weights (after `_refresh_weights`) will be recomputed from only quantum + vol_regime performance, which will produce different weights than what would have been computed by the original 3-model system.

---

## MINOR ISSUES — P2

### Issue 9: Block Length Ceiling Bug
**File:** `validation.py:115`:
```python
block_len = max(1, int(n ** (1/3) + 1e-10))
```
The comment says "Use int(round(...)) to avoid floating-point floor errors" but the code uses `int(...)` which is floor, not round. The `1e-10` fudge is insufficient for edge cases. Should use:
```python
block_len = max(1, int(n ** (1/3)) + 1)  # proper ceil
```

### Issue 10: Dead Code in backtest_boost.py
**File:** `backtest_boost.py:64`:
```python
original_refresh = ensemble._refresh_weights
ensemble._refresh_weights = lambda: None
```
`original_refresh` is saved but never used. Minor cleanup.

### Issue 11: Constant `buy_ratio` values in live results
**File:** `_live_results/state.json` shows `buy_ratio` oscillating between 0.4333, 0.5, 0.9333, 1.0 — many repeated values. The `fetch_trades` call with `size=30` gives only 30 trades, so `buy_ratio = buy_count / 30` has resolution of 1/30 ≈ 0.0333. This low granularity may mask the Born rule's advantage.

### Issue 12: Missing `count` field handling
**File:** `data_historical.py:98`: Sets `"count": 0` for Gate.io candles (which don't have a count field). But `backtest.py:24-28` uses `candle.get("count", 0)` which is fine. Not a bug but worth noting.

### Issue 13: `calibrate_delta.py:66` missing `max(0, min(1, ...))` clamp
```python
return max(0, min(1, abs(amp_h + amp_l) ** 2))
```
Wait, this does have clamping. Let me re-check... Yes, `calibrate_delta.py:68` has `return max(0, min(1, abs(amp_h + amp_l) ** 2))`. OK this is fine.
