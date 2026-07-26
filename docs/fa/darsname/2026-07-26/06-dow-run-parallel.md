# درس ۶ — دو run موازی: production و exploratory

## مشخصات نسخه

| فیلد | مقدار |
|------|--------|
| تاریخ درس | 2026-07-26 |
| snapshot | [SYSTEM_SNAPSHOT-2026-07-26.md](../SYSTEM_SNAPSHOT-2026-07-26.md) |
| پیش‌نیاز | [L05](./05-pipeline-zende.md) |

---

## سوالات این درس

1. چرا دو run همزمان crash یا تداخل فایل نمی‌دهند؟
2. config_hash چیست و چرا analyzer را جدا نگه می‌دارد؟
3. exploratory چند resolve و چند ساعت طول می‌کشد؟
4. آیا نتیجه exploratory جای production را می‌گیرد؟
5. دستور دقیق ترمینال دوم چیست؟

---

## دو ترمینال — یک صرافی

```text
ترمینال 1 (production — دست نزنید):
  ./scripts/start_production_run.sh
  horizon=3600s, sample=60s, max-resolved=720
  log: live_quantum_v3.log

ترمینال 2 (exploratory — نمونه سریع):
  ./scripts/start_exploratory_run.sh
  horizon=60s, sample=5s, max-resolved=500
  log: live_exploratory.log
```

**قفل production** (`.live_quantum_v3.lock`) فقط روی script production است — exploratory **مسدود نمی‌شود**.

---

## جدول مقایسه

| | Production | Exploratory |
|---|------------|-------------|
| horizon | 3600s (1h) | 60s (1min) |
| sample | 60s | 5s |
| max-resolved | 720 | 500 |
| زمان تقریبی | ~30 روز | ~8–10 ساعت |
| سطح claim | primary (n≥720) | exploratory فقط |
| run_id | `btcusdt-quantum-EPOCH1` | `btcusdt-quantum-EPOCH2` |
| config_hash | متفاوت | متفاوت |

---

## چرا فایل‌ها قاطی نمی‌شوند؟

هر run:

```text
core/_live_results/btcusdt-quantum-{epoch}.sqlite3
core/_live_results/btcusdt-quantum-{epoch}.json
```

`config_hash` از horizon + sample + window + model_version ساخته می‌شود — aggregate analyzer فقط compatible ها را با هم جمع می‌زند.

---

## نگاه انتقادی

| ادعا | قضاوت |
|------|--------|
| «500 resolve در 60s = همان 720 resolve در 3600s» | **نه** — regime بازار و microstructure فرق دارد |
| «exploratory سریع‌تر = evidence اصلی» | **نه** — فقط diagnostics و debugging |
| «دو fetch همزمان Huobi مشکل دارد» | معمولاً OK؛ اگر NO DATA زیاد → sample exploratory را 10s کنید |

---

## monitor جدا

```bash
./scripts/monitor_live.sh          # production
./scripts/monitor_exploratory.sh   # exploratory
```

exploratory monitor فقط JSON با `horizon_s=60` و schema v4 را انتخاب می‌کند.

---

## resume exploratory

```bash
python3 core/pipeline_live_ensemble.py \
  --resume btcusdt-quantum-EPOCH \
  --horizon-s 60 --sample-interval-s 5 --window 15 --max-resolved 500
```

---

## پاسخ سوالات

**۱. تداخل?**  
run_id و sqlite/json جدا؛ lock فقط production script.

**۲. config_hash?**  
اثر انگشت تنظیمات — analyzer گروه‌بندی می‌کند.

**۳. exploratory?**  
500 resolve، ~8–10h بعد warmup.

**۴. جایگزین production?**  
خیر — horizon و claim tier فرق دارد.

**۵. ترمینال 2?**  
`./scripts/start_exploratory_run.sh`

---

**بعد:** [L07](./07-tahlil-va-adam-claim.md)
