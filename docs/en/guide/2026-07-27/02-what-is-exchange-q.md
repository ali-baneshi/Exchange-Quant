# Lesson 02 — What Exchange-Q Is (and Is Not)

> **Historical lesson (schema v5/model v1).** Use the July 28, 2026 snapshot and
> current v6 references for commands, identities, and evidence limits.

| Date | 2026-07-27 | Schema | v5 |

---

## What it is

A **research evaluator**: fetch live BTC/USDT data → forecast future buy_ratio → resolve with captured trades → compare Born vs classical.

---

## What it is not

- Not a live trading bot (no authenticated orders)
- Not proof the model works (that requires n≥720 primary study)
- Not comparable: kline direction backtest vs live buy_ratio MAE

---

## Valid quantum path

`pipeline_live_ensemble.py` → schema v5 JSON → `analyze_live_results.py --schema-version 5`

Production: 720 eligible resolves, horizon 3600s, `born_constructive_v1`.

Baseline artifact: [../../../../artifacts/baseline-2026-07-26.md](../../../../artifacts/baseline-2026-07-26.md)

---

## Invalid for claims

- Old runs counting fetches as `n_steps=720`
- Mixing v2/v3/v4 corpus with v5
- Exploratory 60s as primary evidence

**Next:** [03-live-data-buy-ratio.md](./03-live-data-buy-ratio.md)
