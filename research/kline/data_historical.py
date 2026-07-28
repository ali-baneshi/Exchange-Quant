#!/usr/bin/env python3

"""
Historical kline fetcher with pagination and caching.

Primary data source: Gate.io (paginated API, up to 5000+ candles).
Fallback: Huobi (max 2000 candles per request).
Automatically caches results in _kline_cache/ for reproducibility.

Contract: all returned candle lists are oldest → newest (ascending by id/ts).
Slicing for n candles always keeps the newest n from that ascending series.

Requires system `curl` for Gate.io / Huobi HTTP fetches (see requirements.txt).

Usage:
    from data_historical import fetch_klines_range, parse_klines, held_out_split
    raw = fetch_klines_range("btcusdt", "60min", 5000)
    candles = parse_klines(raw)
    train_val, held_out = held_out_split(candles)
"""

import json
import os
import subprocess
import sys
import time

HELD_OUT_FRAC = 0.2

HUOBI_BASE = "https://api.huobi.pro"
GATE_BASE = "https://api.gateio.ws"
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "_kline_cache")

GATE_INTERVALS = {
    "1min": "1m", "5min": "5m", "15min": "15m", "30min": "30m",
    "60min": "1h", "4hour": "4h", "1day": "1d", "1week": "7d",
}
# Gate.io intervals: 1m,5m,15m,30m,1h,4h,8h,1d,7d,30d
# 8h,30d not in Huobi; 1month not in Gate.io

_KNOWN_QUOTES = ("USDT", "USDC", "BTC", "ETH", "USD", "DAI", "BUSD")

# Held-out configuration (see config.py)
# After calling parse_klines(), the last HELD_OUT_FRAC of candles
# are the held-out set.  All parameter tuning / training must use
# the first (1 - HELD_OUT_FRAC) portion only.


def _log_fetch_error(where, detail):
    print(f"[data_historical] {where}: {detail}", file=sys.stderr)


def _curl_get(url, timeout=8):
    last_err = None
    for attempt in range(3):
        try:
            result = subprocess.run(
                ["curl", "-s", "-m", str(timeout), url],
                capture_output=True, text=True, timeout=timeout + 2,
            )
            if result.returncode != 0:
                last_err = f"curl exit {result.returncode}: {result.stderr.strip() or 'no stderr'}"
            elif not result.stdout.strip():
                last_err = "empty response body"
            else:
                data = json.loads(result.stdout)
                if data.get("status") == "ok":
                    return data
                last_err = f"API status={data.get('status')!r} err={data.get('err-msg') or data.get('message')!r}"
                return None
        except FileNotFoundError:
            _log_fetch_error("_curl_get", "curl not found on PATH (required for historical fetch)")
            return None
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
        if attempt < 2:
            time.sleep(1)
    if last_err:
        _log_fetch_error("_curl_get", last_err)
    return None


def _curl_get_raw(url, timeout=8):
    """Fetch a URL that returns a raw JSON value (array or object)."""
    last_err = None
    for attempt in range(3):
        try:
            result = subprocess.run(
                ["curl", "-s", "-m", str(timeout), url],
                capture_output=True, text=True, timeout=timeout + 2,
            )
            if result.returncode != 0:
                last_err = f"curl exit {result.returncode}: {result.stderr.strip() or 'no stderr'}"
            elif not result.stdout.strip():
                last_err = "empty response body"
            else:
                return json.loads(result.stdout)
        except FileNotFoundError:
            _log_fetch_error("_curl_get_raw", "curl not found on PATH (required for historical fetch)")
            return None
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
        if attempt < 2:
            time.sleep(1)
    if last_err:
        _log_fetch_error("_curl_get_raw", last_err)
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
    os.makedirs(_CACHE_DIR, exist_ok=True)
    path = _cache_path(symbol, period)
    tmp = path + ".tmp"
    ascending = to_ascending(data)
    with open(tmp, "w") as f:
        json.dump(ascending, f)
    os.replace(tmp, path)


def to_ascending(candles):
    """
    Normalize raw Huobi-compatible candles to oldest → newest by id.
    Deduplicates by id (last write wins). Safe for legacy newest-first caches.
    """
    if not candles:
        return []
    by_id = {}
    for c in candles:
        cid = c.get("id")
        if cid is None:
            continue
        by_id[int(cid)] = c
    return [by_id[k] for k in sorted(by_id)]


def newest_n(candles, n_candles):
    """From an ascending list, return the newest n candles (still ascending)."""
    if not candles or n_candles <= 0:
        return []
    asc = to_ascending(candles)
    return asc[-n_candles:]


def to_gate_pair(symbol):
    """Convert btcusdt / dogeusdt style symbols to Gate currency_pair."""
    pair = symbol.upper().replace("-", "_")
    if "_" in pair:
        return pair
    for quote in _KNOWN_QUOTES:
        if pair.endswith(quote) and len(pair) > len(quote):
            return f"{pair[:-len(quote)]}_{quote}"
    if len(pair) > 6:
        return pair[:3] + "_" + pair[3:]
    return pair


