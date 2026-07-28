# Evidence Status — July 28, 2026

## Current Conclusion

Exchange-Q has **no valid v6r1 primary corpus proving that the evaluated Born-policy
outperforms its recorded classical comparator**. It also has no evidence that
prediction accuracy translates into trading profitability.

The live runner is operational research infrastructure. That is not the same as a
successful empirical result.

## What Would Count as Primary Evidence

A report must use one frozen schema-v6r1 configuration and include at least 720
eligible resolved forecasts:

```text
status == "resolved"
resolved_label == "forward_window"
label_capture_complete == true
score_eligible == true
```

It must report model and classical MAE, `MAE(constant 0.5)`, the paired
mean-loss difference, the implemented paired moving-block bootstrap result, the
configuration identity, and exclusions. The primary comparison is about prediction
loss, not simulated returns, win rate, or a trade strategy.

## What Existing Material Means

| Material | Status |
|---|---|
| Schema v6r1 runs | Current format; require their own eligible corpus and analysis |
| Pre-hardening schema v6 runs | Historical diagnostics; excluded from v6r1 aggregation |
| Schema v5/v1 exploratory records | Historical diagnostics; not v6 primary evidence |
| Kline backtests | Classical binary-direction checks; not live `buy_ratio` evidence |
| Synthetic experiments | Formula and failure-mode diagnostics; not market evidence |
| Return, Sharpe-like, or profit-factor fields | Secondary simulation diagnostics; not proof of profitability |

## Terminology Correction

The implemented inference is an autocorrelation-aware paired moving-block bootstrap
of the model-versus-classical mean-loss difference. It is **not** White’s Reality
Check, which addresses a different data-snooping problem across a model universe.

## Related Records

- `STATISTICS.md` defines permitted reporting language and metrics.
- `SCHEMA_V6.md` defines record eligibility and provenance.
- `AUDIT_REPORT.md`, `verification_report.md`, `artifacts/`, and `code_audit_v1/`
  are preserved dated evidence. Their statements apply to their recorded dates and
  contracts unless a current-status banner says otherwise.
