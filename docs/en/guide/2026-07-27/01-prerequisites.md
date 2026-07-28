# Lesson 01 — Prerequisites

> **Historical lesson (schema v5/model v1).** Use the July 28, 2026 snapshot and
> current v6 references for commands, identities, and evidence limits.

| Date | 2026-07-27 | Snapshot | [SYSTEM_SNAPSHOT-2026-07-27.md](../SYSTEM_SNAPSHOT-2026-07-27.md) |

---

## Markets (minimal)

- **Order book:** bids and asks
- **Trade:** executed buy/sell
- **buy_ratio:** buy trades / total trades in a window (0–1)

---

## Time horizons

- **horizon_s:** wait time until the future label window ends
- **sample_interval_s:** how often Huobi is polled
- **window:** observations needed before first forecast (15)

With v5 **data_policy 3**, live feature buy_ratio uses only the most recent `max(60, horizon_s)` seconds of trades — aligned with forecast scale.

---

## Statistics (minimal)

- **MAE:** mean absolute error `|prediction − actual|`
- **Paired test:** quantum vs classical on the same forecasts
- **Null baseline:** MAE if you always predict 0.5

**Next:** [02-what-is-exchange-q.md](./02-what-is-exchange-q.md)
