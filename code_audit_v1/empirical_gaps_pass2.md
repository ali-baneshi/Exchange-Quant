# Empirical Gaps — Pass 2 (Data & Statistics)

---

## Statistical Weaknesses

### 1. Sample Size for Statistical Significance

The ablation result (Born rule 0.4801 vs vol_regime 0.5112) is the ONLY positive result. Breakdown:

- **Dataset:** 2000 Huobi candles → 400 held-out samples (after 80/20 split)
- **Effective sample size after block bootstrap:** block_len = ceil(400^(1/3)) ≈ 8, so ~50 blocks
- **p-value resolution:** With 50 blocks and 10000 bootstrap iterations, the minimum detectable p-value is ~0.0001
- **Bonferroni threshold:** 0.05 / 5 = 0.01

For the Held-Out result to survive Bonferroni, the raw p-value must be < 0.01. With 400 samples, this requires roughly 225+ quantum wins out of 400 (56.25%+ win rate). The 6.1% improvement (0.5112 → 0.4801) corresponds to roughly 220 wins out of 400 (55%). This is borderline.

**The research_05_results.md does NOT report the p-value for the 0.4801 result**, making it impossible to verify claimed significance.

### 2. No True Out-of-Sample Testing

The "held-out" set is the last 20% of the continuous time series. This tests whether the model generalizes to adjacent time periods, NOT to different market regimes.

A rigorous test would require:
- Multiple non-overlapping time periods (e.g., 2022 data, 2023 data, 2024 data)
- Different market regimes (bull, bear, sideways, high-vol, low-vol)
- Different assets (ETH, SOL, etc.)

Currently, only BTCUSDT on a single continuous time range is tested.

### 3. Synthetic Experiment Shows Born Rule WORSE

From research_05_results.md:
```
Classical err: 0.1255
Quantum err:   0.1549
Improvement:  -23.5%
```

The synthetic experiment (which has a KNOWN hidden context) shows Born rule performs significantly WORSE than classical. This contradicts the claim that Born rule captures hidden context better. Possible explanations:
- The synthetic experiment's hidden context is fundamentally different from real market dynamics
- The synthetic experiment's delta computation is incorrect
- **The Born rule advantage does not generalize to all types of hidden context**

### 4. Multiple Testing Without Pre-Registration

Bonferroni correction assumes the 5 tests were pre-registered. In reality, the research has been iterative:
- v1: Found initial results (no correction)
- v2: Added Bonferroni
- v3: Fixed bugs, removed models (momentum, anomaly detection)
- v4: Unified Born rule, added Gate.io

Each iteration involves testing and re-testing. The effective number of hypotheses tested is much larger than 5. A stricter correction (e.g., Holm-Bonferroni or Benjamini-Hochberg) would be more appropriate.

---

## Data Collection Bottlenecks

### Current State
| Timeframe | Max candles | Covers | Collection time |
|-----------|-------------|--------|-----------------|
| 15min | 5000 | ~52 days | ~30s (Gate.io) |
| 60min | 5000 | ~208 days | ~30s (Gate.io) |
| 1day | 5000 | ~13.7 years | ~30s (Gate.io) |
| Live (any) | limited by delay | varies | delay × n_steps |

### Live Data Collection is the Bottleneck

The live data pipeline (Huobi order book) produces `buy_ratio` and `imbalance`, which is what the Born rule needs to work properly. But collection is slow:
- `delay=3600` (default): 1000 steps = 1000 hours ≈ 42 days
- `delay=60` (minimum reasonable): 1000 steps ≈ 16 hours

### Proposed Collection Strategy

**Batch historical (already fast):**
```bash
# These run in seconds and cache results
python3 data_historical.py  # fetches 5000 candles for 15min, 60min, 1day
```

**Dedicated live data collector (new file needed):**
Create `data_collector.py` that:
- Runs with `delay=60` seconds
- Collects only `hd.fetch_features(symbol)` — no model inference
- Saves raw features to `_kline_cache/live_features_{symbol}_{timestamp}.json`
- Runs for user-configurable steps (e.g., `n_steps=1000` takes ~16 hours)

**Command for overnight collection:**
```bash
nohup python3 data_collector.py btcusdt 1000 60 &
```
This collects 1000 live data points overnight.

### Timeframe Data Availability

| Timeframe | Has 5000+ candles? | Has buy_ratio? | Has imbalance? |
|-----------|-------------------|----------------|----------------|
| 15min | Yes (Gate.io) | No (klines only) | No |
| 60min | Yes (Gate.io) | No (klines only) | No |
| 1day | Yes (Gate.io) | No (klines only) | No |
| Live (streaming) | Need to collect | Yes | Yes |

**Key insight:** The only data with `imbalance` (required for `compute_delta`) is live Huobi data. Historical data from Gate.io has no order book -> no imbalance -> `compute_delta` falls back to return-based delta. This means ALL backtests use a fundamentally different (and weaker) delta than the live pipeline.

---

## Recommended Data Collection Commands

### Fast Historical (minutes):
```bash
# From project root
python3 core/data_historical.py
# Fetches 5000 15min, 5000 60min, 5000 1day — caches to _kline_cache/
```

### Live Overnight Collection:
Create `core/data_collector.py` with:
```python
import json, time, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from data_fetcher import HuobiData

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "_live_results")
os.makedirs(RESULTS_DIR, exist_ok=True)

def run(symbol="btcusdt", n_steps=1000, delay=60):
    hd = HuobiData()
    data = []
    for i in range(n_steps):
        f = hd.fetch_features(symbol)
        if f:
            data.append(f)
            print(f"[{i+1}/{n_steps}] price={f['price']:.1f} buy={f['buy_ratio']:.4f}")
        if i < n_steps - 1:
            time.sleep(delay)
    path = os.path.join(RESULTS_DIR, f"collected_{symbol}_{int(time.time())}.json")
    with open(path, "w") as fp:
        json.dump(data, fp, indent=2)
    print(f"Saved {len(data)} samples to {path}")

if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "btcusdt"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    d = float(sys.argv[3]) if len(sys.argv) > 3 else 60
    run(symbol, n, d)
```

Then run:
```bash
nohup python3 core/data_collector.py btcusdt 1500 60 &
# Runs ~25 hours, collects 1500 buy_ratio samples with imbalance
```

### Running the Live Ensemble Pipeline Properly:
After the `_quantum_predict` bug is fixed:
```bash
# Quantum-only mode (recommended for pure Born rule evaluation)
python3 core/pipeline_live_ensemble.py btcusdt 10000 3600 quantum
```
