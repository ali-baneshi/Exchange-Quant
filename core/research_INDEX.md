# Exchange-Q Research Index

> **Theory and history index, not an operational contract.** Current system behavior
> is defined by `docs/SCHEMA_V6.md`, `docs/RUNBOOK.md`, and
> `docs/EVIDENCE_STATUS.md`.

**English operations:** [../docs/README.md](../docs/README.md) |
**Persian operations:** [../docs/fa/README.md](../docs/fa/README.md)

## Research Documents

| Document | Role | Relationship to implementation |
|---|---|---|
| `research_01_problem.md` | Market-motivation thought experiment | Theory only; no direct code contract |
| `research_02_nature.md` | Nature/quantum inspiration | Background only; does not validate a market model |
| `research_03_paradoxes.md` | Quantum-cognition examples | Conceptual/demo relation; not live-market evidence |
| `research_04_architecture.md` | ICDS vision | Explicitly differs from implemented code |
| `research_05_results.md` | Historical results archive | Kline-era material; not current live evidence |

These documents may motivate experiments but cannot establish that the v6 evaluated
policy is accurate, quantum-native, statistically superior, or profitable.

## Code Map

| Topic | Current modules |
|---|---|
| Born construction and phase | `quantum_core.py`, `delta_adaptive.py` |
| Classical comparator and ensemble | `baselines.py`, `ensemble.py` |
| Live evaluation | `pipeline_live_ensemble.py`, `live_protocol.py`, `live_store.py`, `data_fetcher.py` |
| Result analysis and statistics | `analyze_live_results.py`, `validation.py` |
| Historical kline checks | `data_historical.py`, `backtest.py` |
| Synthetic diagnostics | `experiment.py`, `market_sim.py` |

The canonical live path is `pipeline_live_ensemble.py` → SQLite durable state →
schema-v6r1 JSON export → `analyze_live_results.py --schema-version 6`.

## Important Differences from Vision Documents

- The live phase is computed continuously and bounded to `[0, π/2]`; it is not a
  grid search over a full phase range.
- The production evaluator uses future captured-trade `buy_ratio`, not kline
  direction.
- HMM/GARCH regimes, sentiment signals, and broad ICDS architecture concepts are
  not current implemented live dependencies unless explicitly present in code.
- `reality_check.py` retains a deprecated historical wrapper; current analysis uses
  paired moving-block mean-loss inference.

## Evidence Boundary

Read `../docs/EVIDENCE_STATUS.md` before interpreting any research result. Dated
artifacts, schema-v5 records, and background theory are retained for traceability,
not promoted to v6 evidence.
