# Exchange-Q Technical Audit

> **Historical audit record — superseded for current operation.** This audit
> evaluated the schema-v5/model-v1 baseline. For schema v8 see
> `AUDIT_REPORT_V8.md`, `docs/SCHEMA_V8.md`, and `docs/RUNBOOK.md`.

**Audit date:** July 28, 2026  
**Baseline:** Current working tree, including uncommitted files and active artifacts  
**Scope:** Full repository, with emphasis on the canonical schema-v5 live evaluator  
**Method:** Source inspection, documentation reconciliation, test execution, artifact inspection, and targeted adversarial probes

## Executive Summary

The project has a clear research boundary, a substantially improved durable live pipeline, and a passing automated suite (`94 passed`). The strongest positive conclusion is infrastructural: the system can persist forecasts, resume runs, and distinguish locally captured forward labels from snapshot fallbacks.

The primary live evidence path is not yet operationally trustworthy. The most important defect is in `LiveRunStore.trade_window`: normal saturated trade polling is treated as a capture hole because the code compares a later page's oldest trade timestamp with the previous batch's **local capture time**, rather than the previous trade frontier. A targeted probe reproduced `capture_complete=False` under ordinary 60-second polling with overlapping saturated pages. Existing v5 files show the same pattern: several runs have most or all resolved forecasts labeled `label_unavailable`.

The live evaluator also uses local wall-clock timestamps as the forecast interval while labels use exchange trade timestamps, without measuring or correcting local/exchange clock offset. This can shift the target window and makes “exact future interval” weaker than the documentation claims.

No evidence of exchange credentials, order execution, or direct trading capability was found. The main risks are research-validity, data-quality, operational recovery, and misleading statistical interpretation rather than credential compromise.

## Runtime Architecture and Data Flow

### Canonical path

1. `pipeline_live_ensemble.py` calls `HuobiData.fetch_features_with_trades()`.
2. `data_fetcher.py` concurrently fetches ticker, depth, recent trades, and one-minute klines.
3. `compute_live_features()` derives the recent-trade `buy_ratio`, volume ratio, imbalance, volatility, spread, timestamps, and quality flags.
4. The runner creates an observation and persists the raw trade page and observation into SQLite.
5. After warmup, it creates one pending forecast using:
   - `classical_ensemble()` from `baselines.py`;
   - `born_rule_predict()` through `ensemble.py`/`quantum_core.py`;
   - optional adaptive ensemble weights.
6. At or after `target_at_ms`, it queries locally persisted trades for the forecast interval.
7. It computes a forward-window label when coverage and minimum-trade checks pass; otherwise it stores a diagnostic snapshot label as `label_unavailable`.
8. Eligible resolved records update ensemble performance, are exported to schema-v5 JSON, and are later filtered by `analyze_live_results.py`.

### State model

The intended state transitions are coherent:

```text
accepted observation → warmup → pending forecast → due → resolved
                                              ↘ incomplete label / ineligible
```

The implementation enforces one pending forecast per database by checking all forecast records, but it does not enforce this invariant across two processes concurrently accessing the same run.

## Findings

### P0 — Saturated trade pages are falsely classified as capture holes

**Evidence:** `core/live_store.py:232-244`

For each saturated batch, the code computes:

```python
frontier_ms = batches[index - 1][0]
if oldest_trade_ms > frontier_ms:
    saturated_hole = True
```

`batches[index - 1][0]` is the previous batch's `captured_at_ms` (local wall time), not its oldest or newest exchange trade timestamp. With normal polling, a later page's oldest trade is expected to be newer than the previous local capture time when the exchange is liquid. The code therefore marks an otherwise continuously captured sequence as incomplete.

**Reproduction:** Three saturated batches at local times 3,600,000, 3,660,000, and 3,720,000 ms, each containing overlapping 2,000-trade pages, produced:

```text
capture_batch_count = 3
capture_max_gap_ms = 60000
capture_saturated = True
capture_complete = False
```

**Observed corpus support:** Current v5 files include:

- `btcusdt-quantum-1785067586.json`: 158 resolved, 0 eligible;
- `btcusdt-quantum-1785114264.json`: 18 resolved, 0 eligible;
- `btcusdt-quantum-1785153254.json`: 170 resolved, 6 eligible;
- production run `btcusdt-quantum-1785124007.json`: 5 resolved, 4 eligible, with incomplete capture on one record.

**Impact:** The canonical evaluator can silently discard valid labels, extend the study, bias eligibility toward low-volume periods, and make the advertised 720-resolution protocol infeasible or nonrepresentative.

**Confidence:** Confirmed.

