# Historical Audit Archive

**Status:** STALE — snapshot from **2026-07-20**.

Do **not** use these documents for the current API surface, module inventory, or operational runbooks.

Many issues listed here were fixed in subsequent hardening (2026-07-23 through 2026-07-26):

- Born rule removed from kline backtests
- `pipeline_live_ensemble.py --mode quantum` crash fixed
- Schema v3 live JSON with `run_id`
- Live δ remapped to [0, π/2]; destructive interference gate
- 66 unit tests (was 57 at time of audit)

**Use instead:**

- [docs/README.md](../docs/README.md) — documentation index
- [ARCHITECTURE.md](../ARCHITECTURE.md) — current design
- [docs/RUNBOOK.md](../docs/RUNBOOK.md) — live operations
- [verification_report.md](../verification_report.md) — empirical verdict

## Files in this archive

| File | Purpose |
|------|---------|
| [audit_notes_v1.md](./audit_notes_v1.md) | Module inventory (2026-07-20) |
| [critical_issues_pass1.md](./critical_issues_pass1.md) | Pass 1 critical issues |
| [empirical_gaps_pass2.md](./empirical_gaps_pass2.md) | Statistical gaps |
| [reproducibility_pass3.md](./reproducibility_pass3.md) | Reproducibility |
| [FINAL_HARDENING_PLAN.md](./FINAL_HARDENING_PLAN.md) | Hardening plan (mostly implemented) |
