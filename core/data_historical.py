#!/usr/bin/env python3

"""
Historical kline fetcher with pagination and caching.

Primary data source: Gate.io (paginated API, up to 5000+ candles).
Fallback: Huobi (max 2000 candles per request).
Automatically caches results in _kline_cache/ for reproducibility.

Usage:
    from data_historical import fetch_klines_range, parse_klines, held_out_split
    raw = fetch_klines_range("btcusdt", "60min", 5000)
    candles = parse_klines(raw)
    train_val, held_out = held_out_split(candles)
"""

import json
import os
import subprocess
import time

HUOBI_BASE = "https://api.huobi.pro"
GATE_BASE = "https://api.gateio.ws"
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "_kline_cache")
os.makedirs(_CACHE_DIR, exist_ok=True)

GATE_INTERVALS = {
    "1min": "1m", "5min": "5m", "15min": "15m", "30min": "30m",
    "60min": "1h", "4hour": "4h", "1day": "1d", "1week": "7d",
}
# Gate.io intervals: 1m,5m,15m,30m,1h,4h,8h,1d,7d,30d
# 8h,30d not in Huobi; 1month not in Gate.io

# Held-out configuration
HELD_OUT_FRAC = 0.2  # last 20% reserved for final validation
# After calling parse_klines(), the last HELD_OUT_FRAC of candles
# are the held-out set.  All parameter tuning / training must use
# the first (1 - HELD_OUT_FRAC) portion only.


def _curl_get(url, timeout=8):
    for attempt in range(3):
        try:
            result = subprocess.run(
                ["curl", "-s", "-m", str(timeout), url],
                capture_output=True, text=True, timeout=timeout + 2,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                if data.get("status") == "ok":
                    return data
            return None
        except Exception:
            if attempt < 2:
                time.sleep(1)
            continue
    return None


def _curl_get_raw(url, timeout=8):
    """Fetch a URL that returns a raw JSON value (array or object)."""
    for attempt in range(3):
        try:
            result = subprocess.run(
                ["curl", "-s", "-m", str(timeout), url],
                capture_output=True, text=True, timeout=timeout + 2,
            )
            if result.returncode == 0 and result.stdout.strip():
                return json.loads(result.stdout)
            return None
        except Exception:
            if attempt < 2:
                time.sleep(1)
            continue
    return None


def _cache_path(symbol, period):
    return os.path.join(_CACHE_DIR, f"{symbol}_{period}.json")


def _load_cache(symbol, period):
    path = _cache_path(symbol, period)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def _save_cache(symbol, period, data):
    path = _cache_path(symbol, period)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _gate_to_huobi(raw_candles):
    """
    Convert Gate.io kline array to Huobi dict format (newest-first).
    Gate.io format: [ts, quote_vol, close, high, low, open, vol, complete]
    """
    result = []
    for k in raw_candles:
        result.append({
            "id": int(k[0]),
            "open": float(k[5]),
            "close": float(k[2]),
            "high": float(k[3]),
            "low": float(k[4]),
            "amount": float(k[1]),
            "vol": float(k[6]),
            "count": 0,
        })
    result.reverse()
    return result


def fetch_klines_gateio(symbol="btcusdt", period="60min", n_candles=2000):
    """
    Fetch OHLCV from Gate.io with pagination.
    Returns raw candles in Huobi-compatible format (newest-first list of dicts).
    """
    MAX_PER_CALL = 1000
    interval = GATE_INTERVALS.get(period, period)
    pair = symbol.upper() if symbol.islower() else symbol
    if "_" not in pair and len(pair) > 6:
        pair = pair[:3] + "_" + pair[3:]

    cached = _load_cache(symbol, period)
    if len(cached) >= n_candles:
        return cached[-n_candles:]

    all_data = list(cached)
    end_ts = None
    if all_data:
        end_ts = all_data[-1]["id"]

    while len(all_data) < n_candles:
        url = f"{GATE_BASE}/api/v4/spot/candlesticks?currency_pair={pair}&interval={interval}&limit={MAX_PER_CALL}"
        if end_ts is not None:
            url += f"&to={end_ts}"

        raw = _curl_get_raw(url)
        if raw is None or len(raw) == 0:
            break

        batch = _gate_to_huobi(raw)
        if not batch:
            break

        existing_ids = {c["id"] for c in all_data}
        new_candles = [c for c in batch if c["id"] not in existing_ids]
        if not new_candles:
            break

        all_data = all_data + new_candles
        end_ts = min(c["id"] for c in new_candles)
        time.sleep(0.15)

    if all_data:
        _save_cache(symbol, period, all_data)
    return all_data[-n_candles:] if all_data else []


def fetch_klines_range(symbol="btcusdt", period="15min", n_candles=2000):
    """Fetch candles from Gate.io (preferred) or Huobi (fallback)."""
    cached = _load_cache(symbol, period)
    if len(cached) >= n_candles:
        return cached[-n_candles:]

    if period in GATE_INTERVALS:
        data = fetch_klines_gateio(symbol, period, n_candles)
        if len(data) >= n_candles:
            return data[-n_candles:]

    url = f"{HUOBI_BASE}/market/history/kline?symbol={symbol}&period={period}&size={min(n_candles, 2000)}"
    raw = _curl_get(url)
    if raw is None:
        return cached[-n_candles:] if cached else []
    huobi_data = raw.get("data", [])
    if huobi_data:
        _save_cache(symbol, period, huobi_data)
    return huobi_data[-n_candles:] if huobi_data else cached[-n_candles:] if cached else []


def parse_klines(raw_candles):
    result = []
    for k in raw_candles:
        result.append({
            "ts": int(k.get("id", 0)),
            "open": float(k.get("open", 0)),
            "close": float(k.get("close", 0)),
            "high": float(k.get("high", 0)),
            "low": float(k.get("low", 0)),
            "amount": float(k.get("amount", 0)),
            "vol": float(k.get("vol", 0)),
            "count": int(k.get("count", 0)),
        })
    result.reverse()
    return result


def held_out_split(candles):
    """
    Split candle list into (train_val, held_out).
    The held-out set is the last HELD_OUT_FRAC of candles (most recent).
    Use train_val for ALL parameter tuning and development.
    Run held_out ONCE at the very end for final honest evaluation.
    """
    split = int(len(candles) * (1 - HELD_OUT_FRAC))
    return candles[:split], candles[split:]


def load_and_split(symbol="btcusdt", period="60min", n_candles=2000):
    """
    High-level helper: fetch, parse, split.
    Returns (train_val_candles, held_out_candles, all_candles).
    """
    raw = fetch_klines_range(symbol, period, n_candles)
    candles = parse_klines(raw)
    train_val, held_out = held_out_split(candles)
    return train_val, held_out, candles


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(line_buffering=True)

    for period, n in [("15min", 5000), ("60min", 5000), ("1day", 5000)]:
        print(f"\nFetching {n} {period} candles...")
        raw = fetch_klines_range("btcusdt", period, n)
        candles = parse_klines(raw)
        tv, ho = held_out_split(candles)
        print(f"  total={len(candles)}  train+val={len(tv)}  held_out={len(ho)}")
        if candles:
            print(f"  range: ts={candles[0]['ts']} -> {candles[-1]['ts']}  "
                  f"price={candles[0]['close']:.0f} -> {candles[-1]['close']:.0f}  "
                  f"held_out starts at ho[0] ts={ho[0]['ts']}")
        else:
            print(f"  FAILED to get {period} candles")
