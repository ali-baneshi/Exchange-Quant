# Statistical Protocol and Claim Policy

This document defines what Exchange-Q may report from the frozen schema-v6r1 live
study. It does not establish that the model works.

## Primary Study

| Item | Frozen definition |
|---|---|
| Population | Schema-v6 BTC/USDT live forecasts with complete local trade labels |
| Model | `born_constructive_v2` gated composite policy |
| Comparator | Classical ensemble recorded in the same forecast |
| Target | Future trade-count `buy_ratio` in the inclusive `[created_at_ms, target_at_ms]` interval |
| Loss | Absolute error |
| Primary contrast | Paired loss difference: `prediction_error - classical_error` |
| Hypothesis | Quantum model reduces paired MAE relative to the classical comparator |
| Minimum primary sample | 720 eligible resolved forecasts |
| Multiple-testing factor | `N_HYPOTHESES_LIVE = 1` for the frozen primary comparison |

The run configuration, model identity, implementation revision, acquisition policy,
and label policy are included in each schema-v6r1 `experiment_manifest`. Changing any of them creates a different
experiment and requires a new corpus.

## Eligibility Before Statistics

The analyzer includes a v6 forecast only when all conditions hold:

```text
status == "resolved"
resolved_label == "forward_window"
label_capture_complete == true
score_eligible == true
```

Records with `label_unavailable`, partial capture, short windows, stale data, endpoint skew, or late resolution are diagnostics, not primary observations.

## Inference

`core/validation.py` uses an autocorrelation-aware paired moving-block bootstrap.
The block length is derived from the sample size; bootstrap iterations use a
deterministic seed for reproducible computation on the same error arrays. This is
not White’s Reality Check.

Report, at minimum:

1. `run_id`, `config_hash`, `model_version`, horizon, and sample interval;
2. number of resolved forecasts and number eligible for scoring;
3. mean classical MAE, model MAE, paired difference, confidence interval, and raw/corrected p-value;
4. the count and reasons for excluded observations;
5. execution-path/fallback rates and label-coverage diagnostics as secondary context.

## Reporting Tiers

These tiers govern **language allowed in reports**, not the analyzer’s technical minimum.

| Eligible resolved forecasts | Allowed language |
|---:|---|
| `< 30` | Pipeline/data-quality diagnostics only; no aggregate MAE interpretation |
| `30–719` | Exploratory MAE and descriptive comparisons; no significance claim |
| `≥ 720` | Primary paired inference for the frozen configuration |

**Analyzer floor:** `analyze_live_results.py` requires at least 3 resolved rows to print a summary (implementation minimum). That is not a reporting tier — treat n `< 30` as diagnostics-only per the table above.

**Null baseline:** Always report `MAE(constant 0.5)` alongside classical and model MAE. If both models exceed the null baseline, the signal may be too weak for the horizon — especially on exploratory 60s runs.

No early “win” claim is permitted because a temporary MAE advantage or win rate can be noise.

## Secondary Diagnostics

The following are useful but not primary proof:

- win rate (`prediction_error < classical_error`);
- **null baseline** `MAE(constant 0.5)`;
- `born_active_only` and fallback-based segments;
- bias, saturation, net-return simulation, Sharpe-like metrics, profit factor;
- exploratory 60-second runs;
- synthetic experiments;
- historical kline results.

Segmenting a corpus after collection increases the effective number of comparisons. Label such results exploratory unless they are separately preregistered and powered.

## Non-Comparable Metrics

| Path | Target | Do not compare directly with |
|---|---|---|
| `backtest.py` | Binary candle direction | Live `buy_ratio` MAE |
| `pipeline_live_ensemble.py` | Continuous future trade `buy_ratio` | Kline-direction MAE |
| `experiment.py` | Simulator target | Exchange-market performance |

## Historical Correction

`N_HYPOTHESES_TOTAL = 5` remains for historical/classical reporting conventions.
It is not evidence of a fully enumerated historical preregistration. Schema-v6
primary inference uses the explicitly frozen single live comparison instead.
