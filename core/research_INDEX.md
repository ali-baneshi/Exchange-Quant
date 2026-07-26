# Exchange-Q Research Index

Maps Persian research documents (`research_01`–`05`) to code modules and notes on staleness.

**English ops:** [../docs/README.md](../docs/README.md) | **Persian:** [../docs/fa/README.md](../docs/fa/README.md)

---

## Document map

| Research doc | Language | Maps to | Stale? |
|--------------|----------|---------|--------|
| [research_01_problem.md](./research_01_problem.md) | FA | Motivation — Intent Trilemma | Theory only — no code mapping |
| [research_02_nature.md](./research_02_nature.md) | FA | Quantum-inspired mechanisms (conceptual) | Theory only |
| [research_03_paradoxes.md](./research_03_paradoxes.md) | FA | [disjunction_demo.py](./disjunction_demo.py), [market_sim.py](./market_sim.py) | OK |
| [research_04_architecture.md](./research_04_architecture.md) | FA | [quantum_core.py](./quantum_core.py), [delta_adaptive.py](./delta_adaptive.py), live pipelines | **Vision doc** — δ grid search not implemented |
| [research_05_results.md](./research_05_results.md) | EN+FA | [verification_report.md](../verification_report.md), archived kline numbers | Partially stale — see banner |

---

## Code modules by topic

### Born rule and interference

| Module | Role |
|--------|------|
| `quantum_core.py` | `born_rule_predict()` — single source of Born predictions |
| `delta_adaptive.py` | `compute_delta()` — live δ ∈ [0, π/2] from order-book |
| `ensemble.py` | Quantum + vol_regime fusion for live ensemble mode |

### Live evaluation (valid Born path)

| Module | Role |
|--------|------|
| `pipeline_live_ensemble.py` | Canonical long-running pipeline → schema v5 JSON |
| `live_protocol.py` | `forecast_lookback`, `pending_due`, resolve-later |
| `data_fetcher.py` | Huobi order book, trades, ticker |
| `analyze_live_results.py` | Parse v3 JSON, segmented fallback stats |

### Classical / deprecated paths

| Module | Role |
|--------|------|
| `backtest.py` | Classical kline backtest (binary direction) — no Born |
| `backtest_ensemble.py` | DEPRECATED stub (exit 1) |
| `experiment.py` | Synthetic Born vs classical — diagnostic |

### Statistics

| Module | Role |
|--------|------|
| `validation.py` | Block bootstrap, Bonferroni, comprehensive_report |
| `reality_check.py` | White's Reality Check wrapper |

See [docs/STATISTICS.md](../docs/STATISTICS.md) for claim thresholds.

---

## Implementation vs research_04 (ICDS)

| research_04 vision | Current code |
|--------------------|--------------|
| δ grid search `[0, π/4, …, π]` | `compute_delta()` continuous mapping to [0, π/2] |
| δ → π means regime change | Live: π/2 = neutral interference; destructive path gated |
| HMM/GARCH regime detection | vol_regime baseline + rolling stats only |
| Sentiment signals | Not implemented |

---

## Related evidence

- [verification_report.md](../verification_report.md) — empirical verdict
- [docs/SCHEMA_V5.md](../docs/SCHEMA_V5.md) — JSON field reference
- [docs/STATISTICS.md](../docs/STATISTICS.md) — p-values and n thresholds
