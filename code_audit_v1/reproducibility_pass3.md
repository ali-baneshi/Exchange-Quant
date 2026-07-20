# Reproducibility — Pass 3 (Cross-Validation & Reproducibility)

---

## Seed Fixity

| Source | Seed Fixed? | Value | Notes |
|--------|------------|-------|-------|
| `experiment.py:129` | YES | `random.seed(42)` | Only affects synthetic experiment |
| `visualize.py:37` | YES | `random.seed(42)` | Same |
| `market_sim.py:35` | **NO** | Uses `random.uniform` on default Random | Agent biases are different each run |
| `validation.py:121` | YES | `rng = random.Random(seed)` with seed=42 | Uses local Random instance, not global |
| `calibrate_delta.py` | N/A | No random elements | Deterministic |
| `backtest.py` | N/A | No random elements | Deterministic |
| `backtest_ensemble.py` | N/A | No random elements | Deterministic |
| `backtest_boost.py` | N/A | No random elements | Deterministic |
| Live pipelines | N/A | No random elements | API-dependent (network) |

**Impact on reproducibility:**
- Backtests: **Fully reproducible** — no random elements, same data → same results
- Synthetic experiment: **NOT reproducible** — `market_sim.py` uses `random.uniform` without a seed. Different agent biases each run → different results.
- Validation bootstrap: **Reproducible** — uses dedicated `Random(42)` instance
- Live pipelines: **NOT reproducible** by nature (live data), but results should be statistically consistent

---

## Sources of Nondeterminism

### In Code
1. **`market_sim.py:35`**: `Agent.__init__` uses `random.uniform(-0.5, 0.5)` on the global Random instance. No seed is set before creating agents. Running `experiment.py` twice produces different results.
2. **`market_sim.py:43`**: `random.gauss(0, self.vol)` — same issue.
3. **`market_sim.py:22`**: `random.random()` for agent decisions — same issue.

### Network / API
4. **`data_fetcher.py:106-109`**: `ThreadPoolExecutor` with 4 workers — response order is non-deterministic.
5. **`data_fetcher.py:81`**: Trade data from Huobi changes between calls.
6. **`data_historical.py:28-42`**: `_curl_get` retries may return different pagination slices.
7. **`data_fetcher.py:15-32`**: `_api_get` with retry — network latency affects timing.

### Data-Dependent
8. **`data_fetcher.py:144`**: `vols = [k["vol"] for k in klines[-3:]]` — depends on which klines are returned.
9. **Live pipeline step order**: Depends on API response times.

---

## Metric Definition Consistency

### Win Rate
- **Definition:** `sum(quantum_error < classical_error) / n`
- **Used consistently in:** `validation.py:156-158`, `reality_check.py:26`, `analyze_live_results.py:57`
- **Verdict:** ✅ Consistent

### Improvement
- **Definition:** `(mean_classical - mean_quantum) / mean_classical * 100`
- **Used consistently in:** `validation.py:163`, `analyze_live_results.py:62`, `experiment.py:104`
- **Verdict:** ✅ Consistent

### Max Drawdown
- **Definition:** MDD from equity curve where `reward = (0.5 - error) * direction`, equity = cumulative sum
- **Used in:** `validation.py:40-60`
- **Verdict:** Only defined in `validation.py`; used consistently via delegation ✅

### Sharpe Ratio
- **Definition:** `mean(returns) / std(returns) * sqrt(periods_per_year)` where `returns = (max_error - error) / max_error`
- **Used in:** `validation.py:63-80`
- **Issue:** `periods_per_year` is hardcoded to 8760 (hourly) by callers even when data is 15min or 1day ❌

### Profit Factor
- **Definition:** `wins / losses` where win = quantum error < classical error
- **Used in:** `validation.py:83-99`
- **Verdict:** ✅ Consistent

### Bonferroni Correction
- **Definition:** `min(1.0, p_value * N_HYPOTHESES_TOTAL)` where N=5
- **Used in:** `validation.py:31-37`, imported by `reality_check.py`, `validation_report.py`
- **Verdict:** ✅ Consistent

### Block Bootstrap p-value
- **Definition:** White's Reality Check with sign-flipping, block_len = ceil(n^(1/3)), n_bootstrap=10000
- **Used in:** `validation.py:102-144`
- **Issue:** Block_len uses floor (int) instead of ceil, minor bias ❌
- **Verdict:** Mostly consistent, minor implementation issue

---

## Documented vs Actual Code Divergence

| Claim (research_05_results.md) | Code Reality | Impact |
|--------------------------------|-------------|--------|
| "Born rule unified across all 4 models" | 3 of 6 Born rule implementations (live pipelines) lack normalization | Inconsistent predictions across pipelines |
| "delta computed from market context" | Backtest ensemble uses hardcoded return-based delta, not `compute_delta` | Backtest results use different delta than live |
| "Bonferroni correction for 5 hypotheses" | N_HYPOTHESES_TOTAL = 5 in `validation.py:19` | ✅ Correct |
| "Block bootstrap with ceil(n^(1/3))" | Uses `int(n^(1/3) + 1e-10)` which is floor, not ceil | Block_len off by 1 for some n |
| "Gate.io pagination up to 5000+ candles" | `fetch_klines_gateio` has pagination, but Huobi fallback limited to 2000 | ✅ Mostly correct |
| "Adaptive weights vs fixed: no difference" | Two different weight formulas (relative vs absolute) exist | The conclusion may not generalize across weight strategies |
| "v4: removed momentum, delta_boost" | `ensemble.py` has 2 models (correct); but `_live_results/state.json` still has 3-model format | State file is incompatible with current code |

---

## End-to-End Reproducibility Assessment

### Can someone clone and reproduce "Born rule error = 0.4801"?

**Steps needed:**
1. Clone repo
2. `pip install` (no requirements.txt exists — must guess dependencies: only stdlib used)
3. Run `python3 core/calibrate_delta.py` (for delta calibration)
4. Run `python3 core/experiment_ablation.py` (for ablation study)

**Will they get exactly 0.4801?**
- Backtest results: **YES** (deterministic, same data from Gate.io → same cache)
- Synthetic results: **NO** (no seed in `market_sim.py`)
- Live results: **NO** (different API data)

**Missing:**
- No `requirements.txt` or `pyproject.toml` (but only stdlib used — pure Python)
- No seed fix for synthetic experiment
- No pinned cache for Gate.io data
- No CI/CD or test suite to verify

---

## Recommendations

1. **Fix seed in `market_sim.py:35`**: Add `random.seed(42)` before agent creation
2. **Add `requirements.txt`**: Even if empty (stdlib only), documents dependencies
3. **Pin reference datasets**: Save the exact 2000-candle Huobi dataset used for the 0.4801 result
4. **Add test script**: `python3 -c "from data_historical import ...; assert abs(result - 0.4801) < 0.01"`
5. **Fix block_len ceiling** in `validation.py:115`
