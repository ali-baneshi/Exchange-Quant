# Exchange-Q Workflow Guide

## Entry-to-Exit Pipeline

This document explains the correct order of operations for using Exchange-Q.

---

## Step 0: Prerequisites

```bash
# Verify Python version (3.8+)
python3 --version

# No pip packages needed — 100% standard library
python3 -c "
import math, cmath, statistics, http.client, ssl
import json, os, sys, time, concurrent.futures, subprocess, signal
print('All stdlib modules available ✓')
"

# Clone / enter project directory
cd Exchange-Q
```

---

## Step 1: Collect Historical Data

**Goal:** Populate `_kline_cache/` with 5000+ candles per timeframe.

```bash
# Downloads 5000 candles for 15min, 60min, 1day from Gate.io
# Runs in ~30 seconds total, caches results
python3 core/data_historical.py
```

**Output:**
```
Fetching 5000 15min candles...
  total=5000  train+val=4000  held_out=1000
Fetching 5000 60min candles...
  total=5000  train+val=4000  held_out=1000
Fetching 5000 1day candles...
  total=5000  train+val=4000  held_out=1000
```

Data is cached in `core/_kline_cache/btcusdt_15min.json`, etc.
Re-running is instant if cache exists.

---

## Step 2: Run Backtests

**Goal:** Compare classical vs quantum models on historical data.

```bash
# 1. Basic classical vs quantum comparison
python3 core/backtest.py

# 2. Ensemble backtest (quantum + vol_regime)
python3 core/backtest_ensemble.py

# 3. Adaptive vs fixed weight comparison
python3 core/backtest_boost.py
```

Each script runs on all three timeframes (15min, 60min, 1day) with:
- Walk-forward: 60% train → 40% val → 20% held-out
- Block bootstrap with Bonferroni correction
- Financial metrics (MDD, Sharpe, profit factor)

---

## Step 3: Ablation Study

**Goal:** Determine if the Born rule adds value beyond simple models.

```bash
python3 core/experiment_ablation.py
```

**What it tests:**
| Comparison | Meaning |
|-----------|---------|
| 2-model (quantum+vol) vs 1-model (vol only) | Does Born rule help? |
| quantum+MA vs MA alone | Does Born rule help with MA? |
| Individual model errors | Which model is best alone? |

**Interpreting results:**
- If 2-model error < 1-model error → Born rule adds value
- If 2-model error >= 1-model error → Born rule does NOT help
- Current finding: **Borderline** — Born rule helps ~1-2% over simple models on 2000 candles, but NOT significant on 5000 candles (p=1.0)

---

## Step 4: Comprehensive Validation Report

```bash
# Single source-of-truth report for a specific period
python3 core/validation_report.py --period 60min

# Save report to JSON
python3 core/validation_report.py --period 60min --output report_60min.json
```

**Metrics explained:**

| Metric | What it measures | Good value |
|--------|-----------------|------------|
| `improvement_pct` | (classical_err - quantum_err) / classical_err | Positive = quantum wins |
| `win_rate` | Fraction of steps where quantum error < classical error | > 0.5 = quantum wins more |
| `raw_p_value` | Bootstrap p-value (uncorrected) | < 0.05 = raw significant |
| `bonferroni_p` | Corrected for 5 simultaneous tests | < 0.05 = robustly significant |
| `max_drawdown_q` | Worst peak-to-trough on quantum equity curve | Lower = smoother |
| `sharpe_q` | Risk-adjusted return (quantum) | Higher = better |
| `profit_factor` | Win sum / Loss sum | > 1.0 = profitable |

**Validation checklist (before trusting any result):**
- [ ] Classical error within ±0.01 of previous run on same dataset
- [ ] Bonferroni p > 0.05 reported as "NOT SIGNIFICANT" (no hedging)
- [ ] n ≥ 100 for any claim; n ≥ 500 for significance claims
- [ ] Held-out set = last 20%, NEVER touched during training
- [ ] Sharpe period matches data frequency (15min→35040, 60min→8760, 1day→365)

