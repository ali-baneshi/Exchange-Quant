# درس ۷ — تحلیل نتایج و claimهای مجاز

## مشخصات نسخه

| فیلد | مقدار |
|------|--------|
| تاریخ درس | 2026-07-26 |
| snapshot | [SYSTEM_SNAPSHOT-2026-07-26.md](../SYSTEM_SNAPSHOT-2026-07-26.md) |
| کد | `core/analyze_live_results.py`, `core/validation.py` |
| پیش‌نیاز | [L05](./05-pipeline-zende.md) |

---

## سوالات این درس

1. سه سطح گزارش (diagnostics / exploratory / primary) دقیقاً چیست؟
2. paired block bootstrap چه چیزی را test می‌کند؟
3. win rate 52% یعنی چه — چرا هنوز «ثابت نشده»؟
4. `--schema-version 4` چرا لازم است؟
5. چه زمانی می‌توان گفت «Born بهتر از classical است»؟

---

## سطوح گزارش (snapshot 2026-07-26)

| n (resolved eligible) | مجاز بگویید | ممنوع بگویید |
|------------------------|-------------|--------------|
| < 30 | «هنوز داده کافی نیست» | win rate، improvement |
| 30–719 | «exploratory: میانگین خطا …» | significant، production-ready |
| ≥ 720 | primary + paired test + Bonferroni live | — (با فرض quality OK) |

`MIN_SIGNIFICANCE_N = 720` در config.

---

## آمار — ساده

**متریک اصلی:** `error = |prediction − actual|`

**paired test:** تفاوت میانگین خطا (quantum − classical) با block bootstrap (خودهمبستگی زمانی).

**Bonferroni live:** `N_HYPOTHESES_LIVE = 1` — یک hypothesis pre-registered برای live.

**حذف شده از claim:** Sharpe/drawdown از error — `financial_metrics_valid: false`.

---

## analyzer

```bash
# همه v4 — گروه‌بندی بر config_hash
python3 core/analyze_live_results.py --schema-version 4

# یک run مشخص
python3 core/analyze_live_results.py --schema-version 4 \
  core/_live_results/btcusdt-quantum-EPOCH.json
```

خروجی مهم:

- `born_active_rate`
- `fallback_reason` breakdown
- `score_eligible` count
- Paired block test (فقط n≥720)

---

## نگاه انتقادی — checklist قبل از claim

- [ ] schema v4 و run_id documented
- [ ] n ≥ 720 eligible (production horizon)
- [ ] run قدیمی v3 با n_steps **exclude**
- [ ] quality failure rate < ~5% (operational)
- [ ] config_hash یکسان در تمام runهای aggregate
- [ ] exploratory (60s) **جدا** از production claim

---

## کار عملی

روی run فعلی (اگر n=0):

```bash
python3 core/analyze_live_results.py --schema-version 4 \
  core/_live_results/btcusdt-quantum-1785040266.json
```

باید ببینید: «Only 0 resolved — need at least 3» → **طبیعی** تا اولین resolve.

---

## پاسخ سوالات

**۱. سه سطح?**  
<30 خاموش؛ 30–719 exploratory؛ ≥720 primary significance.

**۲. bootstrap?**  
H0: quantum خطای میانگین ≥ classical؛ block برای autocorrelation.

**۳. win 52%?**  
فقط اکثریت گام‌ها؛ بدون n=720 و test = noise.

**۴. schema 4?**  
فیلتر v2/v3 قدیمی از ادعاهای جدید.

**۵. «Born بهتر»?**  
n≥720 eligible + test معنادار + quality + همان config production — نه exploratory.

---

**بعد:** [L08](./08-soal-javab-koli.md)
