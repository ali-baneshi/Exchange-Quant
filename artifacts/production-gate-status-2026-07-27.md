# Production Gate Status — 2026-07-27

> **Historical schema-v5/model-v1 gate record.** It describes the dated run shown
> below, not the current v6 runner or current evidence status.

## Active run (stopped 2026-07-27 ~13:59)

| Field | Value |
|---|---|
| Run ID | `btcusdt-quantum-1785124007` |
| Config | horizon=3600s, sample=60s, window=15, max-resolved=720 |
| Config hash | `953d5a659a9a0f356b4b49b0833335bd0c63a81fb025f26401252c432e6a11e2` |
| Log | `live_quantum_v3.log` |
| Started | 2026-07-27 07:16:47 |
| Stopped | 2026-07-27 13:59:49 (`user_stop` + network failure) |
| Eligible resolved | **4 / 720** |

**Action:** Restart production after network restored. See `./scripts/start_production_run.sh`.

Monitor: `./scripts/monitor_live.sh`

## Exploratory run (same session, stopped ~13:59)

| Field | Value |
|---|---|
| Run ID | `btcusdt-quantum-1785124079` |
| Config | horizon=60s, sample=5s, window=15, max-resolved=500 |
| Log | `live_exploratory.log` |
| Eligible resolved | **280** |
| Summary | [`artifacts/exploratory-run-1785124079-2026-07-27.md`](exploratory-run-1785124079-2026-07-27.md) |
| Lesson | [`docs/fa/darsname/2026-07-27/09-tahlil-run-1785124079.md`](../docs/fa/darsname/2026-07-27/09-tahlil-run-1785124079.md) |

Exploratory n=280: quantum MAE 0.3078 < classical 0.3183 (+3.30%); null 0.2824 still best. **Not for primary claims.**

## Daily monitor checklist

Run `./scripts/monitor_live.sh` and verify:

1. PID alive (`kill -0 $(cat live_quantum_v3.pid)`)
2. `resolved eligible` increasing (target 720)
3. `forward_window` / `label_capture_complete` > 90% once resolves begin
4. Excluded reasons logged (`short_forward_window`, `label_unavailable`) — no patch unless systemic failure
5. Cadence: no sustained empty batches or gap>10s spikes in log
6. **Null baseline** printed by `analyze_live_results.py` vs classical vs quantum

## Gate n≥30 (production MAE)

| Criterion | Status |
|---|---|
| n eligible (3600s) | **4 / 30** — NOT MET |
| Action | Restart collection after network fix |
| Model patch | **FORBIDDEN** until gate met |
| Null baseline comparison | Deferred (n too small) |

**Decision (2026-07-27, post-stop):** Gate not met. No model changes. Re-evaluate when n≥30 on production 3600s run.

## Gate n≥720 (primary inference)

| Criterion | Status |
|---|---|
| n eligible | **4 / 720** — NOT MET |
| Paired block test | Withheld per `docs/STATISTICS.md` |
| Primary claim | **FORBIDDEN** |

**Decision (2026-07-27, post-stop):** Gate not met. Continue production run until 720 eligible or manual stop.

## Born / saturation_gate defer

| Criterion | Exploratory ref (1785119130) | Exploratory (1785124079) | Production (1785124007) |
|---|---|---|---|
| n eligible | 50 | 280 | 4 |
| saturation_gate rate | 78% | 65.4% | N/A |
| born_active rate | 22% | 34.6% | N/A |
| born_active worse than classical | yes (MAE 0.273 vs 0.194) | no (q 0.3079 vs c 0.3318) | N/A |

**Decision:** Do **not** change `MAX_INTERFERENCE_BOOST` or Born formula until production n≥30 **and** gate>70% **and** born_active segment worse than classical on **3600s** corpus. Exploratory 60s improvement does not satisfy production gate. Revisit only with new `model_version` and fresh corpus.

## Reference baselines (exploratory 60s — not for primary claims)

| Run | Archive | n | c_err | q_err | null |
|---|---|---:|---:|---:|---:|
| `1785119130` | `_archive/exploratory-post-fix/` | 50 | 0.304 | 0.321 | 0.252 |
| `1785124079` | `_archive/exploratory-1785124079/` | 280 | 0.3183 | 0.3078 | 0.2824 |

Null MAE(0.5) beats both models on 60s in both runs — expected microstructure noise per `docs/STATISTICS.md`.

## Infra incident (2026-07-27 ~13:00)

Both production and exploratory runs lost network (`gaierror`, `Network is unreachable`). Not an API logic bug. Restart required after DNS/connectivity restored.
