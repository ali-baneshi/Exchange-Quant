# Exchange-Q Architecture

> Current references: [schema v6](docs/SCHEMA_V6.md) ·
> [statistics](docs/STATISTICS.md) · [runbook](docs/RUNBOOK.md) ·
> [evidence status](docs/EVIDENCE_STATUS.md)

## Boundary

Exchange-Q evaluates a prediction hypothesis using public market data. The current
runtime identity is schema v6 with implementation revision `v6r1` and acquisition
policy v1. It does not
authenticate to an exchange, place orders, maintain positions, or demonstrate
profitability. The architecture keeps three non-comparable experiments separate:

| Question | Data and target | Canonical path |
|---|---|---|
| Are classical candle features useful? | Historical OHLCV; binary direction | `backtest.py` |
| Does the gated Born policy improve live trade-flow prediction? | Live depth/trades; future `buy_ratio` | `pipeline_live_ensemble.py` |
| Does the formula behave under assumptions? | Simulated market target | `experiment.py` |

## Live Data Flow

```text
exchange ticker + depth + trades
        │
        ├─ validate timestamps, freshness, spread, and endpoint agreement
        ├─ persist and deduplicate raw trades in SQLite
        └─ accept a feature observation when its exchange timestamp is new
                    │
                    ▼
     recent feature history reaches warmup window?
                    │
                    ▼
     create one pending forecast anchored to exchange time
                    │
                    ▼
     capture future trades until target time is covered
                    │
          ┌─────────┴──────────┐
          ▼                    ▼
complete forward label    incomplete/unavailable label
          │                    │
          ▼                    ▼
eligible paired errors    diagnostics only, excluded
          │
          ▼
SQLite authoritative state → atomic JSON export → schema-aware analyzer
```

Feature `buy_ratio` uses the preceding `max(60, horizon_s)` seconds. The resolved
target is separately computed from locally captured future trades in the inclusive
forecast interval. This separation prevents using the target window as a feature.

## Core Components

| Component | Responsibility |
|---|---|
| `data_fetcher.py` | Fetches untrusted exchange endpoints; returns structured per-endpoint status, latency, errors, raw trades, features, and quality flags |
| `live_store.py` | SQLite state, observation/forecast persistence, raw-trade capture, deduplication, retention |
| `live_protocol.py` | Forecast timing helpers and pending lifecycle |
| `pipeline_live_ensemble.py` | Canonical v6 runner, quality gating, resolution, export, signals, cleanup |
| `quantum_core.py`, `delta_adaptive.py` | Born-rule construction, phase calculation, and fallback metadata |
| `baselines.py`, `ensemble.py` | Classical comparator and optional adaptive ensemble |
| `validation.py`, `analyze_live_results.py` | Paired-error inference and eligible-row aggregation |

## State, Persistence, and Concurrency

Each run has an SQLite database plus an atomic JSON export. SQLite uses WAL mode and
full synchronous writes. Unique indexes prevent duplicate accepted observations,
duplicate trades, and more than one pending forecast.

The runner takes a non-blocking `fcntl` lock on its run database, validates a
resumed run’s schema and configuration hash, and closes its store/unlocks on normal
exit or `SIGINT`/`SIGTERM`. The start scripts run in the foreground, write a PID
file for the process lifetime, and are designed to stop cleanly on `Ctrl-C`.

SQLite is authoritative. JSON checkpoints are written on material lifecycle events
and bounded periodic intervals. JSON is useful for inspection but is not a substitute for
the database during recovery or when it briefly lags a state transaction.

## Prediction Policy and Gates

The recorded `prediction` is the actual evaluated policy output. It is not always
the raw Born-rule value:

- bounded feature history is partitioned into high/low buckets;
- the runner records a classical component and interference term;
- destructive/negative behavior, unusable history, and saturation/constructive
  overshoot can use a fallback;
- `fallback_reason` identifies the execution path and must be reported as a
  diagnostic.

The current model uses a magnitude-oriented imbalance treatment. That is an
intentional implementation limitation, not proof that signed imbalance has no
predictive value.

## Eligibility and Observability

Only resolved records with a complete `forward_window` label and no disqualifying
entry/exit quality flag are score eligible. Important flags include stale trades,
crossed or empty books, timestamp problems, local/exchange clock skew, endpoint
skew, late resolution, short windows, and unavailable labels.

`SKIP forecast — pending unresolved` is normal: the protocol deliberately permits
only one unresolved forecast. Monitor SQLite-backed state, pending target time,
eligible/excluded counts, capture coverage, and fallback reasons before diagnosing a
hang.

## Version and Change Boundary

Behavior-preserving reliability fixes use v6r1. The manifest and configuration hash
include `implementation_revision` and `acquisition_policy_version`, so
pre-hardening v6 runs cannot silently resume or aggregate with v6r1.

Changes to the target definition, Born formula, signed imbalance semantics, bucket
ordering, fallback policy, or saturation thresholds require a new v7 protocol and a
fresh evidence corpus.

## Historical Components

Schema v3/v5 documents, dated lessons, kline-era Born claims, and older verification
reports are historical context only. See `docs/EVIDENCE_STATUS.md` for the current
claim boundary and `docs/SCHEMA_V6.md` for the active contract.
