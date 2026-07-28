# System Snapshot — July 28, 2026

> **Current educational snapshot.** The authoritative operational references are
> `RUNBOOK.md`, `SCHEMA_V6.md`, `STATISTICS.md`, and `EVIDENCE_STATUS.md`.

## What Is Implemented

| Item | Current value |
|---|---|
| Live schema | v6r1 (`schema_version=6`, revision `v6r1`) |
| Evaluated model identity | `born_constructive_v2` |
| Data policy | v4 |
| Acquisition policy | v1 |
| Storage authority | Per-run SQLite database |
| Export | Atomic schema-v6 JSON |
| Primary target | Future trade-count `buy_ratio` |
| Primary loss | Paired absolute-error comparison |
| Primary reporting target | 720 eligible resolved forecasts |

The project gathers public ticker, order-book, and trade data. It has no trading
credentials or execution capability.

## Feature, Forecast, and Label

The recent feature `buy_ratio` uses only past trades in the preceding
`max(60, horizon_s)` seconds. After warmup, the runner creates one pending forecast
anchored to exchange time when available. The target is computed later from locally
captured future trades whose timestamps inclusively fall in the forecast interval.

Incomplete capture is not filled with a substitute primary label. It becomes
`label_unavailable` and is excluded from scoring.

## Gates and Scoring

The recorded prediction is the gated policy output. The Born construction records
its classical component, interference, phase, raw value, and fallback reason. A
gate/fallback is part of the actual evaluation path, not an implementation detail to
hide.

Primary eligibility requires a resolved complete forward window and no disqualifying
quality condition. Quality controls cover stale/future/missing timestamps, clock and
endpoint skew, malformed/crossed/empty market data, late resolution, unavailable
labels, and short forward windows.

## Operating It

Start scripts run in the foreground. Run the start command in one terminal and the
monitor/log tail in another. `Ctrl-C` in the start terminal performs graceful
cleanup. A pending forecast causes normal `SKIP forecast — pending unresolved`
messages until it is due.

SQLite is authoritative for active-run monitoring and recovery. JSON is a readable
export and may lag a recent durable write.

## Claims

No current v6 corpus establishes superiority or profitability. MAE and paired
moving-block inference are primary; win rate, returns, and price simulations are
diagnostic only. Historical kline, synthetic, and v5 artifacts cannot be promoted
to v6 primary evidence.
