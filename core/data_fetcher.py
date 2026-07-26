#!/usr/bin/env python3

"""
Huobi live data fetcher for the Exchange-Q project.

Fetches order book depth, ticker data, recent trades, and 1-min klines
from the Huobi API.  Computes market features (buy_ratio, imbalance,
volatility, spread) used by the live prediction pipelines.

Usage:
    hd = HuobiData()
    features = hd.fetch_features("btcusdt")
"""

import json
import time
import math
import statistics
import http.client
import ssl
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import re

from config import (
    MAX_ENDPOINT_SKEW_MS,
    MIN_FORWARD_WINDOW_TRADES,
    min_forward_trades,
)

HUOBI_BASE = "https://api.huobi.pro"
_CTX = ssl.create_default_context()
_SYMBOL_RE = re.compile(r"^[a-z0-9]+$")


def _validate_symbol(symbol):
    if not symbol or not _SYMBOL_RE.match(symbol):
        raise ValueError(f"Invalid symbol {symbol!r}; expected lowercase alphanumeric (e.g. btcusdt)")
    return symbol


def _api_get(url, timeout=3):
    host = "api.huobi.pro"
    path = url.split("api.huobi.pro")[-1]
    last_err = None
    for attempt in range(2):
        conn = None
        try:
            conn = http.client.HTTPSConnection(host, timeout=timeout, context=_CTX)
            conn.request("GET", path, headers={"User-Agent": "Mozilla/5.0", "Connection": "close"})
            resp = conn.getresponse()
            body = resp.read(2_000_001)
            if resp.status < 200 or resp.status >= 300:
                last_err = f"HTTP {resp.status} {resp.reason}"
                continue
            if len(body) > 2_000_000:
                last_err = "response body exceeds 2 MB"
                continue
            data = json.loads(body)
            if not isinstance(data, dict):
                last_err = f"unexpected JSON type {type(data).__name__}"
                continue
            if data.get("status") == "ok":
                return data
            last_err = f"API status={data.get('status')!r} err={data.get('err-msg') or data.get('message')!r}"
            return None
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            if attempt < 1:
                time.sleep(0.2)
            continue
        finally:
            if conn is not None:
                conn.close()
    if last_err:
        print(f"[data_fetcher] _api_get {path}: {last_err}", file=sys.stderr)
    return None


