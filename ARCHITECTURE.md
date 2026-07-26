# Exchange-Q Architecture

> **JSON schema reference:** [docs/SCHEMA_V5.md](./docs/SCHEMA_V5.md) | **Statistics:** [docs/STATISTICS.md](./docs/STATISTICS.md)

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
  features.py                 live_protocol.py
  backtest.py                      │
  experiment_ablation.py           ▼
  validation_report.py      pipeline_live_*.py / one_shot
        │                          │
        │                          ▼
        │                   quantum_core.py ◄── ensemble.py
        │                          │
        └──────────┬───────────────┘
                   ▼
             validation.py
```

### Key Dependencies

| Module | Depends On | Used By |
|--------|-----------|---------|
| `data_historical.py` | stdlib + curl | `backtest.py`, `validation_report.py`, `experiment_ablation.py` |
| `features.py` | — | `backtest.py`, `experiment_ablation.py`, `validation_report.py` |
| `data_fetcher.py` | stdlib + Huobi API | `pipeline_live_*.py`, `pipeline_one_shot.py`, `data_collector.py` |
| `quantum_core.py` | `delta_adaptive.py` | `ensemble.py`, `market_sim.py`, all live pipelines |
| `live_protocol.py` | — | all live pipelines |
| `delta_adaptive.py` | — | `quantum_core.py`, `experiment.py` |
| `ensemble.py` | `quantum_core.py` | `pipeline_live_ensemble.py`, `pipeline_one_shot.py` |
| `baselines.py` | — | live pipelines |
| `validation.py` | — | reports + live summary |
| `market_sim.py` | `quantum_core.py` | `experiment.py`, `visualize.py` |

**Deprecated (stubs, exit 1):** `backtest_ensemble.py`, `backtest_boost.py`, `calibrate_delta.py` — Born rule removed from klines 2026-07-23.

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
   δ = compute_delta(history)        # order-book: imbalance + volatility (live)
   # Live order-book δ is mapped to [0, π/2] (constructive → neutral)
   # Kline return-based delta is NOT used for Born-rule evaluation (removed 2026-07-23)

4. Apply Born rule (unnormalized; see quantum_core.py):
   P_quantum = |√(p_high · μ_high) + √(p_low · μ_low) · e^(i·δ)|²
```

### Expansion

```
P_quantum = p_high·μ_high + p_low·μ_low + 2·√(p_high·p_low·μ_high·μ_low)·cos(δ)

           │______classical part______│ │_________interference term_________│
```

The interference term is what classical models cannot produce. It is positive when δ=0 (constructive) and negative when δ=π (destructive). On the **live order-book path**, δ ∈ [0, π/2] and negative interference is gated via `destructive_interference`.

### Delta Interpretation

| Delta | Context | Meaning |
|-------|---------|---------|
| 0 | Strong imbalance, low vol (live) | Constructive — market is directional |
| π/2 | Weak context (live) or mixed signals | Neutral — cos(δ)=0, no interference |
| π | Kline proxy only | Destructive — gated to classical part in `quantum_core` |

**Live fallback chain:** bucketing tries `buy_ratio` → `buy_ratio_volume` → `imbalance`; on failure returns mean with `fallback_reason` in `{insufficient_history, flat_history, single_bucket}`. If interference term is negative, `fallback_reason: destructive_interference` returns the classical part instead.

---

## Prediction Pipelines

### 1. Backtest (kline-based, classical only, binary direction)

```
Input: OHLCV klines (oldest→newest) → features.compute_features() → conviction
Target: next_candle_direction (0 or 1)
Models: classical_ensemble_klines only
Born rule: REMOVED from this path (2026-07-23)
```

### 2. Live (order-book-based, continuous buy_ratio, forecast)

```
Input: Huobi order book + trades → buy_ratio, imbalance
Lookback: live_protocol.forecast_lookback → history[-window:]
Target: FUTURE buy_ratio after horizon_s (resolve-later)
Models: classical_ensemble (baselines.py), quantum_core.born_rule_predict
Delta:  compute_delta (imbalance+volatility based)
```

### 3. Synthetic (controlled hidden context)

```
Input: MarketSimulator agents → buy_ratio, synthetic imbalance, hidden_context
Target: next_buy_ratio
Models: classical_model, quantum_model → both route Born through quantum_core
Delta:  compute_delta; optional hidden-sign probe (δ=0/π), not a true oracle
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

## Live Pipeline Semantics (2026-07-26)

- **Canonical entry point:** `pipeline_live_ensemble.py`
- **Cron alternative:** `pipeline_one_shot.py` uses persisted `state.json` with `STATE_VERSION = 2` (not schema v5 JSON); prefer ensemble pipeline for definitive eval
- **One pending forecast at a time** — no overlapping horizons when `sample_interval_s << horizon_s`
- **Resolve timing:** `live_protocol.pending_due()` before scoring
- **Ensemble mode:** weights update via `Ensemble.predict_and_update()` on resolve
- **Output schema:** version 3 JSON with `run_id`, `quality_flags`, `bucket_feature`, optional `ensemble_weights`
- **Corpus policy:** active v5 runs in `_live_results/`; legacy v2–v4/collector in `_live_results/_archive/pre_v5/`

---

## Key Files Reference

| File | Purpose | Entry Point |
|------|---------|-------------|
| `core/ensemble.py` | 2-model Ensemble (quantum + vol_regime) | `Ensemble()` class |
| `core/delta_adaptive.py` | Delta computation | `compute_delta()`, `compute_delta_from_klines()` |
| `core/validation.py` | Statistical testing | `comprehensive_report()` |
| `core/backtest.py` | Classical-only kline backtest | `python3 backtest.py` |
| `core/pipeline_live_ensemble.py` | **Primary** live pipeline (ensemble/quantum) | `python3 pipeline_live_ensemble.py ...` |
| `core/pipeline_one_shot.py` | Cron one-shot with state v2 | `python3 pipeline_one_shot.py` |
| `core/pipeline_real.py` | Demo/smoke only (short runs) | `python3 pipeline_real.py ...` |
| `core/pipeline_live_long.py` | Legacy long run — prefer ensemble pipeline | `python3 pipeline_live_long.py ...` |
| `core/data_historical.py` | Historical data collection | `python3 data_historical.py` |
| `core/data_collector.py` | Live data collection | `python3 data_collector.py ...` |
| `core/data_fetcher.py` | Huobi API wrapper | `HuobiData()` class |
