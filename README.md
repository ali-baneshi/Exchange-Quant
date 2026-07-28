# Exchange-Q

Exchange-Q is a durable **research evaluator** for a quantum-inspired
market-prediction hypothesis. It is not a trading system: it has no exchange
credentials, order routing, portfolio management, or profitability claim.

## Current Status — July 28, 2026

- The current live contract is **schema v6r1**: schema v6, model
  `born_constructive_v2`, data policy v4, implementation revision `v6r1`, and
  acquisition policy v1.
- The evaluated output is a **gated composite policy**. A raw Born-rule value can
  fall back to its classical component; execution-path diagnostics are required
  when reporting results.
- No v6 primary corpus currently proves lower prediction loss than the recorded
  classical comparator. No project result proves trading profitability.

See [docs/EVIDENCE_STATUS.md](docs/EVIDENCE_STATUS.md) before quoting a result.

## Deliberately Separate Paths

| Path | Target | Purpose | Evidence status |
|---|---|---|---|
| Historical kline path | Binary next-candle direction | Classical data and baseline checks | Not Born-rule evidence |
| Live order-book path | Future continuous trade `buy_ratio` | Primary Born-policy evaluation | Requires an eligible v6 corpus |
| Synthetic path | Simulator target | Formula and failure-mode diagnostics | Not market evidence |

Metrics from these paths are not directly comparable.

## Quick Start

```bash
pip install -r requirements-dev.txt
make test
make compile
```

Start the production research run in a dedicated terminal:

```bash
./scripts/start_production_run.sh
```

The command stays in the foreground by design. In other terminals:

```bash
./scripts/monitor_live.sh
tail -f live_quantum_v3.log
```

Press `Ctrl-C` in the starting terminal for graceful shutdown. If that terminal is
unavailable, use:

```bash
./scripts/stop_all_runs.sh
```

The production profile uses a 3600-second horizon, 60-second collection interval,
and stops after 720 **eligible** resolutions. The legacy log filename does not
change the schema; output is schema v6.

For an infrastructure-only 60-second run:

```bash
./scripts/start_exploratory_run.sh
./scripts/monitor_exploratory.sh
tail -f live_exploratory.log
```

Analyze current v6r1 results:

```bash
python3 core/analyze_live_results.py --schema-version 6 --exclude-collector
```

Pre-hardening v6 files are historical diagnostics. Inspect them only with
`--allow-pre-hardening-v6`; they are excluded from current aggregation.

## What Makes a Score Eligible?

The runner captures live features and raw trade pages locally, creates one pending
forecast, then resolves its future target only from locally captured trades in the
inclusive `[created_at_ms, target_at_ms]` interval. A primary score requires:

```text
status == "resolved"
resolved_label == "forward_window"
label_capture_complete == true
score_eligible == true
```

`label_unavailable`, partial capture, stale or malformed market data, timing skew,
and late resolution remain valuable diagnostics but are excluded from primary
scoring.

## Documentation Map

| Need | Reference |
|---|---|
| Operations, monitoring, recovery | [docs/RUNBOOK.md](docs/RUNBOOK.md) |
| Architecture and data flow | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Schema-v6 fields and lifecycle | [docs/SCHEMA_V6.md](docs/SCHEMA_V6.md) |
| Statistics and permitted claims | [docs/STATISTICS.md](docs/STATISTICS.md) |
| Current evidence limits | [docs/EVIDENCE_STATUS.md](docs/EVIDENCE_STATUS.md) |
| End-to-end workflows | [WORKFLOW.md](WORKFLOW.md) |
| Persian operational docs | [README.fa.md](README.fa.md), [docs/fa/README.md](docs/fa/README.md) |
| Historical material and audits | [core/research_INDEX.md](core/research_INDEX.md), [code_audit_v1/STALE.md](code_audit_v1/STALE.md) |

## Documentation Lifecycle

Current operational documents describe v6. Schema v3/v5 material, dated snapshots,
audit reports, verification reports, exploratory artifacts, and PDFs are preserved
as historical or background references. They are not silently rewritten as current
evidence.
