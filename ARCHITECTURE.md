# Exchange-Q Architecture

## Overview

Exchange-Q applies the **Born rule from quantum probability** to financial market prediction. It models market participants' buy/sell decisions as interfering quantum states, where a hidden "context" variable creates non-classical correlations that classical law-of-total-probability models cannot capture.

No quantum hardware is required — the Born rule is a simple formula evaluated on a regular CPU.

---

## Data Flow

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   DATA LAYER    │────▶│  FEATURE EXTRACT │────▶│  PREDICTION     │
│                 │     │                  │     │                 │
│ Gate.io (hist.) │     │ compute_features │     │ Quantum (Born)  │
│ Huobi (live)    │     │ → buy_ratio      │     │ Vol regime      │
│ MarketSim (syn) │     │ → conviction     │     │ Classical ens.  │
│                 │     │ → imbalance      │     │                 │
│ _kline_cache/   │     │ → volatility     │     │ Ensemble fusion │
│ _live_results/  │     │ → delta          │     │                 │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
                                                          ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  VALIDATION     │◀────│  REPORTING       │◀────│  SIGNAL         │
│                 │     │                  │     │                 │
│ Block bootstrap │     │ JSON results     │     │ delta → signal  │
│ Bonferroni corr.│     │ CSV printout     │     │ confidence      │
│ MDD / Sharpe    │     │ analyze_live     │     │ alert           │
│ Profit factor   │     │ visualization    │     │                 │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

---

## Module Dependency Graph

```
data_historical.py           data_fetcher.py
        │                          │
        ▼                          ▼
  backtest.py ◄────────────── pipeline_live_*.py
  backtest_ensemble.py              │
  backtest_boost.py                 │
        │                          │
        ▼                          ▼
  delta_adaptive.py ◄────── ensemble.py / ensemble_adaptive.py
        │                          │
        └──────────┬───────────────┘
                   ▼
             validation.py
                   │
                   ▼
        comprehensive_report()
```

### Key Dependencies

| Module | Depends On | Used By |
|--------|-----------|---------|
| `data_historical.py` | — (stdlib + curl) | `backtest.py`, `backtest_ensemble.py`, `backtest_boost.py`, `calibrate_delta.py`, `validation_report.py`, `experiment_ablation.py` |
| `data_fetcher.py` | — (stdlib + Huobi API) | `pipeline_live_*.py`, `pipeline_one_shot.py`, `analyze_live_results.py` |
| `delta_adaptive.py` | — | `ensemble.py`, `ensemble_adaptive.py`, `backtest.py`, `backtest_ensemble.py`, `pipeline_live_*.py`, `experiment.py`, `pipeline_real.py` |
| `ensemble.py` | `delta_adaptive.py` | `pipeline_live_ensemble.py`, `pipeline_one_shot.py`, `backtest_boost.py` |
| `ensemble_adaptive.py` | `delta_adaptive.py` | `backtest_ensemble.py`, `validation_report.py` |
| `baselines.py` | — | `pipeline_live_*.py`, `pipeline_one_shot.py`, `pipeline_real.py` |
| `validation.py` | — | all backtests + live pipelines + experiment ablation |
| `market_sim.py` | — | `experiment.py`, `visualize.py` |

---

## The Born Rule in Detail

### Standard Form (used everywhere after v4 hardening)

```
Given a window of recent buy_ratios (or convictions):

1. Split into two groups at the median:
   high_group = {r : r > median}
   low_group  = {r : r <= median}

2. Compute statistics:
   p_high = |high_group| / N         # probability of high context
   p_low  = |low_group| / N          # probability of low context
   μ_high = mean(high_group)         # expected value in high context
   μ_low  = mean(low_group)          # expected value in low context

3. Compute interference phase δ from market context:
   δ = compute_delta(history)        # imbalance-based (live)
   δ = compute_delta_from_klines()   # return-based (backtest)

4. Apply Born rule:
   P_quantum = |√(p_high · μ_high) + √(p_low · μ_low) · e^(i·δ)|²
```

### Expansion

```
P_quantum = p_high·μ_high + p_low·μ_low + 2·√(p_high·p_low·μ_high·μ_low)·cos(δ)

           │______classical part______│ │_________interference term_________│
```

The interference term is what classical models cannot produce. It is positive when δ=0 (constructive) and negative when δ=π (destructive).

### Delta Interpretation

| Delta | Context | Meaning |
|-------|---------|---------|
| 0 | Strong imbalance, low vol | Constructive — market is directional |
| π/2 | Mixed signals | Max uncertainty — no interference |
| π | Low imbalance, high vol | Destructive — regime shift possible |

---

## Prediction Pipelines

### 1. Backtest (kline-based, binary direction)

```
Input: OHLCV klines → compute_features() → conviction, return
Target: next_candle_direction (0 or 1)
Models: classical_ensemble_klines, quantum_model_klines
Delta:  compute_delta_from_klines (return-based)
```

### 2. Live (order-book-based, continuous buy_ratio)

```
Input: Huobi order book + trades → compute_features() → buy_ratio, imbalance
Target: next_step_buy_ratio (continuous [0,1])
Models: classical_ensemble (baselines.py), _quantum_predict (ensemble.py)
Delta:  compute_delta (imbalance+volatility based)
```

### 3. Synthetic (controlled hidden context)

```
Input: MarketSimulator agents → buy_ratio, imbalance, hidden_context
Target: next_buy_ratio
Models: classical_model (market_sim.py), quantum_model (market_sim.py)
Delta:  compute_delta (imbalance+volatility based)
```

---

## Statistical Testing Framework

### Block Bootstrap (White's Reality Check)

```
H₀: quantum_win_rate ≤ 0.5
Hₐ: quantum_win_rate > 0.5

block_len = ceil(n^(1/3))           # handles autocorrelation
n_blocks = ceil(n / block_len)
For each bootstrap iteration:
    For each block: flip sign with p=0.5
    Count wins in resampled series
p_value = (count_extreme + 1) / (n_iterations + 1)
```

### Bonferroni Correction

```
N_HYPOTHESES_TOTAL = 5              # pre-registered tests
corrected_p = min(1.0, raw_p * 5)
significant_005 = corrected_p < 0.05
significant_001 = corrected_p < 0.01
```

### Financial Metrics

```
MDD:     max peak-to-trough drawdown on error-based equity curve
Sharpe:  mean(return_series) / std(return_series) * √(periods_per_year)
Profit Factor: win_count / loss_count  (inf if all wins)
```

---

## Key Files Reference

| File | Purpose | Entry Point |
|------|---------|-------------|
| `core/ensemble.py` | 2-model Ensemble (quantum + vol_regime) | `Ensemble()` class |
| `core/delta_adaptive.py` | Delta computation | `compute_delta()`, `compute_delta_from_klines()` |
| `core/validation.py` | Statistical testing | `comprehensive_report()` |
| `core/backtest.py` | Classical vs Quantum backtest | `python3 backtest.py` |
| `core/pipeline_live_ensemble.py` | Live ensemble pipeline | `python3 pipeline_live_ensemble.py ...` |
| `core/data_historical.py` | Historical data collection | `python3 data_historical.py` |
| `core/data_collector.py` | Live data collection | `python3 data_collector.py ...` |
| `core/data_fetcher.py` | Huobi API wrapper | `HuobiData()` class |
