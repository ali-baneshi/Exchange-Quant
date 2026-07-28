# Lesson 08 — FAQ

> **Historical lesson (schema v5/model v1).** Use the July 28, 2026 snapshot and
> current v6 references for commands, identities, and evidence limits.

| Date | 2026-07-27 | Schema | v5 |

---

**Q: Is this a trading bot?**  
A: No — research evaluation only.

**Q: Feature vs label buy_ratio?**  
A: Feature uses recent lookback; label uses captured trades in `[created_at, target_at]`.

**Q: What is null baseline?**  
A: MAE(constant 0.5). If models lose to it, signal may be too weak — not always a bug.

**Q: How long for production?**  
A: ~30 days wall time for 720 hourly resolves.

**Q: Two runs at once?**  
A: Yes — production + exploratory in separate terminals.

**Q: Old run with n_steps=720?**  
A: Invalid — counted fetches, not eligible resolves.

**Q: saturation_gate everywhere?**  
A: Safeguard by design. No Born/gate patch until production n≥30.

**Q: Analyze command?**  
A: `--schema-version 5`

**Q: 50 exploratory resolves enough?**  
A: Diagnostics/exploratory only — not primary (need 720 production).

**Q: Which quality flags zero score?**  
A: `crossed_market`, `no_trades`, `endpoint_skew`, `late_resolution`, `short_forward_window`, `label_unavailable`

---

**Index:** [../README.md](../README.md)