def _gate_to_huobi(raw_candles):
    """
    Convert Gate.io kline array to Huobi dict format, oldest → newest.
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
    return to_ascending(result)


def _refresh_cache_tail(symbol, period, cached):
    """Fetch latest Gate.io candles and merge into cache (updates stale tail)."""
    MAX_PER_CALL = 1000
    interval = GATE_INTERVALS.get(period, period)
    pair = to_gate_pair(symbol)
    url = (
        f"{GATE_BASE}/api/v4/spot/candlesticks"
        f"?currency_pair={pair}&interval={interval}&limit={MAX_PER_CALL}"
    )
    raw = _curl_get_raw(url)
    if raw is None or len(raw) == 0:
        return cached
    batch = _gate_to_huobi(raw)
    if not batch:
        return cached
    return to_ascending(cached + batch)


def fetch_klines_gateio(symbol="btcusdt", period="60min", n_candles=2000):
    """
    Fetch OHLCV from Gate.io with pagination.
    Returns raw candles oldest → newest (Huobi-compatible dicts).
    """
    MAX_PER_CALL = 1000
    interval = GATE_INTERVALS.get(period, period)
    pair = to_gate_pair(symbol)

    cached = to_ascending(_load_cache(symbol, period))
    if len(cached) >= n_candles:
        refreshed = _refresh_cache_tail(symbol, period, cached)
        if len(refreshed) != len(cached) or (refreshed and cached and refreshed[-1]["id"] != cached[-1]["id"]):
            _save_cache(symbol, period, refreshed)
            cached = refreshed
        return newest_n(cached, n_candles)

    all_data = list(cached)

    while len(all_data) < n_candles:
        url = (
            f"{GATE_BASE}/api/v4/spot/candlesticks"
            f"?currency_pair={pair}&interval={interval}&limit={MAX_PER_CALL}"
        )
        # Page further into the past from the oldest candle we already have.
        if all_data:
            url += f"&to={all_data[0]['id']}"

        raw = _curl_get_raw(url)
        if raw is None or len(raw) == 0:
            break

        batch = _gate_to_huobi(raw)
        if not batch:
            break

        existing_ids = {c["id"] for c in all_data}
        if all_data:
            cutoff = all_data[0]["id"]
            new_candles = [c for c in batch if c["id"] < cutoff and c["id"] not in existing_ids]
        else:
            new_candles = [c for c in batch if c["id"] not in existing_ids]
        if not new_candles:
            break

        all_data = to_ascending(all_data + new_candles)
        time.sleep(0.15)

    if all_data:
        _save_cache(symbol, period, all_data)
    return newest_n(all_data, n_candles)


def fetch_klines_range(symbol="btcusdt", period="15min", n_candles=2000):
    """Fetch candles from Gate.io (preferred) or Huobi (fallback). Oldest → newest."""
    cached = to_ascending(_load_cache(symbol, period))
    if len(cached) >= n_candles:
        if period in GATE_INTERVALS:
            refreshed = _refresh_cache_tail(symbol, period, cached)
            if len(refreshed) != len(cached) or (refreshed and cached and refreshed[-1]["id"] != cached[-1]["id"]):
                _save_cache(symbol, period, refreshed)
                cached = refreshed
        return newest_n(cached, n_candles)

    if period in GATE_INTERVALS:
        data = fetch_klines_gateio(symbol, period, n_candles)
        if len(data) >= n_candles:
            return newest_n(data, n_candles)

    url = (
        f"{HUOBI_BASE}/market/history/kline"
        f"?symbol={symbol}&period={period}&size={min(n_candles, 2000)}"
    )
    raw = _curl_get(url)
    if raw is None:
        return newest_n(cached, n_candles) if cached else []
    huobi_data = to_ascending(raw.get("data", []))
    if huobi_data:
        _save_cache(symbol, period, huobi_data)
    if huobi_data:
        return newest_n(huobi_data, n_candles)
    return newest_n(cached, n_candles) if cached else []


def parse_klines(raw_candles):
    """Parse raw Huobi-compatible candles to typed dicts, oldest → newest."""
    ascending = to_ascending(raw_candles)
    result = []
    for k in ascending:
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
    return result


def held_out_split(candles, min_held_out=1):
    """
    Split candle list into (train_val, held_out).
    Candles must be oldest → newest. Held-out is the last HELD_OUT_FRAC (most recent).
    Use train_val for ALL parameter tuning and development.
    Run held_out ONCE at the very end for final honest evaluation.
    """
    n = len(candles)
    if n < min_held_out + 1:
        raise ValueError(
            f"Need at least {min_held_out + 1} candles for held-out split, got {n}"
        )
    split = int(n * (1 - HELD_OUT_FRAC))
    split = min(split, n - min_held_out)
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
