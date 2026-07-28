# درس ۷ — تحلیل نتایج و claimهای مجاز

> **درس تاریخی (schema v5/model v1).** برای فرمان، نسخه و محدودیت ادعای فعلی از
> snapshot ۲۸ ژوئیه و مراجع v6 استفاده کنید.

## مشخصات نسخه

| فیلد | مقدار |
|------|--------|
| تاریخ درس | 2026-07-27 |
| snapshot | [SYSTEM_SNAPSHOT-2026-07-27.md](../SYSTEM_SNAPSHOT-2026-07-27.md) |
| schema | v5 |
| کد | `core/analyze_live_results.py`, `core/validation.py` |

### تغییرات نسبت به 2026-07-26

- `--schema-version 5`
- **Null baseline:** `MAE(constant 0.5)` در خروجی
- price sim فقط diagnostic
- gate doc: `artifacts/production-gate-status-2026-07-27.md`

---

## سطوح گزارش

| n eligible | مجاز | ممنوع |
|---:|---|---|
| < 30 | diagnostics | aggregate MAE claim |
| 30–719 | exploratory MAE + null baseline | significance |
| ≥ 720 | primary paired inference | — |

---

## analyzer

```bash
python3 core/analyze_live_results.py --schema-version 5

python3 core/analyze_live_results.py --schema-version 5 \
  core/_live_results/btcusdt-quantum-1785124007.json
```

خروجی مهم:

- `Null baseline: MAE(constant 0.5)=...`
- classical vs quantum vs null
- `born_active_rate`, `fallback_reason`
- `forward_window` rate
- Paired test (n≥720 only)

---

## checklist قبل از claim

- [ ] schema v5، `resolved_label=forward_window`
- [ ] n ≥ 720 eligible (production 3600s)
- [ ] null baseline گزارش شده
- [ ] exploratory 60s **جدا** از production claim
- [ ] runهای v3/v4/n_steps قدیمی exclude

---

## مثال exploratory ref (نه primary)

Run `1785119130`: 50 eligible، null 0.252 < classical 0.304 < quantum 0.321 — **claim ممنوع** (exploratory 60s).

---

**بعد:** [L08](./08-soal-javab-koli.md)  
**case study:** [L09 — run 1785124079](./09-tahlil-run-1785124079.md)