**Remediation:** Track and compare exchange-time frontiers, such as previous `newest_trade_ms`/`oldest_trade_ms`, and distinguish:

- page saturation;
- overlap with the previous exchange-time page;
- actual uncovered time intervals;
- first-batch behavior, where no prior frontier exists.

Add tests using realistic consecutive saturated pages with current timestamps.

### P0 — Forecast target windows are not aligned to an exchange clock

**Evidence:** `core/pipeline_live_ensemble.py:76-85`, `:101-115`, `:452-480`

Forecast creation and target time use `obs["wall_time_ms"]`, derived from the local machine clock. Forward labels use exchange trade timestamps from Huobi. The code records ticker/depth timestamps but never measures local-versus-exchange offset, validates system clock accuracy, or anchors `created_at_ms` to an exchange timestamp.

**Impact:**

- Clock drift can shift both interval boundaries.
- A forecast may include trades that occurred before the actual forecast observation or omit trades that occurred immediately after it.
- “Exact future interval” is only exact relative to the local clock, not necessarily the exchange timeline.
- Coverage checks can pass while the label is temporally misaligned.

**Confidence:** Confirmed design gap; production impact depends on clock offset.

**Remediation:** Establish an explicit time policy: sample an exchange timestamp, record local/exchange offset, reject excessive offset or skew, and define the label interval in one clock domain. Use half-open intervals (`[start, end)`) to avoid boundary double counting.

### P1 — Stale trades are not detected by age

**Evidence:** `core/data_fetcher.py:202-218`, `:301-325`

`_trades_in_lookback()` anchors the feature window to the newest returned trade timestamp. `compute_live_features()` flags `stale_trades` only when timestamps are highly duplicated:

```python
unique_trade_ts <= max(1, total_trades // 5)
```

There is no check that the newest trade is close to the ticker timestamp, local collection time, or current time. A delayed but internally diverse trade page can be treated as fresh. The same issue affects label capture because page contents are accepted based on timestamp ranges and batch metadata without an explicit exchange-time freshness check.

**Impact:** Delayed API data can be used as current features, producing stale predictions and potentially misaligned labels while avoiding the intended quality gates.

**Confidence:** Confirmed design gap.

**Remediation:** Validate:

- newest trade timestamp versus ticker timestamp;
- newest trade timestamp versus local collection time after applying measured offset;
- monotonicity and reasonable future bounds;
- maximum age for each endpoint.

Record explicit `stale_trades`/`stale_ticker`/`future_timestamp` flags and decide whether each disqualifies scoring.

### P1 — Important quality flags do not disqualify scoring

**Evidence:** `core/config.py:59-67`, `core/data_fetcher.py:310-326`

`empty_depth`, `stale_trades`, and `missing_timestamp` can be recorded on observations, but they are absent from `DISQUALIFYING_QUALITY_FLAGS`. Consequently, a forecast with stale or empty market context can remain eligible if it has a complete forward label and no other listed flag.

The operational documentation describes these flags as data-quality concerns, while the schema contract presents primary eligibility as requiring valid quality. The implementation does not consistently enforce that interpretation.

**Confidence:** Confirmed.

**Remediation:** Define a versioned quality policy distinguishing diagnostic-only flags from score-disqualifying flags. Validate the policy at resolution and in the analyzer rather than relying only on a string set.

### P1 — Analyzer trusts self-declared schema-v5 metadata too much

**Evidence:** `core/analyze_live_results.py:98-112`, `:368-377`

For v5 analysis, the analyzer checks `schema_version`, `resolved_label`, `label_capture_complete`, and `score_eligible`, but it does not validate the required:

- `model_version == "born_constructive_v1"`;
- `data_policy_version`;
- `experiment_manifest.label_policy`;
- `experiment_manifest.primary_metric`;
- symbol and horizon against the frozen production configuration;
- consistency between `config_hash` and manifest fields.

A hand-edited or malformed v5 document can therefore pass the primary filter if its row-level eligibility fields look valid.

The analyzer also omits a full count and reason breakdown for excluded resolved records. It reports only the filtered eligible population and limited flags among eligible rows, despite the documentation requiring excluded-label reasons.

**Impact:** Invalid or mixed experiments can be analyzed as primary evidence, and operators lack the information needed to diagnose why observations were excluded.

**Confidence:** Confirmed.

**Remediation:** Validate the complete manifest and row invariants before analysis; fail closed on missing/mismatched fields; report total resolved, eligible, excluded, and exclusion-reason counts.

### P1 — “White’s Reality Check” is statistically mislabeled

**Evidence:** `core/reality_check.py:13-21`, `:32-44`

The module claims to test quantum win rate:

