# Lesson 06 — Parallel Runs

> **Historical lesson (schema v5/model v1).** Use the July 28, 2026 snapshot and
> current v6 references for commands, identities, and evidence limits.

| Date | 2026-07-27 |

---

## Two terminals

```bash
# Terminal 1 — production (do not stop casually)
./scripts/start_production_run.sh

# Terminal 2 — exploratory smoke
./scripts/start_exploratory_run.sh
```

| | Production | Exploratory |
|---|------------|-------------|
| horizon | 3600s | 60s |
| sample | 60s | 5s |
| max-resolved | 720 | 500 |
| claim tier | primary | smoke only |

---

## Isolation

- Separate `run_id`, SQLite, JSON per run
- Production lock: `.live_quantum_v5.lock` — exploratory not blocked
- `config_hash` includes schema, data_policy, label_policy

---

## Monitors

```bash
./scripts/monitor_live.sh
./scripts/monitor_exploratory.sh
```

Both select schema **v5** (exploratory also filters `horizon_s=60`).

---

## Do not claim

500 resolves at 60s ≠ 720 resolves at 3600s — different regime and microstructure.

**Next:** [07-analysis-and-claims.md](./07-analysis-and-claims.md)
