# Exchange-Q

Exchange-Q is fail-closed research infrastructure for forecasting future
aggressor-side trade flow. It does not place orders, manage positions, or establish
trading profitability.

## Current Contract

The canonical implementation is **schema v7 / revision v7r3**:

- raw trades and book observations are persisted before feature construction;
- features use the causal half-open window `[t-lookback, t)`;
- labels use the non-overlapping half-open window `[t, t+horizon)`;
- model artifacts are fitted on development data and frozen before evaluation;
- SQLite is authoritative and JSON is an explicit snapshot export;
- proper probabilistic loss is primary;
- labels are eligible only when the provider can prove capture continuity.

The bundled HTX WebSocket adapter is intentionally **diagnostic-only** because its
consumed messages do not provide enough continuity information to prove that no
trade was missed. It cannot produce eligible primary labels.

## Install

```bash
python3 -m pip install -e '.[dev]'
make test
make lint
```

Python 3.10 or newer is required.

## Commands

```bash
./scripts/exchange-q run --profile diagnostic
```

This single foreground command creates the diagnostic artifact when needed,
generates the run ID and SQLite path, applies bounded HTX-safe defaults, and shows
an integrated live dashboard. Redirected output automatically uses compact logs.
Press `Ctrl-C` for complete shutdown.

Advanced commands:

```bash
./scripts/exchange-q run --profile diagnostic --display log
./scripts/exchange-q status --database runs/RUN_ID.sqlite3 --run-id RUN_ID
./scripts/exchange-q stop --database runs/example.sqlite3 --run-id RUN_ID
./scripts/exchange-q analyze --database runs/example.sqlite3 --run-id RUN_ID
./scripts/exchange-q export \
  --database runs/example.sqlite3 \
  --run-id RUN_ID \
  --output artifacts/v7/RUN_ID.json
```

The run dashboard always identifies the generated database and run ID.

`fit` expects a JSON list containing `feature`, `buy_count`, and `total_count`.
The feature object follows `exchange_q.domain.FeatureWindow`.

## Evidence Boundary

There is currently no schema-v7 corpus proving model superiority. All schema-v6
and earlier runs, dated guides, audits, and result files are historical evidence
only. See `docs/EVIDENCE_STATUS.md`.

Historical candle experiments live under `research/` and are not comparable with
the live trade-flow evaluator.
