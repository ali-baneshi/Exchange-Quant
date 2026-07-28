# Exchange-Q Schema-v8 Audit

**Audit date:** July 28, 2026  
**Scope:** Schema v8 implementation in `exchange_q/`  
**Test baseline:** 58 passed (`make test`)

## Summary

Schema v8 introduces explicit diagnostic versus primary modes, a capture ledger,
three-axis evidence reporting, and fail-closed primary gates. Legacy schema v7
databases remain readable and exportable but cannot resume under v8 writers.

## Inventory

| Area | Status |
|------|--------|
| v8 lifecycle states | Implemented |
| Capture ledger tables and APIs | Implemented and wired from Binance/runner |
| v7 read-only compatibility | Implemented |
| Binance sequenced adapter | Implemented with aggTrades recovery and depth resync |
| Provider certification CLI | Replay + fault + live soak sections |
| Outcome/detail console | Implemented |
| Analysis slot summary + HAC | Implemented when prerequisites met |
| Study/certification fixtures | Example files under `studies/` and `certifications/` |

## Original defect mapping

| Defect | v8 mitigation | Test coverage |
|--------|---------------|---------------|
| Four-row artifact presented as research-grade | `purpose: diagnostic_fixture`; primary rejects | `test_doctor_*`, primary CLI gate |
| Uncalibrated probabilities appear authoritative | Monitor shows raw when uncalibrated; artifact `calibration_status` | monitor detail view |
| Mixed feature/label windows | Explicit WINDOWS section; timing policies in manifest | runner + monitor tests |
| `flow` mislabel | Renamed to closing book imbalance / persistence baseline | monitor strings |
| Stale trades + fresh books combined | Separate trade/book ages in console | monitor snapshot |
| Tiny spreads round to 0.00 bp | Adaptive spread formatting (bp or ppm) | monitor formatters |
| Stopped runs retain open slots | `cancel_open_slots` on terminal exits | `test_cancel_open_slots_on_stop` |
| Integrity vs evidence conflated | Three-axis `evidence` block in status | `test_status_includes_evidence_axes` |
| Label resolution on any event | Watermark + settlement delay (primary) | `test_primary_timing_requires_settlement` |
| Diagnostic ratios look scored | OUTCOME labeled "not scored yet" | monitor outcome view |
| Documentation drift | SCHEMA_V8.md + updated RUNBOOK/ARCHITECTURE | manual review |

## Remaining operational gates

Primary live operation still requires a valid Binance certification produced by
`provider-certify` against live market data. Offline replay and fault sections
pass in CI; live soak must be executed by an operator before primary evidence
collection.

## Commands verified in CI

- Unit, store, runner, monitor, CLI, Binance provider, compatibility, and analysis tests
- `ruff check exchange_q tests`
- `compileall exchange_q tests`