```text
H0: quantum_win_rate <= 0.5
```

but delegates to `paired_moving_block_test()`, which tests the mean loss difference (`model_error - classical_error`). It is not White’s Reality Check over a model/data-snooping universe, nor a block-bootstrap test of win rate.

**Impact:** Reports and historical artifacts can overstate what the procedure tests. The mean-error test may be valid as a paired comparison, but it does not support the function’s stated hypothesis or name.

**Confidence:** Confirmed.

**Remediation:** Rename the helper and documentation to paired moving-block mean-loss inference, or implement and document a genuine multiple-model reality-check procedure. Do not report win-rate hypotheses from a mean-loss p-value.

### P1 — Concurrent resume can violate one-pending semantics

**Evidence:** `core/pipeline_live_ensemble.py:368-405`, `:417-557`, `scripts/start_production_run.sh:11-29`

The production shell wrapper holds `.live_quantum_v5.lock`, but direct CLI launches and resume commands do not acquire a per-run lock. Two processes can open the same SQLite database, both load the same state, both see no pending forecast, and both create forecasts or update the same forecast state.

SQLite serialization prevents some corruption, but it does not provide application-level compare-and-swap semantics for forecast creation or ensemble updates.

**Impact:** Duplicate forecasts, conflicting ensemble performance, non-deterministic JSON exports, and broken lifecycle invariants.

**Confidence:** High.

**Remediation:** Acquire an exclusive per-run lock inside the runner, or implement a transactional run lease and unique pending-forecast constraint. Test simultaneous resume and duplicate forecast creation.

### P1 — JSON export cost grows quadratically over a long run

**Evidence:** `core/pipeline_live_ensemble.py:222-253`, `:509-520`, `:549-571`; `core/live_store.py:268-284`

Every forecast creation and resolution calls `store.export_document()`, which reads and JSON-decodes every observation and forecast, then rewrites the complete JSON document. A 30-day run with thousands of observations repeatedly serializes an ever-growing document.

**Impact:** Increasing CPU, disk I/O, latency, and crash windows; potential missed sampling deadlines; unnecessary duplication because SQLite is already authoritative.

**Confidence:** Confirmed design issue.

**Remediation:** Keep SQLite authoritative, export incrementally or on a bounded cadence, use a streaming/manifest export, and measure export latency as an operational metric.

### P1 — API failure handling hides partial acquisition and timing gaps

**Evidence:** `core/data_fetcher.py:44-79`, `:154-176`, `:187-199`

Endpoint failures are converted into empty/default values. `fetch_features_with_trades()` retries complete endpoint batches, but failed attempts are not persisted as capture gaps. The runner only sees `None` or a final feature result. HTTP errors retry without backoff, while malformed payloads and endpoint-specific validity are not represented in structured state.

**Impact:** Operators cannot distinguish API outage, malformed response, stale response, empty market, and feature-validation failure. Coverage gaps depend on timing side effects rather than explicit acquisition records.

**Confidence:** Confirmed.

**Remediation:** Persist acquisition attempt metadata, endpoint status, request/response timestamps, retry count, and failure class. Apply bounded exponential backoff with jitter and expose counters for each failure mode.

### P2 — Feature construction validates too little numeric/domain input

**Evidence:** `core/data_fetcher.py:248-300`

Ticker fields and bid/ask are checked for finite numeric values, but there is no equivalent validation for depth quantities, trade prices/amounts/timestamps, `close > 0`, `high >= low`, nonnegative liquidity, or valid trade directions. `price = ticker["close"] or 1` silently replaces a zero close with `1`.

**Impact:** Malformed exchange data can produce misleading bounded features rather than a rejected observation. Silent substitution is particularly dangerous in a research evaluator because it changes the target population.

**Confidence:** High.

**Remediation:** Reject invalid domain values explicitly, preserve the failure reason, and never replace a missing/zero market price with a plausible numeric fallback.

### P2 — Feature lookback and labels can be based on different temporal populations

**Evidence:** `core/data_fetcher.py:202-218`, `:278-347`; `core/pipeline_live_ensemble.py:436-446`

Feature `buy_ratio` is computed from the most recent `max(60, horizon)` seconds relative to the newest returned trade. Forward labels use all locally captured trades in `[created_at_ms, target_at_ms]`. This is intentional in the documentation, but the newest-trade anchor and lack of freshness/clock checks mean the feature window may not correspond to the observation time.

**Impact:** The feature/target relationship can be distorted by API staleness or page truncation, especially when the exchange returns a partial recent-trade page.

**Confidence:** Confirmed risk.

**Remediation:** Anchor features to the same normalized observation time used by the label policy and record actual coverage start/end, page truncation, and freshness.

