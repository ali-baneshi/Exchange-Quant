# Schema-v8 Statistical Protocol

## Estimand

The target is the future aggressor-buy probability over a fixed non-overlapping
window. Each label retains buy count, sell count, and total trades.

## Scores

- **Primary:** per-trade binomial negative log-likelihood.
- **Secondary:** Brier score, MAE of window buy ratio, calibration intercept,
  calibration slope, reliability, sharpness, and prediction distribution.

MAE alone is not a proper probability score and does not account for variable
information across windows.

## Comparators

The primary comparator and all secondary baselines must be frozen before primary
collection. Supported baseline concepts are:

- development-set prior;
- flow persistence;
- exponentially weighted flow;
- regularized conventional probabilistic regression.

The weakest observed comparator may not be selected after collection.

## Sample Size

There is no universal 720-observation rule. Use `exchange-q power` with a negative
expected paired loss difference, development-period loss variance, and dependence
estimate. Freeze the resulting target in the run manifest.

Primary collection uses a fixed stopping rule. Interim significance peeking and
performance-based early stopping are prohibited.

## Inference

Paired loss differences are analyzed with an intercept model using Newey-West HAC
covariance. Reports must include:

- compatible run and artifact identities;
- eligible and excluded counts with reasons;
- effect estimate and confidence interval;
- one-sided preregistered p-value;
- HAC lag choice and sensitivity analysis;
- circular moving-block bootstrap sensitivity with fixed seed and block length;
- proper scores and calibration diagnostics.

Multiple symbols, horizons, models, or post-hoc segments require explicit
multiplicity handling.

## Claim Boundary

Forecast accuracy does not establish execution quality or profitability. The
schema-v8 primary record intentionally excludes trading signals, fees, returns,
Sharpe-like ratios, drawdown, and profit factor.
