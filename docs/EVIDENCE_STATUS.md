# Evidence Status — August 1, 2026

Exchange-Q now has a schema-v8 primary comparative corpus, but **no proven Born
superiority** on the pre-fix artifact.

## Latest powered soak (historical)

Run `btcusdt-primary-20260731-123411-03adade7` (target_eligible=360):

- wall-clock ≈ 8.5h, status=`failed` near the end (`provider_stalled` while the
  consumer queue was full — later diagnosed as consumer backpressure + silent
  trade drops)
- scoreable n=329 / 506 terminal slots
- integrity valid; capture marked certified at the time
- Born lost to all baselines on proper scores (flow_persistence best)
- calibration on that artifact was `uncalibrated` (14-row fit)

That run is comparative evidence that the previous primary artifact was not
competitive. It is **not** a clean training corpus for future fits because trade
queue drops were not recorded as continuity gaps in that revision.

## Current artifact gate (post-fix)

- development dataset rebuilt with ≥500 certified rows
- primary artifact must be `purpose=primary`, `calibration_status=fitted`,
  with ≥50 calibration rows
- `doctor --profile primary` (and six-hour runs) require a holdout gate where
  Born NLL beats `development_prior` and `flow_persistence`
- primary soaks are foreground-only; systemd units are forbidden by the runbook

Passing unit tests establish software invariants, not trading profitability.
