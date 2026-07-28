# درس ۶ — دو run موازی: production و exploratory

> **درس تاریخی (schema v5/model v1).** برای فرمان، نسخه و محدودیت ادعای فعلی از
> snapshot ۲۸ ژوئیه و مراجع v6 استفاده کنید.

## مشخصات نسخه

| فیلد | مقدار |
|------|--------|
| تاریخ درس | 2026-07-27 |
| snapshot | [SYSTEM_SNAPSHOT-2026-07-27.md](../SYSTEM_SNAPSHOT-2026-07-27.md) |
| پیش‌نیاز | L05 |

### تغییرات نسبت به 2026-07-26

- lock: `.live_quantum_v5.lock`
- monitor: schema **v5**
- run refs: prod `1785124007`, exploratory `1785119130`

---

## دو ترمینال

```bash
# ترمینال 1 — production (دست نزنید)
./scripts/start_production_run.sh

# ترمینال 2 — exploratory smoke
./scripts/start_exploratory_run.sh
```

| | Production | Exploratory |
|---|------------|-------------|
| horizon | 3600s | 60s |
| sample | 60s | 5s |
| max-resolved | 720 | 500 |
| claim | primary | smoke فقط |
| log | live_quantum_v3.log | live_exploratory.log |

**قفل:** `.live_quantum_v5.lock` — فقط production script؛ exploratory مسدود نمی‌شود.

---

## config_hash

شامل: symbol, mode, horizon, sample, window, schema_version, data_policy_version, label_policy, model_version.

---

## monitor

```bash
./scripts/monitor_live.sh          # production — schema v5
./scripts/monitor_exploratory.sh   # horizon_s=60 + schema v5
```

---

## نگاه انتقادی

- exploratory 60s **جایگزین** production نیست
- null baseline روی 60s اغلب بهتر از مدل — طبیعی
- قبل از production: `./scripts/stop_all_runs.sh`

---

**بعد:** [L07](./07-tahlil-va-adam-claim.md)
