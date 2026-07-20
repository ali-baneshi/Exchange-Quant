#!/usr/bin/env python3

"""
Dedicated live data collector for Exchange-Q.

Collects raw features (buy_ratio, imbalance, volatility) from Huobi
at regular intervals WITHOUT running any model inference.
Use this to accumulate large datasets for later analysis.

Usage:
    python3 data_collector.py btcusdt 1500 60
    # Collects 1500 samples at 60s intervals (~25 hours)

    nohup python3 data_collector.py btcusdt 1500 60 &
    # Runs overnight, saves to _live_results/
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_fetcher import HuobiData

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "_live_results")
os.makedirs(RESULTS_DIR, exist_ok=True)


def run(symbol="btcusdt", n_steps=1000, delay=60):
    hd = HuobiData()
    data = []
    t_start = time.time()

    print(f"  DATA COLLECTOR")
    print(f"  symbol={symbol}  n_steps={n_steps}  delay={delay}s")
    print(f"  Started at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Estimated duration: {n_steps * delay / 3600:.1f}h")
    print()

    for i in range(n_steps):
        features = hd.fetch_features(symbol)
        if features:
            data.append(features)
            print(f"  [{i+1:4d}/{n_steps}] p={features['price']:.1f} "
                  f"buy={features['buy_ratio']:.4f} "
                  f"imb={features['imbalance']*100:+.1f}% "
                  f"vol={features['volatility']:.6f}")
        else:
            print(f"  [{i+1:4d}/{n_steps}] NO DATA")

        if i < n_steps - 1:
            time.sleep(delay)

        # Save checkpoint every 100 steps
        if len(data) > 0 and len(data) % 100 == 0:
            _save_checkpoint(symbol, data)

    # Final save
    path = os.path.join(RESULTS_DIR, f"collected_{symbol}_{int(time.time())}.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    elapsed = time.time() - t_start
    print(f"\n  Done. Collected {len(data)} samples in {elapsed/3600:.1f}h")
    print(f"  Saved to {path}")
    return data


def _save_checkpoint(symbol, data):
    path = os.path.join(RESULTS_DIR, f"collected_{symbol}_checkpoint.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    symbol = sys.argv[1] if len(sys.argv) > 1 else "btcusdt"
    n_steps = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    delay = float(sys.argv[3]) if len(sys.argv) > 3 else 60.0
    run(symbol, n_steps, delay)
