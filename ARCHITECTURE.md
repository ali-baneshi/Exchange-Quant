# Exchange-Q Architecture

> Current operational contract: [schema v5](./docs/SCHEMA_V5.md) · [statistical protocol](./docs/STATISTICS.md) · [runbook](./docs/RUNBOOK.md)

## Purpose and Boundary

Exchange-Q is a durable **research-evaluation pipeline** for a quantum-inspired prediction hypothesis. It has no exchange authentication, portfolio management, order-routing, or execution layer.

The architecture separates three questions that must not be mixed:

| Question | Data | Target | Canonical code |
|---|---|---|---|
| Are classical candle features useful? | Historical OHLCV | Binary next-candle direction | `backtest.py` |
| Does the frozen Born model improve live trade-flow prediction? | Live order book and trades | Future continuous `buy_ratio` | `pipeline_live_ensemble.py` |
| Does the formula behave under controlled assumptions? | `MarketSimulator` | Simulator target | `experiment.py` |

## System Context

```text
Gate.io OHLCV ───────────────► historical cache ─► classical backtest/report

Huobi ticker/depth/trades ───► feature snapshot ─┐
                         raw trades ─► SQLite ───┼─► live forecast
                                                  │
                  pending forecast + exact future trade window
                                                  │
                                                  ▼
                                       eligible paired-error record
                                                  │
                                                  ▼
                                  schema-v5 JSON export / analyzer / report
```

The SQLite database is the durable source of truth for a live run. JSON is an atomic, inspectable export of that state.

## Live Evaluation Lifecycle

```text
fetch features + raw trades
        │
        ├─ validate timestamp and quality flags
        ├─ persist raw trade batch and deduplicate trade IDs
        └─ append accepted observation
                 │
                 ▼
       warmup window complete?
          │ no                  │ yes and no pending forecast
          ▼                     ▼
       collect only        create one pending forecast
                                      │
                                      ▼
                              target time reached?
                                      │
                                      ▼
                   read locally captured trades in exact interval
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
             complete label                      incomplete label
                    │                                   │
                    ▼                                   ▼
          score + optional ensemble update       diagnostic only; excluded
```

## Module Boundaries

| Module | Responsibility | Key contract |
|---|---|---|
| `data_fetcher.py` | Fetches ticker, depth, trades, and klines; computes live features | Exchange data is untrusted and may be incomplete |
| `live_store.py` | SQLite persistence for state, observations, forecasts, raw trades, and retention | Deduplicates observations and raw trades |
| `live_protocol.py` | Pure forecast timing helpers | One pending forecast at a time |
| `pipeline_live_ensemble.py` | Canonical durable live evaluator | Emits schema v5 and preserves label provenance |
| `quantum_core.py` | Shared Born-rule prediction and fallback metadata | All live Born predictions pass through this module |
| `delta_adaptive.py` | Phase calculation | Live order-book delta is bounded to `[0, π/2]` |
| `ensemble.py` | Quantum + volatility-regime adaptive ensemble | Updates only from eligible resolved labels |
| `baselines.py` | Classical comparators | Returns bounded predictions |
| `validation.py` / `reality_check.py` | Paired error statistics | Significance requires the frozen primary protocol |
| `analyze_live_results.py` | Schema-aware filtering and aggregation | Defaults to v5 and rejects non-primary labels |

## Born-Rule Model

For a high/low partition of a bounded feature history:

```text
P = |sqrt(p_high * mu_high) + sqrt(p_low * mu_low) * exp(i * delta)|²
```

The implementation records the classical component and interference term separately:

```text
classical_part = p_high * mu_high + p_low * mu_low
interference_term = 2 * sqrt(p_high * p_low * mu_high * mu_low) * cos(delta)
```

### Live safeguards

- Bucketing tries usable live features and returns explicit fallback metadata.
- Flat or insufficient histories revert to a bounded mean.
- Negative interference is gated back to the classical part.
- Constructive overshoot or near-saturation is gated back to the classical part.
- The active model name is `born_constructive_v1`; it is a frozen experimental arm, not a claim of mathematical optimality.

## Persistence and Recovery

Each live run has:

```text
core/_live_results/<run_id>.sqlite3   durable source of truth
core/_live_results/<run_id>.json      atomic schema-v5 export
```

On resume, the runner verifies the stored `config_hash`, restores observations and forecasts, rebuilds history, and restores ensemble performance. A configuration mismatch stops the run rather than silently mixing experiments.

Raw trades are retained locally for 30 days. Trade batches record response saturation and capture timing; incomplete coverage makes a label ineligible rather than silently substituting a different target.

## Data Quality Model

| Condition | Result |
|---|---|
| Duplicate exchange timestamp | Not used in forecast history |
| Empty trades/depth, crossed market, endpoint skew | Recorded as quality flags; may disqualify a score |
| Too few future trades | `label_unavailable` |
| Capture gap, or saturated response with no overlap to prior frontier | `label_unavailable` |
| Late resolution | Disqualified from primary scoring |

## Deprecated and Historical Components

| Component | Status | Reason |
|---|---|---|
| `backtest_ensemble.py`, `backtest_boost.py`, `calibrate_delta.py` | Deprecated stubs | Born rule removed from kline evaluation |
| `pipeline_one_shot.py` | Legacy convenience path | State v2; not schema-v5 evidence |
| `pipeline_live_long.py` | Legacy | Canonical runner has durable v5 behavior |
| `pipeline_real.py` | Smoke/demo only | Not a primary evaluator |
| `docs/SCHEMA_V3.md`, `code_audit_v1/` | Historical | Preserve context, not current instructions |

## Operational References

- `docs/RUNBOOK.md`: start, monitor, stop, resume, and troubleshoot live runs.
- `docs/SCHEMA_V5.md`: field-level contract and eligibility invariants.
- `docs/STATISTICS.md`: primary hypothesis and reporting threshold.
- `WORKFLOW.md`: end-to-end usage, including historical and synthetic paths.
