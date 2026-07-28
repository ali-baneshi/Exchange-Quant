# Schema v8

Exchange-Q schema v8 separates diagnostic pipeline validation from primary-capable
research evidence.

## Evidence axes

| Axis | Values | Meaning |
|------|--------|---------|
| System integrity | `valid`, `valid_so_far`, `quarantined` | Lifecycle and persistence are internally consistent |
| Capture quality | `certified`, `uncertified`, `gapped` | Continuity and freshness of sequenced capture |
| Evidence status | `diagnostic`, `unscoreable`, `scoreable` | Whether outcomes may be used as scored research evidence |

These axes are independent. A run may have valid integrity while remaining
diagnostic-only or unscoreable.

## Slot lifecycle

```text
scheduled → forecasted → awaiting_label → resolved_scoreable | resolved_unscoreable
         ↘ skipped | cancelled | failed
```

Legacy v7 names remain readable from older databases but are not written by v8
writers.

## Policy identities

Runs and artifacts carry explicit policy IDs:

- `capture_policy`
- `clock_policy`
- `eligibility_policy`
- `feature_policy`
- `label_policy`

Primary runs reject mismatched artifacts, certifications, or policy revisions.

## Capture ledger

Schema v8 databases persist:

- `capture_sessions`
- `capture_checkpoints`
- `recovery_attempts`
- `continuity_intervals`
- `clock_samples`
- `provider_certifications`

Primary label resolution requires trade-stream watermarks and certified continuity.

## Timing (primary)

- Exchange-time slot targets
- Fixed decision lead before the target window
- Feature window ending at `slot_start - decision_lead`
- Fixed settlement delay after the label window
- Resolution only after watermarks exceed `slot_end + settlement_delay`

## Artifacts

Artifacts record provenance:

- `purpose`: `diagnostic_fixture` or `primary`
- `dataset_hash`
- development and calibration boundaries
- `calibration_status`: `uncalibrated` unless explicitly fitted

The bundled four-row artifact is `diagnostic_fixture` only.

## Compatibility

- Schema v7 databases open read-only for inspect/export
- Resume and mixed-schema analysis are prohibited
- Schema v8 evidence cannot be combined with v7 or incompatible policy revisions

## Commands

```bash
./scripts/exchange-q doctor --profile diagnostic
./scripts/exchange-q run --profile diagnostic --view outcome
./scripts/exchange-q provider-certify --provider binance-sequenced --symbol btcusdt --output certifications/binance-btcusdt.json
./scripts/exchange-q dataset build --capture-database runs/capture.sqlite3 --output datasets/development.json
./scripts/exchange-q fit datasets/development.json --purpose primary --output artifacts/v8/btcusdt-born.json
./scripts/exchange-q run --profile primary --study studies/btcusdt-primary.example.json
./scripts/exchange-q status --database runs/RUN.sqlite3 --run-id RUN --json
./scripts/exchange-q analyze --database runs/RUN.sqlite3 --run-id RUN
```
