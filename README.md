# Exchange-Q

Exchange-Q is a **research evaluator** for a quantum-inspired market-prediction hypothesis. It is not a trading system: it never stores exchange credentials, places orders, or makes profitability claims.

The project compares a frozen Born-rule model with classical baselines on two intentionally separate paths:

| Path | Target | Purpose | Claim status |
|---|---|---|---|
| Historical kline path | Next candle direction (`0`/`1`) | Classical baselines and data-pipeline checks | Born rule is **not** evaluated here |
| Live order-book path | Future trade `buy_ratio` (`0..1`) | Primary Born-rule experiment | Requires schema v5 evidence |
| Synthetic path | Simulator `buy_ratio` | Diagnostics and theory exploration | Not market evidence |

## Status — July 26, 2026

- Born-rule-on-kline findings are deprecated: historical klines do not contain the required order-book imbalance signal.
- The canonical live evaluator writes **schema v5** and scores only forecasts with a complete, locally captured future trade window.
- The frozen live model is `born_constructive_v1`.
- Existing legacy results do **not** establish that the Born rule outperforms classical baselines. A completed, preregistered schema-v5 corpus is still required.

Read `verification_report.md` before quoting any research result.

## Quick Start

### Requirements

- Python 3.10+ is supported in CI; runtime code uses the standard library.
- `curl` is required for historical Gate.io collection.
- `pytest==9.0.3` is the only development dependency.

```bash
python3 --version
command -v curl
pip install -r requirements-dev.txt
make test
make compile
```

### Classical historical workflow

```bash
python3 core/data_historical.py
python3 core/backtest.py
python3 core/experiment_ablation.py
python3 core/validation_report.py --period 60min
```

These commands report **classical** performance on binary candle direction. Do not compare their MAE directly with live `buy_ratio` MAE.

### Live research workflow

```bash
# Recommended: runs tests, acquires the production lock, and starts the frozen study.
./scripts/start_production_run.sh

# Monitor an active run.
./scripts/monitor_live.sh

# Analyze only primary-eligible schema-v5 files.
python3 core/analyze_live_results.py --schema-version 5 --exclude-collector
```

The production configuration uses a one-hour horizon and stops after 720 eligible resolutions. It normally needs about 30 calendar days because only one forecast may be pending at a time.

## What Makes a Live Score Eligible?

For every forecast, the evaluator:

1. captures order-book features and raw trades locally;
2. stores raw trades in the run SQLite database with deduplication;
3. creates a forecast for `[created_at_ms, target_at_ms]`;
4. resolves it only from trades captured in that exact future interval;
5. rejects the score when capture coverage is incomplete, the trade window is too short, or a disqualifying quality flag is present.

`resolved_label: "forward_window"` plus `label_capture_complete: true` is required for primary analysis. Snapshot fallback values are retained for diagnostics as `label_unavailable` and are never scored or used to update ensemble weights.

## Project Map

| Need | Start here |
|---|---|
| Operational commands, monitoring, recovery | `docs/RUNBOOK.md` |
| Architecture and module boundaries | `ARCHITECTURE.md` |
| Schema-v5 field reference | `docs/SCHEMA_V5.md` |
| Statistical protocol and claim rules | `docs/STATISTICS.md` |
| End-to-end workflow | `WORKFLOW.md` |
| Contributor workflow | `CONTRIBUTING.md` |
| Persian operational documentation | `README.fa.md`, `docs/fa/README.md` |
| Current evidence and limitations | `verification_report.md` |
| Historical research/audits | `core/research_INDEX.md`, `code_audit_v1/STALE.md` |

## Repository Layout

```text
core/
  data_fetcher.py              Exchange API adapter and live features
  live_store.py                Durable SQLite state, raw trades, retention
  live_protocol.py             Forecast timing and pending-forecast helpers
  pipeline_live_ensemble.py    Canonical schema-v5 live evaluator
  quantum_core.py              Shared Born-rule implementation
  ensemble.py                  Frozen quantum + volatility-regime ensemble
  baselines.py                 Classical live baselines
  validation.py                Paired-error statistics
  analyze_live_results.py      Schema-aware result analysis
  data_historical.py           Gate.io historical kline collection
  backtest.py                  Classical-only kline backtest
docs/
  RUNBOOK.md                   Operations
  SCHEMA_V5.md                 Current result contract
  STATISTICS.md                Research and inference policy
  fa/                          Persian operational documentation
scripts/                       Start, monitor, archive, and stop helpers
```

## Safety and Scope

- This repository evaluates predictions; it is not an order-execution bot.
- Financial metrics are diagnostic, not investment advice.
- Do not treat exploratory slices, legacy schemas, synthetic results, or kline-era Born results as primary evidence.
- Do not mix schema v2–v4 documents with schema-v5 aggregates.

## Documentation Lifecycle

Current operational documents describe schema v5. Date-stamped lessons, `code_audit_v1/`, and `docs/SCHEMA_V3.md` are preserved as historical material and explicitly marked as such. PDFs are fixed reference artifacts; their current Markdown counterparts are the maintainable sources of truth.
