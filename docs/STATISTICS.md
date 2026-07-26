# Statistical Testing and Claim Thresholds

How Exchange-Q evaluates quantum vs classical predictions and what claims are supported.

Implementation: [`core/validation.py`](../core/validation.py), [`core/reality_check.py`](../core/reality_check.py).

---

## What is being tested

**Primary metric:** paired absolute error on continuous `buy_ratio`.

- Classical error: \|classical − resolved_actual\|
- Quantum error: \|prediction − resolved_actual\|
- **Win:** quantum error < classical error on the same step

**Hypothesis (block bootstrap / White's Reality Check):**

- H₀: the frozen quantum model does not reduce paired MAE
- Hₐ: the frozen quantum model reduces paired MAE

---

## Block bootstrap

Handles autocorrelation in time-series errors.

```
block_len = max(1, int(n^(1/3)) + 1)
n_blocks = ceil(n / block_len)
For each of 10000 bootstrap iterations:
    For each block: flip sign of (quantum_err - classical_err) with p=0.5
    Count resampled wins
p_value = (count_extreme + 1) / (n_bootstrap + 1)
```

Used by `comprehensive_report()` (pipeline shutdown) and optionally `analyze_live_results.py` (White's RC line).

---

## Bonferroni correction

```python
corrected_p = min(1.0, raw_p * N_HYPOTHESES_TOTAL)  # N=5 in config.py
```

**Honest caveat:** `N_HYPOTHESES_TOTAL = 5` reflects a historical kline-era convention. The repository does **not** contain an enumerated pre-registration list of five named hypotheses. Iterative research likely tested more than five comparisons. Treat Bonferroni p-values as **conservative**, not as proof of rigorous pre-registration.

Live schema v5 primary evaluation uses **`N_HYPOTHESES_LIVE = 1`** in [`core/config.py`](../core/config.py) when `live=True` is passed to `reality_check()` / `comprehensive_report()`. Production significance requires **n ≥ 720** resolved eligible predictions (`MIN_SIGNIFICANCE_N`).

---

## Sample size thresholds

| n (resolved eligible) | Reporting |
|----------------------|-----------|
| < 3 | Analyzer skips file |
| 3–29 | Exploratory only — win rate / improvement suppressed in pipeline |
| ≥ 30 | Exploratory summaries allowed; segmented output in analyzer |
| ≥ 720 | Target for production significance claims (hourly horizon, ~30 days) |

From [`docs/RUNBOOK.md`](./RUNBOOK.md) clean re-run checklist.

---

## Non-comparable targets

**Do not compare** these metrics directly:

| Path | Target | Typical MAE scale |
|------|--------|-------------------|
| Kline backtest (`backtest.py`) | Binary candle **direction** (0/1) | ~0.50 |
| Live pipeline | Continuous **buy_ratio** [0, 1] | Much smaller (e.g. 0.01–0.20) |
| Synthetic (`experiment.py`) | Next **buy_ratio** in simulator | ~0.12–0.17 |

Historical kline Born results (e.g. error 0.4801) are **deprecated** and used a different target.

---

## Segmented analysis

When n ≥ 30, `analyze_live_results.py` prints:

- `all_eligible` — all score-eligible resolved predictions
- `born_active_only` — subset where `fallback_reason == "none"`
- Per-fallback buckets: `flat_history`, `single_bucket`, `insufficient_history`, `destructive_interference`

**Label segmented comparisons as exploratory** unless explicitly pre-registered. Post-hoc slicing inflates effective hypothesis count beyond Bonferroni n=5.

---

## Financial metrics (secondary)

From error series in `comprehensive_report()`:

| Metric | Notes |
|--------|-------|
| Max drawdown | On error-based equity curve |
| Sharpe | Error-derived returns; `periods_per_year` from horizon |
| Profit factor | Win count / loss count on paired errors |

These are diagnostic; **win rate + Bonferroni p** are the primary significance path.

---

## Making a valid live claim

Minimum checklist:

1. Schema v5 JSON only; `--schema-version 5 --exclude-collector`
2. Report `run_id`, n resolved eligible, `born_active_rate`
3. Report raw and Bonferroni p from `comprehensive_report` or analyzer
4. n ≥ 720 resolved eligible for production significance
5. Require `resolved_label: forward_window` and complete local capture; do not mix archived v2–v4 corpus with v5 runs

---

## Related

- [SCHEMA_V5.md](./SCHEMA_V5.md) — label provenance and `score_eligible`
- [verification_report.md](../verification_report.md) — empirical verdict to date
- [core/research_05_results.md](../core/research_05_results.md) — archived kline-era numbers