---

## Step 5: Synthetic Experiment

**Goal:** Controlled test with known ground truth (hidden context).

```bash
python3 core/experiment.py
python3 core/visualize.py
```

**Important:** On synthetic data, the Born rule performs **worse** than classical (23.5% higher error). This discrepancy with the theoretical claim needs investigation. The Born rule advantage on real data may come from market microstructure features not present in the synthetic model.

---

## Step 6: Collect Live Data

**Goal:** Accumulate buy_ratio + imbalance samples from Huobi (required for the quantum model to work with proper delta).

```bash
# Overnight collection (60s intervals, ~25 hours for 1500 samples)
nohup python3 core/data_collector.py btcusdt 1500 60 &

# Check progress
tail -f nohup.out

# Results saved to: core/_live_results/collected_btcusdt_<timestamp>.json
```

---

## Step 7: Run Live Pipeline (The Definitive Test)

**Goal:** Compare quantum vs classical on real streaming data with order-book imbalance — the only delta that gives the Born rule its advantage.

```bash
# Quantum-only mode (pure Born rule)
python3 core/pipeline_live_ensemble.py btcusdt 720 3600 quantum

# Ensemble mode (quantum + vol_regime)
python3 core/pipeline_live_ensemble.py btcusdt 720 3600 ensemble
```

**Parameters:**
| Arg | Example | Meaning |
|-----|---------|---------|
| symbol | btcusdt | Trading pair |
| n_steps | 720 | Number of hourly comparisons |
| delay | 3600 | Seconds between steps (3600 = 1 hour) |
| mode | quantum/ensemble | Model mode |

**Target:** 720+ hourly observations. Win rate > 50% with Bonferroni p < 0.05.

---

## Step 8: Analyze Results

```bash
# Analyze all live results
python3 core/analyze_live_results.py

# Analyze specific file
python3 core/analyze_live_results.py core/_live_results/btcusdt_ensemble_*.json
```

---

## Quick Reference: All Commands

```bash
# === DATA COLLECTION ===
python3 core/data_historical.py                              # Historical (30s)
nohup python3 core/data_collector.py btcusdt 1500 60 &      # Live overnight

# === BACKTESTS ===
python3 core/backtest.py                                     # Basic comparison
python3 core/backtest_ensemble.py                            # Ensemble comparison
python3 core/backtest_boost.py                               # Adaptive vs fixed

# === ABLATION & VALIDATION ===
python3 core/experiment_ablation.py                          # Born rule value?
python3 core/calibrate_delta.py                              # Delta calibration
python3 core/validation_report.py --period 60min             # Full report

# === SYNTHETIC ===
python3 core/experiment.py                                   # Synthetic test
python3 core/visualize.py                                    # Sparklines

# === LIVE ===
python3 core/pipeline_live_ensemble.py btcusdt 720 3600 quantum  # Quantum mode
python3 core/pipeline_live_ensemble.py btcusdt 720 3600 ensemble # Ensemble mode
python3 core/analyze_live_results.py                         # Analyze results

# === DEMO ===
python3 core/disjunction_demo.py                             # Disjunction effect
```

---

## Interpreting Research Claims

| Claim in `research_05_results.md` | What it actually means |
|-----------------------------------|----------------------|
| "Born rule error 0.4801" | On 2000 candles, 400 held-out, binary **direction** prediction (not buy_ratio) |
| "Born rule beats all simple models" | On the same 2000-candle dataset; NOT replicable on 5000 candles |
| "v4 unified Born rule" | Standardized the formula. Fixes have now been applied to all files. |
| "Bonferroni correction for 5 tests" | Corrects for 5 pre-registered hypotheses. Actual number tested is higher. |

**Bottom line:** The project has strong theoretical foundations and working infrastructure, but the empirical case for the Born rule beating classical baselines is **not yet proven**. The definitive test is the live pipeline with `--mode quantum` running for 30+ days.
