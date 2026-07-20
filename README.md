# Exchange-Q

**Quantum-inspired prediction for financial markets.** Born-rule interference models that capture non-classical correlations in market microstructure — no quantum hardware required.

## Quick Start

```bash
# 1. Collect historical data (runs in seconds via Gate.io API)
python3 core/data_historical.py

# 2. Run backtest: Classical vs Quantum on 5000 candles
python3 core/backtest.py

# 3. Ensemble backtest
python3 core/backtest_ensemble.py

# 4. Ablation: does Born rule add value over simple models?
python3 core/experiment_ablation.py

# 5. Synthetic experiment
python3 core/experiment.py

# 6. Live pipeline (requires Huobi API access — quantum mode)
python3 core/pipeline_live_ensemble.py btcusdt 100 3600 quantum
```

## Project Structure

```
Exchange-Q/
├── core/                          # All source code
│   ├── data_fetcher.py            # Huobi live API (order book, trades, ticker)
│   ├── data_historical.py         # Gate.io historical klines (paginated, cached)
│   ├── delta_adaptive.py          # Interference phase (delta) computation
│   ├── ensemble.py                # 2-model adaptive ensemble (quantum + vol_regime)
│   ├── ensemble_adaptive.py       # Alternative ensemble (relative-gap weights)
│   ├── baselines.py               # Classical models (SMA, EMA, momentum, lin-reg)
│   ├── backtest.py                # Classical vs Quantum on historical klines
│   ├── backtest_ensemble.py       # Ensemble backtest
│   ├── backtest_boost.py          # Adaptive vs fixed weight comparison
│   ├── market_sim.py              # Synthetic market with hidden context
│   ├── experiment.py              # Born rule on synthetic data
│   ├── experiment_ablation.py     # Does Born rule add value? (quantum vs vol only)
│   ├── calibrate_delta.py         # Delta optimization scan on real data
│   ├── validation.py              # Statistical testing (block bootstrap, Bonferroni, Sharpe)
│   ├── validation_report.py       # Single-source-of-truth report
│   ├── reality_check.py           # White's Reality Check wrapper
│   ├── pipeline_live_ensemble.py  # Live streaming ensemble
│   ├── pipeline_live_long.py      # Long-running live pipeline
│   ├── pipeline_real.py           # Short live pipeline
│   ├── pipeline_one_shot.py       # Per-invocation pipeline (persists state)
│   ├── analyze_live_results.py    # Parse live JSON results
│   ├── visualise.py               # Sparkline visualization
│   ├── disjunction_demo.py        # Disjunction effect (Tversky & Shafir) demo
│   ├── _kline_cache/              # Cached historical klines
│   ├── _live_results/             # Live pipeline output
│   ├── research_01_problem.md     # Intent Trilemma (Persian)
│   ├── research_02_nature.md      # Nature's quantum examples (Persian)
│   ├── research_03_paradoxes.md   # Quantum cognition paradoxes (Persian)
│   ├── research_04_architecture.md# Proposed architecture (Persian)
│   └── research_05_results.md     # Validation results v4 (Persian)
├── code_audit_v1/                 # Full forensic code audit
│   ├── audit_notes_v1.md          # Module summary & data flow
│   ├── critical_issues_pass1.md   # Bugs found (most now fixed)
│   ├── empirical_gaps_pass2.md    # Statistical & data gaps
│   ├── reproducibility_pass3.md   # Reproducibility audit
│   └── FINAL_HARDENING_PLAN.md    # Fix plan with statuses
├── verification_report.md         # Honest verdict: does it work?
└── README.md                      # This file
```

## The Core Idea

**Classical models** use the law of total probability:
```
P(buy) = P(high)·P(buy|high) + P(low)·P(buy|low)
```

**Quantum model** adds an interference term via the Born rule:
```
P(buy) = |√(p_high·μ_high) + √(p_low·μ_low)·e^{iδ}|²
       = classical + 2√(p_high·p_low·μ_high·μ_low)·cos(δ)
```

The interference term captures non-classical correlations caused by hidden market context (dark pools, latent sentiment, MEV bots) that classical models cannot see. The phase δ controls whether interference is constructive (δ=0) or destructive (δ=π).

## Quick Results Summary

| Scenario | Result | Status |
|----------|--------|--------|
| Born rule on 2000 candles (60min held-out) | Error 0.4801 vs 0.5112 (classical) | Borderline — p-value not reported |
| Born rule on 5000 candles (60min held-out) | Error 0.5122 vs 0.5031 (classical) | **Not significant** (p=1.0) |
| Ensemble adaptive vs fixed weights | 0.5022 vs 0.5030 | **Not significant** (p=1.0) |
| Synthetic experiment | Quantum **worse** by 23.5% | Contradicts theory |
| Live pipeline (quantum mode) | **Untested at scale** | Requires 30+ day run |

**Honest assessment:** To date, there is no statistically significant evidence that the Born rule beats classical baselines on historical kline data. The true test is the live pipeline with real order-book imbalance — unrun at scale.

## Data Sources

- **Gate.io** — Historical OHLCV, paginated up to 5000+ candles. Preferred for backtests.
- **Huobi** — Live order book depth + trades + ticker for `buy_ratio` and `imbalance`. Required for quantum mode.
- **Synthetic** — `MarketSimulator` with hidden context. For controlled experiments.

## Dependencies

Python 3.8+ standard library only (no pip packages needed):
- `math`, `cmath`, `statistics`, `random` — numerics
- `http.client`, `ssl` — API calls
- `json`, `os`, `sys`, `time` — I/O
- `concurrent.futures` — parallel API fetching
- `subprocess` — curl fallback
- `signal` — graceful shutdown

## Recommended Workflow

```bash
# Step 1: Collect historical data (fast)
python3 core/data_historical.py

# Step 2: Run all backtests
python3 core/backtest.py
python3 core/backtest_ensemble.py
python3 core/backtest_boost.py
python3 core/validation_report.py --period 60min

# Step 3: Ablation (is Born rule adding value?)
python3 core/experiment_ablation.py

# Step 4: Collect live data (overnight)
nohup python3 core/data_collector.py btcusdt 1500 60 &

# Step 5: Run live pipeline (after data collection)
python3 core/pipeline_live_ensemble.py btcusdt 720 3600 quantum
```

## More Info

- **[code_audit_v1/](./code_audit_v1/)** — Full forensic code audit with all findings
- **[verification_report.md](./verification_report.md)** — Honest verdict on Born rule performance
- **`core/research_05_results.md`** — Validation results v4 (Persian, with English summary)