class HuobiData:
    def fetch_ticker(self, symbol="btcusdt"):
        raw = _api_get(f"{HUOBI_BASE}/market/detail/merged?symbol={symbol}")
        if raw is None:
            return None
        tick = raw.get("tick", {})
        return {
            "open": tick.get("open", 0),
            "close": tick.get("close", 0),
            "high": tick.get("high", 0),
            "low": tick.get("low", 0),
            "amount": tick.get("amount", 0),
            "vol": tick.get("vol", 0),
            "bid": tick.get("bid", [0, 0]),
            "ask": tick.get("ask", [0, 0]),
            "ts": raw.get("ts", 0),
        }

    def fetch_depth(self, symbol="btcusdt", depth=20):
        if depth not in (5, 10, 20):
            depth = 20
        raw = _api_get(
            f"{HUOBI_BASE}/market/depth?symbol={symbol}&type=step1&depth={depth}"
        )
        if raw is None:
            return {"bids": [], "asks": []}
        tick = raw.get("tick", {})
        return {
            "bids": tick.get("bids", []),
            "asks": tick.get("asks", []),
            "ts": raw.get("ts", 0),
        }

    def fetch_trades(self, symbol="btcusdt", size=50):
        size = max(1, min(int(size), 2000))
        raw = _api_get(
            f"{HUOBI_BASE}/market/history/trade?symbol={symbol}&size={size}"
        )
        if raw is None:
            return []
        trades = []
        for item in raw.get("data", []):
            for t in item.get("data", []):
                trades.append({
                    "trade_id": t.get("id") or t.get("trade-id"),
                    "price": float(t.get("price", 0)),
                    "amount": float(t.get("amount", 0)),
                    "ts": t.get("ts", 0),
                    "direction": t.get("direction", "buy"),
                })
        return sorted(trades[:size], key=lambda trade: trade.get("ts", 0))

    def fetch_klines(self, symbol="btcusdt", period="1min", limit=100):
        raw = _api_get(
            f"{HUOBI_BASE}/market/history/kline?symbol={symbol}&period={period}&size={min(limit, 2000)}"
        )
        if raw is None:
            return []
        result = []
        for k in raw.get("data", []):
            result.append({
                "id": k.get("id", 0),
                "open": float(k.get("open", 0)),
                "close": float(k.get("close", 0)),
                "high": float(k.get("high", 0)),
                "low": float(k.get("low", 0)),
                "amount": float(k.get("amount", 0)),
                "vol": float(k.get("vol", 0)),
                "count": k.get("count", 0),
            })
        return sorted(result, key=lambda candle: candle.get("id", 0))

    def fetch_all(self, symbol="btcusdt", trade_size=30):
        symbol = _validate_symbol(symbol)
        with ThreadPoolExecutor(max_workers=4) as ex:
            ft = {ex.submit(self.fetch_ticker, symbol): "ticker",
                  ex.submit(self.fetch_depth, symbol, 20): "depth",
                  ex.submit(self.fetch_trades, symbol, trade_size): "trades",
                  ex.submit(self.fetch_klines, symbol, "1min", 5): "klines"}
            results = {}
            for fut in as_completed(ft):
                name = ft[fut]
                try:
                    results[name] = fut.result()
                except Exception as exc:
                    print(
                        f"[data_fetcher] {name} fetch failed: {type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )
        return (
            results.get("ticker"),
            results.get("depth", {"bids": [], "asks": []}),
            results.get("trades", []),
            results.get("klines", []),
        )

    def fetch_features(self, symbol="btcusdt", max_attempts=3):
        features, _ = self.fetch_features_with_trades(symbol, max_attempts=max_attempts)
        return features

    def fetch_features_with_trades(self, symbol="btcusdt", max_attempts=3,
                                   trade_size=30):
        symbol = _validate_symbol(symbol)
        for attempt in range(max_attempts):
            t, d, tr, k = self.fetch_all(symbol, trade_size=trade_size)
            f = compute_live_features(t, d, tr, k)
            if f is not None:
                return f, tr
            if attempt < max_attempts - 1:
                time.sleep(min(2 ** attempt, 30))
        return None, []


def compute_buy_ratio_for_window(trades, start_ms, end_ms, min_trades=None):
    """
    Buy/sell count and volume ratios for trades with ts in [start_ms, end_ms].
    Returns (result_dict, trade_count) or (None, trade_count) when below min_trades.
    """
    if min_trades is None:
        min_trades = MIN_FORWARD_WINDOW_TRADES
    window = [
        t for t in trades
        if start_ms <= t.get("ts", 0) <= end_ms
    ]
    count = len(window)
    if count < min_trades:
        return None, count
    buy_count = sum(1 for t in window if t.get("direction") == "buy")
    buy_ratio = buy_count / count
    buy_amount = sum(t.get("amount", 0) for t in window if t.get("direction") == "buy")
    sell_amount = sum(t.get("amount", 0) for t in window if t.get("direction") != "buy")
    total_amount = buy_amount + sell_amount
    buy_ratio_volume = buy_amount / total_amount if total_amount > 0 else buy_ratio
    return {
        "buy_ratio": round(buy_ratio, 4),
        "buy_ratio_volume": round(buy_ratio_volume, 4),
        "trade_count": count,
    }, count


def _best_bid_ask(ticker):
    """Return (bid, ask) prices or None if ticker side arrays are empty."""
    bid = ticker.get("bid") or []
    ask = ticker.get("ask") or []
    if not bid or not ask:
        return None
    return float(bid[0]), float(ask[0])


def compute_live_features(ticker, depth, trades, klines):
    if not ticker:
        return None
    ba = _best_bid_ask(ticker)
    if ba is None:
        return None
    bid_px, ask_px = ba
    numeric_inputs = [
        ticker.get("close"),
        ticker.get("high"),
        ticker.get("low"),
        bid_px,
        ask_px,
    ]
    if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in numeric_inputs):
        return None
    total_trades = len(trades)
    buy_count = sum(1 for t in trades if t["direction"] == "buy")
    buy_ratio = buy_count / total_trades if total_trades > 0 else 0.5
    buy_amount = sum(t["amount"] for t in trades if t["direction"] == "buy")
    sell_amount = sum(t["amount"] for t in trades if t["direction"] != "buy")
    total_amount = buy_amount + sell_amount
    buy_ratio_volume = buy_amount / total_amount if total_amount > 0 else buy_ratio
    total_bid = sum(q for _, q in depth.get("bids", []))
    total_ask = sum(q for _, q in depth.get("asks", []))
    total_liq = total_bid + total_ask
    imbalance = (total_bid - total_ask) / total_liq if total_liq > 0 else 0.0
    price = ticker["close"] or 1
    price_range = (ticker["high"] - ticker["low"]) / price
    vol_change = 0.0
    if klines and len(klines) >= 3:
        vols = [k["vol"] for k in klines[-3:]]
        vol_prev = statistics.mean(vols[:-1]) if len(vols) > 1 else vols[0]
        if vol_prev > 0:
            vol_change = (vols[-1] - vol_prev) / vol_prev
    spread = (ask_px - bid_px) / price
    trade_ts = [t["ts"] for t in trades if t.get("ts")]
    unique_trade_ts = len(set(trade_ts))
    trade_window_start_ms = min(trade_ts) if trade_ts else None
    trade_window_end_ms = max(trade_ts) if trade_ts else None
    trade_window_span_ms = (
        trade_window_end_ms - trade_window_start_ms
        if trade_window_start_ms is not None and trade_window_end_ms is not None
        else 0
    )
    quality_flags = []
    if total_trades == 0:
        quality_flags.append("no_trades")
    elif unique_trade_ts <= max(1, total_trades // 5):
        quality_flags.append("stale_trades")
    if total_liq <= 0:
        quality_flags.append("empty_depth")
    if ticker.get("ts", 0) == 0:
        quality_flags.append("missing_timestamp")
    if ask_px < bid_px:
        quality_flags.append("crossed_market")
    ticker_ts = ticker.get("ts", 0)
    depth_ts = depth.get("ts", 0)
    if ticker_ts and depth_ts:
        if abs(ticker_ts - depth_ts) > MAX_ENDPOINT_SKEW_MS:
            quality_flags.append("endpoint_skew")

    return {
        "timestamp": ticker.get("ts", 0),
        "collected_at_ms": int(time.time() * 1000),
        "price": price,
        "buy_ratio": round(buy_ratio, 4),
        "buy_ratio_volume": round(buy_ratio_volume, 4),
        "conviction": round(buy_ratio, 4),
        "imbalance": round(imbalance, 4),
        "volatility": round(price_range, 6),
        "volume_change": round(vol_change, 4),
        "spread": round(spread, 6),
        "trade_count": total_trades,
        "unique_trade_ts": unique_trade_ts,
        "trade_window_start_ms": trade_window_start_ms,
        "trade_window_end_ms": trade_window_end_ms,
        "trade_window_span_ms": trade_window_span_ms,
        "ticker_timestamp_ms": ticker.get("ts", 0),
        "depth_timestamp_ms": depth.get("ts", 0),
        "quality_flags": quality_flags,
    }


# Backward-compatible alias (kline OHLCV features live in features.py)
compute_features = compute_live_features


def stream_features(symbol="btcusdt", n_points=100, delay=1.0):
    hd = HuobiData()
    for i in range(n_points):
        ticker, depth, trades, klines = hd.fetch_all(symbol)
        features = compute_live_features(ticker, depth, trades, klines)
        if features:
            yield features
        elif i < n_points - 1:
            time.sleep(delay * 2)
        if delay > 0 and i < n_points - 1:
            time.sleep(delay)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(line_buffering=True)
    hd = HuobiData()
    t0 = time.time()
    ticker = hd.fetch_ticker("btcusdt")
    if ticker:
        ba = _best_bid_ask(ticker)
        if ba:
            bid_px, ask_px = ba
            sp = (ask_px - bid_px) / ticker["close"] * 100
            print(f"BTCUSDT: {ticker['close']} bid={bid_px} ask={ask_px} spread={sp:.4f}%  ({time.time()-t0:.1f}s)")
        else:
            print(f"BTCUSDT: {ticker['close']} (empty bid/ask)  ({time.time()-t0:.1f}s)")
    print("Streaming...")
    for i, f in enumerate(stream_features("btcusdt", n_points=10, delay=0.0)):
        print(f"[{i}] p={f['price']:.1f} buy={f['buy_ratio']:.3f} imb={f['imbalance']*100:+.1f}% spread={f['spread']*100:.4f}%")
