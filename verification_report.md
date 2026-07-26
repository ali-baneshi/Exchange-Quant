# Verification Report

**Date:** 2026-07-20  
**Subject:** Does the Born rule, with all fixes applied, consistently beat classical baselines on large-scale, out-of-sample data?

---

## Executive Verdict

**No. The Born rule does NOT consistently beat classical baselines on large-scale, out-of-sample kline data.** All backtest p-values after Bonferroni correction are 1.0 (not significant). The one positive result (error 0.4801) is on a small held-out set (400 samples), uncorrected, and for a different prediction task (binary direction) than the live pipeline (continuous buy_ratio).

---

## Evidence

### On 2000-candle Huobi dataset (60min, held-out)

| Model | Error | Source |
|-------|-------|--------|
| Born rule (quantum) | **0.4801** | `experiment_ablation.py` on 400 held-out samples |
| vol_regime | 0.5112 | Same run |
| MA | 0.5122 | Same run |
| Improvement | +6.1% | |

**Caveats:**
- Only 400 held-out samples (insufficient for Bonferroni significance)
- p-value NOT reported in research_05_results.md
- Predicts **binary direction** (not buy_ratio)
- Not replicable on Gate.io 5000-candle dataset (where p=1.0)

### On 5000-candle Gate.io dataset (60min, held-out)

| Experiment | n | Classical | Quantum | Improvement | Bonf. p |
|-----------|---|-----------|---------|-------------|---------|
| Born rule backtest | 979 | 0.5031 | 0.5122 | **-1.8%** | 1.000 |
| Adaptive vs fixed | 984 | 0.5030 | 0.5022 | +0.16% | 1.000 |
| Ensemble vs quantum | 979 | 0.5016 | 0.5127 | **-2.2%** | 1.000 |

**All results are NOT statistically significant after Bonferroni correction.**

### On Synthetic Data

| Metric | Classical | Quantum | Improvement |
|--------|-----------|---------|-------------|
| Mean error | 0.1255 | 0.1549 | **-23.5%** |

**Born rule performs WORSE than classical on the synthetic benchmark.**

---

## Changes Applied (2026-07-20)

The following 9 code fixes from the hardening plan have been implemented:

| Fix | Description | Files Changed |
|-----|-------------|---------------|
| 1 | `_quantum_predict` crash bug | `pipeline_live_ensemble.py` |
| 2 | Remove Born rule normalization | `ensemble.py`, `ensemble_adaptive.py`, `backtest.py`, `backtest_ensemble.py` |
| 3 | Correct Sharpe periods_per_year | `backtest.py`, `backtest_ensemble.py` |
| 4 | Feature name aliases (buy_ratio/conviction) | `data_fetcher.py`, `backtest.py`, `backtest_ensemble.py`, `backtest_boost.py` |
| 5 | Unified delta via `compute_delta_from_klines` | `backtest_ensemble.py` |
| 6 | Block_len ceiling fix | `validation.py` |
| 7 | Random seed for reproducibility | `market_sim.py` |
| 8 | Relative-gap weight unification | `ensemble_adaptive.py` |

All 20 `.py` files compile cleanly after fixes. The live pipeline can now run in `--mode quantum` without crashing.

## After Applying All Fixes

