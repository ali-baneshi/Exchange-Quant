# Audit Notes v1 — Comprehensive Module Summary

## Codebase Snapshot
- **Date:** 2026-07-20
- **Root:** `Exchange-Q/core/`
- **Python files:** 20
- **Research docs:** 4 (research_01 through 05)
- **Live results dir:** `_live_results/`

---

## Module Purpose & Data Flow

### Data Layer
```
data_fetcher.py          ← Huobi live API (ticker, depth, trades, klines)
data_historical.py       ← Gate.io historical klines (paginated, cached)
  _kline_cache/          ← JSON cache for historical data
```

### Feature Extraction
```
data_fetcher.compute_features()       → buy_ratio, imbalance, volatility, spread
backtest.py.compute_features()        → conviction, direction, volatility, imbalance
backtest_ensemble.py.compute_features() → same as backtest.py
backtest_boost.py.compute_features()  → same as backtest.py
calibrate_delta.py.compute_features_for_window() → volatility, conviction, trend
```

### Prediction Models
| File | Model | Input Features | Output |
|------|-------|---------------|--------|
| `baselines.py` | SMA, EMA, momentum, logistic | buy_ratio, imbalance, volatility | prediction in [0,1] |
| `market_sim.py` | classical_model | buy_ratio history | rolling mean |
| `market_sim.py` | quantum_model | buy_ratio history + delta | Born rule prediction |
| `ensemble.py` | _quantum_predict | conviction/buy_ratio history | prediction + delta |
| `ensemble.py` | _volregime_predict | conviction, volatility | prediction |
| `ensemble_adaptive.py` | _quantum_buyratio | buy_ratio/conviction | prediction + delta |
| `backtest.py` | quantum_model_klines | conviction + delta_from_klines | prediction + delta |
| `backtest_ensemble.py` | quantum_model_klines | conviction + hardcoded delta | prediction + delta |

### Ensemble / Meta-Learning
| File | Class | Strategy | Weight Formula |
|------|-------|----------|---------------|
| `ensemble.py` | Ensemble | 2-model (quantum + vol_regime) | exp(-gap * 10), relative to best |
| `ensemble_adaptive.py` | AdaptiveEnsemble | 2-model (quantum + vol_regime) | exp(-mean_err * 30), absolute |
| `experiment_ablation.py` | _EnsembleBase | N-model configurable | exp(-mean_err * 4) |

### Validation
| File | Function | Purpose |
|------|----------|---------|
| `validation.py` | comprehensive_report | Full report: n, wins, p-value, MDD, Sharpe, profit factor |
| `validation.py` | block_bootstrap_pvalue | White's Reality Check with block bootstrap |
| `validation.py` | bonferroni_correct | Correct for N_HYPOTHESES_TOTAL=5 |
| `validation.py` | max_drawdown_from_errors | MDD from error-based equity curve |
| `validation.py` | sharpe_ratio | Annualized Sharpe from error returns |
| `reality_check.py` | reality_check | Wrapper: block bootstrap + Bonferroni |
| `analyze_live_results.py` | analyze | Parse live JSON results |

### Orchestration
| File | Purpose |
|------|---------|
| `pipeline_live_ensemble.py` | Live streaming with 2-model Ensemble; `--mode quantum` crashes |
| `pipeline_live_long.py` | Long-running live pipeline (direct quantum, no Ensemble) |
| `pipeline_real.py` | Short live pipeline (direct quantum, no Ensemble) |
| `pipeline_one_shot.py` | Per-call pipeline; saves/loads state.json |
| `backtest.py` | Classical vs quantum on historical klines |
| `backtest_ensemble.py` | Ensemble backtest on klines |
| `backtest_boost.py` | Adaptive vs fixed weights comparison |
| `calibrate_delta.py` | Delta optimization scan |
| `experiment.py` | Synthetic market experiment |
| `validation_report.py` | Single-source-of-truth report |
| `visualize.py` | Sparkline visualization |

