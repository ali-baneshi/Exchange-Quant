# System Snapshot — 2026-07-27

> **Historical snapshot.** This schema-v5/model-v1 record is retained for context.
> Use [SYSTEM_SNAPSHOT-2026-07-28.md](./SYSTEM_SNAPSHOT-2026-07-28.md) and the
> current v6 operational references for present behavior.

**Date:** 2026-07-27 | **Tests:** 94 passed | **Schema:** v5

Reference for all lessons in `2026-07-27/`. Persian mirror: [../../fa/darsname/SYSTEM_SNAPSHOT-2026-07-27.md](../../fa/darsname/SYSTEM_SNAPSHOT-2026-07-27.md)

---

## One-line goal

Research platform comparing Born-rule predictions to classical baseline on **live buy_ratio** — not a trading bot.

---

## Valid paths

| Path | Claim tier |
|------|------------|
| Production 3600s, n=720 | Primary |
| Exploratory 60s | Infra smoke only |
| Kline backtest | Classical — not comparable to live |

---

## Schema v5 essentials

| Item | Value |
|------|-------|
| `model_version` | `born_constructive_v1` |
| `data_policy_version` | 3 — feature lookback `max(60, horizon_s)` |
| `label_policy` | `captured_trade_window_v1` |
| Primary label | `resolved_label: forward_window` |
| Lock | `.live_quantum_v5.lock` |
| Archive | `_archive/pre_v5/` |

---

## Reference runs

| Run ID | Role |
|--------|------|
| `btcusdt-quantum-1785124007` | Active production |
| `btcusdt-quantum-1785119130` | Exploratory ref (archived) |

Artifacts: [../../../artifacts/baseline-2026-07-26.md](../../../artifacts/baseline-2026-07-26.md), [../../../artifacts/production-gate-status-2026-07-27.md](../../../artifacts/production-gate-status-2026-07-27.md)

---

## Commands

```bash
./scripts/stop_all_runs.sh
make test
./scripts/start_production_run.sh
./scripts/monitor_live.sh
python3 core/analyze_live_results.py --schema-version 5
```

---

## Reporting tiers

| n eligible | Allowed |
|---:|---|
| < 30 | Diagnostics only |
| 30–719 | Exploratory MAE + null baseline |
| ≥ 720 | Primary paired inference |

**Null baseline:** MAE(constant 0.5) — on 60s ref both models lost to 0.252 (expected noise).

---

## Known limits

1. Old v3/v4 runs and `n_steps` API invalid for claims
2. `saturation_gate` ~78% on exploratory — no Born patch until production n≥30
3. Price sim metrics are diagnostic only
