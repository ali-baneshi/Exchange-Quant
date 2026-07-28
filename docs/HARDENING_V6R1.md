# v6r1 Reliability Hardening Record — July 28, 2026

## Baseline

The hardening pass began with no active live process, two incomplete pre-hardening
v6 runs, six eligible observations, and 97 passing tests. Passing tests described
the existing behavior but did not establish protocol validity or model performance.

## Implemented

- Added `implementation_revision = "v6r1"` and
  `acquisition_policy_version = 1` to run state, manifests, and configuration hashes.
- Added structured acquisition outcomes with per-endpoint success, error, latency,
  retries, raw trades, and feature state.
- Preserved successfully fetched trades when another endpoint prevents feature
  construction.
- Added conservative capture failure reasons, including saturated-page gaps and
  missing boundary coverage.
- Added periodic trade pruning, WAL checkpoints, database-size observability, and
  less frequent full JSON checkpoints.
- Added exception-safe failed-state persistence, immediate lock/PID cleanup, and
  distinct `SIGINT`/`SIGTERM` exit codes.
- Made v6r1 analysis fail closed on identity, explicit eligibility, finite bounds,
  timing, window alignment, and recomputed error consistency.
- Replaced user-visible White’s Reality Check naming with paired moving-block
  mean-loss inference while retaining a deprecated compatibility wrapper.
- Unified production/exploratory monitoring around read-only SQLite state and exact
  profile selection.
- Restricted shutdown to pipeline processes owned by this repository.

## Verification

The deterministic suite contains 104 passing tests. New coverage includes partial
endpoint failure, retained raw trades, saturated start coverage, forged persisted
errors, pre-hardening v6 rejection, failed-run cleanup, signal exit behavior, WAL
checkpointing, and database-size reporting.

## Deferred to v7

v6r1 does not change the Born formula, signed-imbalance treatment, bucket ordering,
fallback semantics, saturation thresholds, forecast target, or overlapping-pending
policy. Those changes require preregistration, a new version identity, and a fresh
corpus.