### P2 — The live Born-rule arm is mostly a gated classical predictor

**Evidence:** `core/quantum_core.py:98-139`, `:232-247`; `config.py:51-53`

Constructive predictions are reverted to `classical_part` when prediction is at least `0.99` or interference exceeds `0.15`. Negative interference is also reverted to the classical part. The active model therefore frequently executes a classical fallback rather than the raw Born prediction.

Current artifacts show:

- `btcusdt-quantum-1785124079.json`: `saturation_gate` 183/280 eligible records (65.4%);
- `btcusdt-quantum-1785119130.json`: `saturation_gate` 39/50 (78%);
- only 97/280 and 11/50 records were `fallback_reason == "none"`.

**Impact:** A positive aggregate result would not establish that the ungated Born rule works. It would evaluate a composite gated policy whose behavior is dominated by a classical fallback.

**Confidence:** Confirmed modeling interpretation.

**Remediation:** Treat the gated policy as a separately named frozen model. Report raw Born, gated prediction, classical part, and fallback segments as distinct pre-registered arms.

### P2 — Order-book imbalance sign is discarded

**Evidence:** `core/delta_adaptive.py:70-82`; `core/quantum_core.py:71-95`

The live phase uses `abs(imbalance)`, and the imbalance bucketing also groups by `abs(imbalance)`. Positive and negative order-book imbalance therefore receive the same phase and bucket treatment, despite the target being directional trade flow.

**Impact:** The model cannot represent opposite directional effects from signed imbalance. This is a domain assumption that should be justified experimentally, not treated as a neutral preprocessing detail.

**Confidence:** Confirmed.

**Remediation:** Either justify magnitude-only modeling in the preregistration or preserve sign through separate buckets/features and evaluate the change as a new model version.

### P2 — Held-out kline evaluation discards preceding context

**Evidence:** `core/backtest.py:69-90`; `core/validation_report.py:60-79`

Each split computes features and prediction history only within that split. The first held-out candle has no preceding training-window context, and the held-out feature construction does not carry the final training observations into the lookback.

**Impact:** The held-out score is not a faithful continuation of the time series and can differ from the operational walk-forward behavior. It may be conservative or distorted depending on regime transition.

**Confidence:** Confirmed.

**Remediation:** Preserve prior observations as read-only context when starting validation, while ensuring no held-out future values enter the feature state.

### P2 — Current scripts and documentation retain operational naming/schema drift

**Evidence:**

- `scripts/start_production_run.sh` writes `live_quantum_v3.log` and `live_quantum_v3.pid` while launching schema v5.
- `scripts/monitor_exploratory.sh` uses helper names `is_v4_exploratory()` and `exploratory_v4_files()` while filtering schema v5.
- `core/research_INDEX.md` still describes the analyzer as parsing v3.
- `verification_report.md` contains superseded v3 statements after the current v5 implementation.

The behavior is not always wrong, but the naming creates a real risk of selecting the wrong artifact, interpreting a legacy run as current, or following stale operational instructions.

**Confidence:** Confirmed documentation/operations risk.

**Remediation:** Rename or clearly isolate legacy names, add a single generated/current status page, and make monitor scripts validate run ID, schema, horizon, config hash, and file freshness together.

## Metrics and Statistical Validity

### Correctly implemented or appropriately constrained

- Primary v5 analysis filters complete forward-window labels and eligibility.
- Classical and live targets are explicitly documented as different tasks.
- The null baseline `MAE(0.5)` is displayed by the analyzer.
- The paired error arrays are validated for equal length and finite nonnegative values.
- The moving-block bootstrap is deterministic for fixed inputs and seed.
- Current live reports suppress significance claims below 720 eligible records.

### Remaining concerns

1. **Win rate is not profitability.** The code correctly labels price simulation as diagnostic in the canonical path, but legacy scripts still print win-rate summaries without equally prominent non-comparability warnings.
2. **Aggregate analysis loses paired raw data.** `analyze_live_results.py` computes weighted means and total wins across files but does not recompute a combined paired bootstrap, so an aggregate “primary” tier is only descriptive.
3. **Multiple-run dependence is unspecified.** Same-config runs are grouped by `config_hash` without a policy for repeated looks, stopped/restarted runs, overlapping time periods, or dependence between runs.
4. **The `N_HYPOTHESES_LIVE = 1` choice is a research assumption, not something enforced by code.** The system cannot prove that no other live hypotheses, segmentations, or gate variants were tested.
5. **Confidence intervals are bootstrap intervals of the raw mean-difference resamples, while p-values use centered resampling.** This is not necessarily invalid, but the exact inferential procedure should be documented and independently reviewed rather than called a generic “White’s Reality Check.”

