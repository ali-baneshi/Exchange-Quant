# Lesson 04 — Born Rule (Simple + Limits)

> **Historical lesson (schema v5/model v1).** Use the July 28, 2026 snapshot and
> current v6 references for commands, identities, and evidence limits.

| Date | 2026-07-27 | `model_version` | `born_constructive_v1` |

---

## Idea

Split history into high/low buckets on buy_ratio (or imbalance), apply Born-style interference with phase δ from order book.

---

## fallback_reason

| Value | Meaning |
|-------|---------|
| `none` | Born active |
| `destructive_interference` | Revert to `classical_part` |
| `saturation_gate` | Constructive overshoot → `classical_part` (safeguard) |
| `flat_history`, `insufficient_history`, … | Classical fallback |

δ live is in **[0, π/2]** — constructive-biased frozen protocol.

---

## saturation_gate

Triggers when prediction ≥ 0.99 or overshoot > `MAX_INTERFERENCE_BOOST` (0.15). ~78% on exploratory ref — **do not patch** until production n≥30 per gate policy.

**Next:** [05-live-pipeline.md](./05-live-pipeline.md)
