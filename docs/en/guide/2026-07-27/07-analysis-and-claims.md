# Lesson 07 — Analysis and Claims

> **Historical lesson (schema v5/model v1).** Use the July 28, 2026 snapshot and
> current v6 references for commands, identities, and evidence limits.

| Date | 2026-07-27 | Code | `analyze_live_results.py`, `validation.py` |

---

## Reporting tiers

| n eligible | Allowed |
|---:|---|
| < 30 | Diagnostics only |
| 30–719 | Exploratory MAE — no significance claim |
| ≥ 720 | Primary paired block bootstrap |

Analyzer minimum: 3 resolved rows to print anything (technical floor, not a reporting tier).

---

## Analyzer

```bash
python3 core/analyze_live_results.py --schema-version 5
python3 core/analyze_live_results.py --schema-version 5 \
  core/_live_results/btcusdt-quantum-1785124007.json
```

Always read:

- **Null baseline: MAE(constant 0.5)=…**
- classical vs quantum vs null
- `born_active_rate`, `fallback_reason`
- `forward_window` / excluded reasons

Price sim (hit rate, avg_ret) is **diagnostic only**.

---

## Before any “win” claim

- [ ] schema v5, production horizon 3600s
- [ ] n ≥ 720 eligible, same `config_hash`
- [ ] null baseline reported
- [ ] exploratory 60s kept separate

Gate tracking: [../../../../artifacts/production-gate-status-2026-07-27.md](../../../../artifacts/production-gate-status-2026-07-27.md)

**Next:** [08-faq.md](./08-faq.md)