## Security, Privacy, and Reliability

### Security posture

- No exchange API keys, credentials, order endpoints, or order execution code were found.
- Symbols are constrained to lowercase alphanumeric values in `data_fetcher.py`.
- Network calls use HTTPS and bounded response reads.
- Raw market trades are stored locally; they are public market data, but the repository contains large logs and result databases that may expose operational timing and host-side metadata.

### Reliability gaps

- Direct runner invocation lacks the production wrapper’s lock.
- There is no structured metrics system; monitoring parses logs and JSON ad hoc.
- `SIGKILL` recovery can leave only SQLite as the authoritative state; operators must understand that JSON may lag.
- No disk-space, database-size, export-latency, API-rate-limit, or endpoint-health alert exists.
- Raw trade retention is time-based at startup and does not guarantee pending-label recoverability after a long pause.

## Test Assessment

`make test -s` passes **94 tests** on Python 3.14.5. The tests cover:

- basic feature construction;
- Born-rule bounds and fallback metadata;
- pending/resolved helper behavior;
- SQLite round trips and several synthetic coverage cases;
- fake-clock runner completion and resume;
- analyzer filtering;
- deterministic bootstrap behavior.

The suite does not cover the highest-risk production cases:

- realistic consecutive saturated pages under high-volume timing;
- local/exchange clock skew or future/stale timestamps;
- malformed depth/trade payloads and zero/negative prices;
- simultaneous processes resuming the same run;
- crash between SQLite commit and JSON export;
- export latency and disk exhaustion;
- analyzer rejection of malformed/mismatched manifests;
- aggregate paired inference across multiple result files;
- raw versus gated Born-arm attribution;
- boundary overlap from inclusive `[start, end]` intervals.

## Prioritized Remediation

### Immediate

1. Fix saturated-page frontier logic and add a realistic regression test.
2. Establish a single clock-domain policy for forecast and label timestamps.
3. Add stale/freshness validation for trades, ticker, depth, and local clock offset.
4. Re-run or invalidate all v5 artifacts collected under the old capture logic.

### Short term

5. Add per-run locking or transactional single-pending enforcement.
6. Make analyzer validation fail closed on manifest/config/model mismatches.
7. Report excluded counts and reason distributions.
8. Replace the mislabeled reality-check API with correctly named paired-loss inference.
9. Instrument endpoint failures, retry counts, capture gaps, export latency, and database growth.

### Research hardening

10. Freeze separate raw-Born, gated-Born, and classical comparator definitions.
11. Decide whether signed imbalance is part of the hypothesis.
12. Preserve temporal context across held-out splits.
13. Define repeated-run, aggregation, and multiple-testing policy before collecting a primary corpus.
14. Require an execution model before making any profitability interpretation.

## Final Verdict

**Software maturity:** Moderate research prototype with meaningful durability improvements.  
**Canonical live-pipeline readiness:** Not ready for primary scientific claims until capture-frontier and clock-alignment issues are fixed and the corpus is recollected.  
**Current empirical claim:** Existing artifacts do not establish Born-rule superiority. Several exploratory results are below the constant-0.5 null baseline, and production evidence is far below the required 720 eligible observations.  
**Security risk:** Low for exchange-account compromise; moderate for operational/data-integrity risk.  
**Recommended status:** No-go for new primary claims; continue only as diagnostic collection after the immediate data-integrity fixes.

## Schema-v7 Timing Incident — July 28, 2026

Two schema-v7r2 HTX diagnostic runs were inspected after completion:

- `btcusdt-diagnostic-20260728-124453-c3e38bf0`
- `btcusdt-diagnostic-20260728-130620-02577b4a`

Both SQLite databases pass `PRAGMA integrity_check`, have no active lease, and
reached their configured 10-slot diagnostic limit. Connectivity and raw persistence
worked: the first run stored 83 trades and 547 books; the second stored 58 trades
and 580 books.

The forecast lifecycle was invalid. Every pending forecast was resolved roughly
58.5 seconds before its 60-second label window ended. The first database persisted
one labeled trade while its raw events reconstruct 82 trades in the same windows.
The second persisted one while raw events reconstruct 57. The defect was caused by
resolving `pending_label` on the next event inside the active slot instead of waiting
for `slot_end_ms`.

These databases are immutable audit evidence and must not be repaired in place.
Schema-v7r3 status/export integrity checks classify both as `quarantined`, and
analysis is blocked. They support only connectivity, raw persistence, forecast
creation, and shutdown observations. They support no accuracy, profitability, or
model-quality claim.
