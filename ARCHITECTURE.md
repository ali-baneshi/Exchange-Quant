# Exchange-Q Schema v8 Architecture

## Trust Boundary

The system accepts untrusted public market events and produces auditable forecast
records. It has no authenticated exchange or order-execution capability.

```text
provider adapter
    │
    ├── validate and normalize immutable events
    ├── persist raw trades/books before evaluation
    ├── checkpoint sequenced capture (primary)
    └── expose explicit health and continuity capability
            │
            ▼
fixed non-overlapping scheduler
            │
            ├── causal feature window ending before slot start
            ├── frozen model artifact with provenance
            └── awaiting label window [t, t+horizon)
                        │
                        ▼
             trade watermark and continuity settled?
                 │               │
                yes              no
                 │               │
       resolved scoreable   resolved unscoreable
                 │
                 ▼
proper scoring and optional HAC inference
```

## Modes

| Mode | Provider | Evidence |
|------|----------|----------|
| Diagnostic | HTX WebSocket | pipeline validation only |
| Primary | KuCoin sequenced | scoreable only when certified |

## Components

| Component | Responsibility |
|---|---|
| `exchange_q/domain.py` | Events, windows, v8 lifecycle states, evidence helpers |
| `exchange_q/capture.py` | Provider-to-store capture hook contract |
| `exchange_q/providers/` | KuCoin primary adapter, Binance optional adapter, HTX diagnostic adapter, replay |
| `exchange_q/store.py` | Single-run schema v8 SQLite, capture ledger, v7 read-only compatibility |
| `exchange_q/runner.py` | Lifecycle orchestration, settlement, shutdown cleanup |
| `exchange_q/monitor.py` | Outcome and detail operator console |
| `exchange_q/cli.py` | Doctor, certify, dataset, run, analyze, export |
| `exchange_q/analysis.py` | Proper scores, calibration diagnostics, HAC and block sensitivity |

## State and Recovery

```text
scheduled → forecasted → awaiting_label
                              ├── resolved_scoreable
                              └── resolved_unscoreable
```

Legacy v7 states are readable from old databases but are never written by v8.
Each SQLite database is single-run; use a new database for every independent run.

Terminal runs must not retain open slots. Stopped, failed, completed, and
diagnostic-limit exits cancel open work with structured reasons.

## Timing Contract

- Features use `[slot_start - decision_lead - lookback, slot_start - decision_lead)`.
- Labels use `[slot_start, slot_start + horizon)`.
- Slot cadence is never shorter than the horizon.
- Primary resolution requires the trade watermark to reach
  `slot_end + settlement_delay`.
- Late or retroactive events create interval-specific continuity failures.

## Evidence semantics

Three independent axes are reported on every status export:

1. **Integrity** — lifecycle validity
2. **Capture quality** — certified / uncertified / gapped
3. **Evidence status** — diagnostic / unscoreable / scoreable

See [docs/SCHEMA_V8.md](docs/SCHEMA_V8.md) for policy IDs and capture ledger tables.
