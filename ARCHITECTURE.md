# Exchange-Q v7 Architecture

## Trust Boundary

The system accepts untrusted public market events and produces auditable forecast
records. It has no authenticated exchange or order-execution capability.

```text
provider adapter
    │
    ├── validate and normalize immutable events
    ├── persist raw trades/books
    └── expose explicit health and continuity capability
            │
            ▼
fixed non-overlapping scheduler
            │
            ├── causal feature window [t-lookback, t)
            ├── frozen model artifact
            └── pending label window [t, t+horizon)
                        │
                        ▼
             complete coverage proof?
                 │               │
                yes              no
                 │               │
       resolved eligible   resolved ineligible
                 │
                 ▼
proper scoring and calibration analysis
```

## Components

| Component | Responsibility |
|---|---|
| `exchange_q/domain.py` | Typed events, windows, forecasts, labels, manifests, and lifecycle states |
| `exchange_q/providers/` | Provider protocol, replay adapter, and diagnostic HTX stream adapter |
| `exchange_q/models.py` | Frozen normalized Born-inspired model and defensible baselines |
| `exchange_q/scheduler.py` | Horizon-aligned, non-overlapping forecast slots |
| `exchange_q/store.py` | Transactional schema-v7 SQLite state, leases, events, labels, and exports |
| `exchange_q/runner.py` | Acquisition supervision, deterministic recovery, and lifecycle orchestration |
| `exchange_q/analysis.py` | Proper scores, calibration, HAC paired inference, and power calculations |
| `exchange_q/cli.py` | Single operational interface |

## Mathematical Boundary

The model is quantum-inspired, not quantum computation. Buy and sell outcome
amplitudes are constructed separately and normalized:

```text
p_buy = |A_buy|² / (|A_buy|² + |A_sell|²)
```

Signed imbalance is preserved. Constructive and destructive phases remain
representable. There is no saturation gate, output clipping, destructive fallback,
or silent substitution of a classical model.

Parameters are fitted on time-ordered development data and represented by a hashed
immutable artifact. Primary runs do not update model parameters online.

## State and Recovery

Forecast state transitions are validated transactionally:

```text
scheduled → created → pending_label
scheduled → skipped
pending_label → resolved_eligible | resolved_ineligible | expired | failed
```

Terminal states cannot transition again. Forecast creation, resolution, labels,
exclusions, and lifecycle events commit atomically.

A database lease identifies the single permitted writer. Restart recovery inspects
the latest persisted slot and continues without recreating a terminal forecast.
JSON exports use a consistent read transaction and are never used for recovery.

## Fail-Closed Eligibility

A forecast is eligible only when:

- raw events cover the complete half-open label interval;
- the provider reports certifiable continuity;
- no reconnect or sequence gap intersects the interval;
- the label meets the preregistered minimum trade count;
- the run, model artifact, provider semantics, timing, and policy identities match.

Unsupported provider continuity produces diagnostics, never primary evidence.
