# Lesson 03 — Live Data and buy_ratio

> **Historical lesson (schema v5/model v1).** Use the July 28, 2026 snapshot and
> current v6 references for commands, identities, and evidence limits.

| Date | 2026-07-27 | Code | `data_fetcher.py`, `live_store.py` |

---

## Fetch → observation

Each poll: ticker + depth + trades + klines → one **observation** with features and `quality_flags`.

---

## Feature vs label (v5)

| | Source | Window |
|---|--------|--------|
| **Feature buy_ratio** | Recent trades | `max(60, horizon_s)` seconds |
| **Label (primary)** | Captured trades | `[created_at_ms, target_at_ms]` |

Do not confuse full API trade pages (~80 min) with the 60s forward label.

---

## Resolve (forward_window)

At `target_at_ms`, the store filters locally captured trades for the forecast window:

- `resolved_label: forward_window`
- `label_capture_complete: true` required for scoring
- Minimum trades: `min_forward_trades(horizon_s)` — 15 for 3600s

---

## capture_saturated (v5 fix)

A full Huobi page (2000 trades) does **not** always mean incomplete capture. Saturation breaks coverage only when the oldest trade is **after** the previous capture frontier (real gap).

---

## Disqualifying flags

`crossed_market`, `no_trades`, `endpoint_skew`, `late_resolution`, `short_forward_window`, `label_unavailable`

---

## Critical note

On exploratory ref run `1785119130`, MAE(constant 0.5)=0.252 beat both models — expected 60s noise, not necessarily infra failure.

**Next:** [04-born-rule.md](./04-born-rule.md)
