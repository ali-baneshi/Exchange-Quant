# Exchange-Q

**Quantum-inspired prediction for financial markets.** Born-rule interference models that capture non-classical correlations in market microstructure — no quantum hardware required.

**Status (2026-07-26):** Born rule has been **removed from kline-based evaluation** (all large-sample Bonferroni p = 1.0). Classical tools remain for klines. Born rule is only for **live order-book** pipelines via `quantum_core.py`.

## Quick Start

```bash
# System dependency for historical fetch: curl on PATH
command -v curl

# 1. Collect historical data (Gate.io API, cached oldest→newest)
python3 core/data_historical.py

# 2. Classical-only backtest on klines (binary direction target)
python3 core/backtest.py

# 3. Classical ablation (vol / MA / vol+ma)
python3 core/experiment_ablation.py

# 4. Classical validation report + live Born status
python3 core/validation_report.py --period 60min

# 5. Synthetic experiment (computed δ + hidden-sign probe)
python3 core/experiment.py

# 6. Live Born-rule pipeline (Huobi order book — the valid quantum path)
python3 core/pipeline_live_ensemble.py btcusdt 720 3600 quantum
```

Deprecated stubs (exit code 1): `backtest_ensemble.py`, `backtest_boost.py`, `calibrate_delta.py`.

## Project Structure

```
Exchange-Q/
├── core/                          # All source code
│   ├── data_fetcher.py            # Huobi live API (order book, trades, ticker)
│   ├── data_historical.py         # Gate.io historical klines (ascending + cache)
│   ├── features.py                # Shared kline feature computation
│   ├── quantum_core.py            # Single-source Born-rule predict
│   ├── live_protocol.py           # Forecast lookback + resolve-later helpers
│   ├── delta_adaptive.py          # Interference phase (delta) computation
│   ├── ensemble.py                # 2-model adaptive ensemble (quantum + vol_regime)
│   ├── ensemble_adaptive.py       # Alternative ensemble (relative-gap weights)
│   ├── baselines.py               # Classical models (SMA, EMA, momentum, lin-reg)
│   ├── backtest.py                # Classical-only kline backtest
│   ├── backtest_ensemble.py       # DEPRECATED stub
│   ├── backtest_boost.py          # DEPRECATED stub
│   ├── calibrate_delta.py         # DEPRECATED stub
│   ├── market_sim.py              # Synthetic market with hidden context
│   ├── experiment.py              # Born rule on synthetic data
│   ├── experiment_ablation.py     # Classical ablation (vol / MA)
│   ├── validation.py              # Statistical testing (block bootstrap, Bonferroni, Sharpe)
│   ├── validation_report.py       # Classical kline report + live Born status
│   ├── reality_check.py           # White's Reality Check wrapper
│   ├── pipeline_live_ensemble.py  # Primary live forecast pipeline
│   ├── pipeline_one_shot.py       # Cron one-shot with state v2
│   ├── pipeline_live_long.py      # Legacy long run (prefer ensemble)
│   ├── pipeline_real.py           # Demo/smoke only
│   ├── analyze_live_results.py    # Parse live JSON results
│   ├── visualize.py               # Sparkline visualization
│   ├── disjunction_demo.py        # Disjunction effect (Tversky & Shafir) demo
│   ├── _kline_cache/              # Cached historical klines
│   ├── _live_results/             # Live pipeline output
│   └── research_*.md              # Research notes / results
├── code_audit_v1/                 # Forensic code audit
├── verification_report.md         # Honest verdict: does it work?
└── README.md
```

## The Core Idea

**Classical models** use the law of total probability:
```
P(buy) = P(high)·P(buy|high) + P(low)·P(buy|low)
```

**Quantum model** adds an interference term via the Born rule (unnormalized quantum-cognition form in `quantum_core.py`):
```
P(buy) = |√(p_high·μ_high) + √(p_low·μ_low)·e^{iδ}|²
       = classical + 2√(p_high·p_low·μ_high·μ_low)·cos(δ)
```

Valid δ requires **real order-book imbalance**. Kline proxies are not a substitute (decision 2026-07-23).

## Quick Results Summary

| Scenario | Result | Status |
|----------|--------|--------|
| Born rule on 5000 candles (any TF) | Bonf. p = 1.0 | **Removed from kline eval** |
| Classical kline ensemble | Direction MAE reported by `backtest.py` | Active |
| Synthetic experiment | Quantum often worse; hidden-sign probe ≠ true oracle | Diagnostic only |
| Live pipeline (quantum mode) | 2866 obs aggregate: quantum MAE 0.38 vs classical 0.19 | **Negative — primary path still open for clean re-run** |

## Testing

```bash
make test
# Dev deps (optional): pip install -r requirements-dev.txt
```

52 unit tests cover data ordering, Born-rule core, validation stats, live protocol, and pipeline helpers. CI: `.github/workflows/test.yml`.

- **Gate.io** — Historical OHLCV, paginated. Preferred for classical backtests. Requires `curl`.
- **Huobi** — Live order book + trades + ticker for `buy_ratio` and `imbalance`. Required for Born rule.
- **Synthetic** — `MarketSimulator` with hidden context (synthetic imbalance only).

## Dependencies

Python 3.8+ standard library only (no pip packages). **System:** `curl` on PATH for `data_historical.py`.

## Recommended Workflow

```bash
python3 core/data_historical.py
python3 core/backtest.py
python3 core/experiment_ablation.py
python3 core/validation_report.py --period 60min
python3 core/experiment.py
# Live Born-rule evaluation (hours–days):
python3 core/pipeline_live_ensemble.py btcusdt 720 3600 quantum
python3 core/analyze_live_results.py
```

## More Info

- **[docs/RUNBOOK.md](./docs/RUNBOOK.md)** — Live pipeline operations
- **[CONTRIBUTING.md](./CONTRIBUTING.md)** — Tests, review checklist
- **[code_audit_v1/](./code_audit_v1/)** — Forensic code audit
- **[verification_report.md](./verification_report.md)** — Honest verdict
- **`core/research_05_results.md`** — Validation results archive
