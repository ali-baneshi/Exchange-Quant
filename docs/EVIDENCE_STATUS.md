# Evidence Status — July 28, 2026

Exchange-Q currently has **no valid schema-v7 primary corpus**.

The repository now contains a schema-v7 implementation with:

- normalized signed-imbalance Born-inspired probabilities;
- frozen model artifacts;
- causal half-open windows;
- transactional forecast state;
- fixed non-overlapping scheduling;
- proper probabilistic scoring;
- fail-closed provider coverage.

Passing tests establish software invariants, not empirical superiority.

The bundled HTX adapter is diagnostic-only because it cannot prove uninterrupted
trade capture from the consumed stream. A primary run requires a provider adapter
with certifiable continuity and replay fixtures validating its semantics.

All schema-v6r1 and earlier results are historical diagnostics. They cannot be
combined with schema-v7 data or used to validate the new model.

No project result proves trading profitability, quantum advantage, or superiority
over strong frozen conventional baselines.
