# Statistical Protocol and Claim Policy

This document defines what Exchange-Q may report from the frozen schema-v5 live study. It does not establish that the model works.

## Primary Study

| Item | Frozen definition |
|---|---|
| Population | Schema-v5 BTC/USDT live forecasts with complete local trade labels |
| Model | `born_constructive_v1` |
| Comparator | Classical ensemble recorded in the same forecast |
| Target | Future trade-count `buy_ratio` in `[created_at_ms, target_at_ms]` |
| Loss | Absolute error |
| Primary contrast | Paired loss difference: `prediction_error - classical_error` |
| Hypothesis | Quantum model reduces paired MAE relative to the classical comparator |
| Minimum primary sample | 720 eligible resolved forecasts |
| Multiple-testing factor | `N_HYPOTHESES_LIVE = 1` for the frozen primary comparison |

The run configuration, model identity, and label policy are included in each schema-v5 `experiment_manifest`. Changing any of them creates a different experiment and requires a new corpus.

## Eligibility Before Statistics

The analyzer includes a v5 forecast only when all conditions hold:

```text
status == "resolved"
resolved_label == "forward_window"
label_capture_complete == true
score_eligible == true
```

Records with `label_unavailable`, partial capture, short windows, stale data, endpoint skew, or late resolution are diagnostics, not primary observations.

## Inference

`core/validation.py` uses an autocorrelation-aware paired block bootstrap. The block length is derived from the sample size; bootstrap iterations use a deterministic seed for reproducible computation on the same error arrays.

Report, at minimum:

1. `run_id`, `config_hash`, `model_version`, horizon, and sample interval;
2. number of resolved forecasts and number eligible for scoring;
3. mean classical MAE, model MAE, paired difference, confidence interval, and raw/corrected p-value;
4. the count and reasons for excluded observations;
5. `born_active_rate` and label-coverage diagnostics as secondary context.

## Reporting Tiers

| Eligible resolved forecasts | Allowed language |
|---:|---|
| `< 3` | Diagnostics only; no aggregate interpretation |
| `3–29` | Inspect data quality and pipeline behavior only |
| `30–719` | Exploratory MAE and descriptive comparisons; no significance claim |
| `≥ 720` | Primary paired inference for the frozen configuration |

No early “win” claim is permitted because a temporary MAE advantage or win rate can be noise.

## Secondary Diagnostics

The following are useful but not primary proof:

- win rate (`prediction_error < classical_error`);
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

`N_HYPOTHESES_TOTAL = 5` remains for historical/classical reporting conventions. It is not evidence of a fully enumerated historical preregistration. Schema-v5 primary inference uses the explicitly frozen single live comparison instead.