---

## Key Mathematical Formulas

### Born Rule (standard quantum cognition form)
```
amp_high = sqrt(p_high * mu_high)
amp_low  = sqrt(p_low * mu_low) * exp(i * delta)
P = |amp_high + amp_low|^2
  = p_high*mu_high + p_low*mu_low + 2*sqrt(p_high*p_low*mu_high*mu_low)*cos(delta)
```

### Born Rule WITH normalization (used by 5 files, wrong in 3 of 6 contexts)
```
norm = sqrt(p_high * mu_high + p_low * mu_low)
amp_high = sqrt(p_high * mu_high) / norm
amp_low  = sqrt(p_low * mu_low) / norm * exp(i * delta)
P = |amp_high + amp_low|^2
  = 1 + 2*sqrt(p_high*mu_high*p_low*mu_low) / (p_high*mu_high + p_low*mu_low) * cos(delta)
```

### Delta from Market Context (compute_delta)
```
context_factor = |avg_imbalance| * (1 - avg_volatility)
delta = 0      if context_factor > 0.7  (constructive)
delta = pi     if context_factor < 0.3  (destructive)
delta = pi/2   otherwise                (max uncertainty)
```

### Delta from Klines (compute_delta_from_klines)
```
avg_return = mean([(close-open)/open])
delta = 0      if avg_return >= 0
delta = pi     if avg_return < 0
```

### Ensemble Weight (ensemble.py)
```
gap = mean_error[i] - min(mean_errors)
weight[i] = exp(-gap * RELATIVE_K)   # RELATIVE_K = 10
weights /= sum(weights)
```

### Validation Metrics
```
win_rate = sum(quantum_error < classical_error) / n
raw_p = block_bootstrap_pvalue(errors_c, errors_q)  # H0: win_rate <= 0.5
corrected_p = min(1.0, raw_p * N_HYPOTHESES_TOTAL)  # N=5
sharpe = mean(return_series) / std(return_series) * sqrt(periods_per_year)
```

---

## Data Sources

### Huobi (Live)
- **API:** `api.huobi.pro`
- **Endpoints:** `/market/detail/merged` (ticker), `/market/depth` (order book), `/market/history/trade` (trades), `/market/history/kline` (klines)
- **Features:** buy_ratio, imbalance, volatility, volume_change, spread
- **Limitation:** Max 2000 klines per call. No historical pagination.

### Gate.io (Historical)
- **API:** `api.gateio.ws`
- **Endpoints:** `/api/v4/spot/candlesticks`
- **Features:** OHLCV (converted to Huobi-compatible format)
- **Capability:** Paginated, up to unlimited candles
- **Limitation:** No order book data (no imbalance)

### Synthetic (MarketSimulator)
- **Purpose:** Controlled experiments with known hidden context
- **Features:** buy_ratio, imbalance, volatility, hidden_context
- **Limitation:** Born rule performance is WORSE than classical on this data

---

## Known Results (from research_05_results.md)

| Experiment | n | Classical | Quantum | Improvement | Bonf. p |
|-----------|---|-----------|---------|-------------|---------|
| Born rule (60min held-out, 2000 candles) | 400 | 0.5112 | 0.4801 | +6.1% | not reported |
| Backtest (60min, 5000 candles) | 979 | 0.5031 | 0.5122 | -1.8% | 1.000 |
| Adaptive vs fixed (5000) | 984 | 0.5030 | 0.5022 | +0.16% | 1.000 |
| Ensemble vs standalone quantum (5000) | 979 | 0.5016 | 0.5127 | -2.2% | 1.000 |
| Synthetic experiment | ~480 | 0.1255 | 0.1549 | -23.5% | N/A |

**Key observation:** The only positive result (0.4801) is on 2000 candles with 400 held-out, un-corrected p-value, and on a DIFFERENT prediction task (binary direction) than the live pipeline.