### Predicted impact of Fix 2 (remove normalization):
- The Born rule prediction values will change numerically
- The sign and magnitude of the interference term remain the same
- The classical baseline is unchanged
- **No change in statistical significance** (normalization doesn't affect p-values)

### Predicted impact of Fix 3 (Sharpe period):
- Sharpe ratios for 15min and 1day will correct
- **No impact on win rate, p-value, or improvement %**

### Predicted impact of Fix 5 (unified delta):
- `backtest_ensemble.py` results may shift by ~1-2%
- **Unlikely to change statistical significance**

---

## The Only Remaining Path to Validation

The Born rule needs **live buy_ratio data with real order-book imbalance** to work properly. Historical klines lack imbalance, forcing a return-based delta that removes the Born rule's advantage.

**Required experiment (Run now — Fix 1 is applied):**
```bash
# Quantum-only mode for 720+ hourly steps (30+ days):
python3 core/pipeline_live_ensemble.py btcusdt 720 3600 quantum
```

Target: 720+ hourly observations, 50%+ win rate with Bonferroni p < 0.05.

**Current live data** (from `_live_results/state.json` and `results_ensemble.json`):
- Only 12 comparison steps collected (insufficient for any claim)
- Old 3-model ensemble format (not reproducible with current code)
- No quantum-mode data exists yet

---

## Final Conclusion

| Claim | Status |
|-------|--------|
| "Born rule beats classical on 60min held-out" | **Unsupported** (p not reported, task mismatch) |
| "Born rule beats all simple models" | **Borderline** (only on 2000 candles, 400 held-out) |
| "Born rule works on large-scale data" | **False** (p=1.0 on 5000 candles) |
| "Born rule works with imbalance-based delta" | **Untested** (no live collection at scale) |
| "Born rule is the correct approach" | **Plausible but unproven** |

**Bottom line:** To date, there is NO statistically significant evidence that the Born rule beats classical baselines at predicting market direction or buy_ratio. The project has promising theory, high-quality infrastructure, and a clear path forward — but the empirical case is not yet made.

---

## Repair follow-up (2026-07-26)

Engineering repairs from the comprehensive plan:

- Fixed kline cache/slice ordering (oldest→newest; newest-n window)
- Deprecated Born-on-klines callers; `validation_report.py` is classical + live status
- Unified Born predictions through `quantum_core.py`; live scripts share `live_protocol` forecast/resolve-later
- `pipeline_one_shot.py` state v2 with backup on migration
- Docs aligned with post-2026-07-23 decision
- Unit suite: 57 tests green (CI via `.github/workflows/test.yml`)
- Schema v3 live output with `run_id`; `analyze_live_results.py` parses v2 and v3
- Committed locally as `3c12386`; tagged `v0.9.0-stability`
- **Push note:** `git push origin main` failed (remote repository not found). Push manually when remote is available.

### Schema v3 smoke (2026-07-26)

Short ensemble smoke (`btcusdt_quantum_1785028289.json`):

| Check | Result |
|-------|--------|
| `schema_version` | 3 |
| `run_id` | `btcusdt-quantum-1785028289` |
| Forecast → resolve | OK (3 resolved, single-pending semantics) |
| `analyze_live_results.py` | Parses v3 without error |

### Long-horizon runs started (2026-07-26)

Background processes (monitor with `./scripts/monitor_live.sh`):

| Run | Command | Log |
|-----|---------|-----|
| 24h smoke | `pipeline_live_ensemble.py btcusdt 1440 3600 quantum 60 15` | `live_smoke_24h.log` |
| ~720 forecasts | `pipeline_live_ensemble.py btcusdt 43200 3600 quantum 60 15` | `live_quantum_v3.log` |

With single-pending semantics, one forecast resolves per hour after warmup. Use **43200** sample steps (not 720) for ~720 hourly resolves over ~30 days.

**Do not mix** pre-fix v2 corpus with schema v3 runs in aggregates. Update this section when the v3 run reaches ≥30 resolved eligible predictions.

### Live evaluation snapshot (legacy v2 aggregate)

Smoke: `pipeline_real` forecast/resolve-later works against Huobi (pending→resolved).

Full on-disk aggregate via `analyze_live_results.py` (all `_live_results/*.json` except `state.json`):

| Metric | Value |
|--------|-------|
| Resolved observations (aggregate) | 2866 |
| Weighted classical MAE | 0.1878 |
| Weighted quantum MAE | 0.3820 |
| Improvement | **-103.4%** (quantum worse) |
| Quantum win rate | 23.3% (669/2866) |
| White's Reality Check | NOT_SIGNIFICANT on inspected files |

**Honest reading:** Existing live quantum runs do **not** support a Born-rule win. A clean, single-protocol, long-horizon re-run (`pipeline_live_ensemble.py btcusdt 720 3600 quantum`) is still recommended before any new claim — but the current corpus already points negative, not pending.
