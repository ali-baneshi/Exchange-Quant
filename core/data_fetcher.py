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
from concurrent.futures import ThreadPoolExecutor, as_completed

HUOBI_BASE = "https://api.huobi.pro"
_CTX = ssl.create_default_context()


def _api_get(url, timeout=3):
    host = "api.huobi.pro"
    path = url.split("api.huobi.pro")[-1]
    for attempt in range(2):
        try:
            conn = http.client.HTTPSConnection(host, timeout=timeout, context=_CTX)
            conn.request("GET", path, headers={"User-Agent": "Mozilla/5.0", "Connection": "close"})
            resp = conn.getresponse()
            data = json.loads(resp.read())
            conn.close()
            if data.get("status") == "ok":
                return data
            return None
        except Exception:
            if attempt < 1:
                time.sleep(0.2)
            continue
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
        }

    def fetch_trades(self, symbol="btcusdt", size=50):
        raw = _api_get(
            f"{HUOBI_BASE}/market/history/trade?symbol={symbol}&size={min(size, 100)}"
        )
        if raw is None:
            return []
        trades = []
        for item in raw.get("data", []):
            for t in item.get("data", []):
                trades.append({
                    "price": float(t.get("price", 0)),
                    "amount": float(t.get("amount", 0)),
                    "ts": t.get("ts", 0),
                    "direction": t.get("direction", "buy"),
                })
        return trades[:size]

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
        return result

    def fetch_all(self, symbol="btcusdt"):
        with ThreadPoolExecutor(max_workers=4) as ex:
            ft = {ex.submit(self.fetch_ticker, symbol): "ticker",
                  ex.submit(self.fetch_depth, symbol, 20): "depth",
                  ex.submit(self.fetch_trades, symbol, 30): "trades",
                  ex.submit(self.fetch_klines, symbol, "1min", 5): "klines"}
            results = {}
            for fut in as_completed(ft):
                results[ft[fut]] = fut.result()
        return (
            results.get("ticker"),
            results.get("depth", {"bids": [], "asks": []}),
            results.get("trades", []),
            results.get("klines", []),
        )

    def fetch_features(self, symbol="btcusdt", max_attempts=2):
        for _ in range(max_attempts):
            t, d, tr, k = self.fetch_all(symbol)
            f = compute_features(t, d, tr, k)
            if f is not None:
                return f
            time.sleep(1)
        return None


def compute_features(ticker, depth, trades, klines):
    if not ticker:
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
    spread = (ticker["ask"][0] - ticker["bid"][0]) / price
    trade_ts = [t["ts"] for t in trades if t.get("ts")]
    unique_trade_ts = len(set(trade_ts))
    quality_flags = []
    if total_trades == 0:
        quality_flags.append("no_trades")
    elif unique_trade_ts <= max(1, total_trades // 5):
        quality_flags.append("stale_trades")
    if total_liq <= 0:
        quality_flags.append("empty_depth")
    if ticker.get("ts", 0) == 0:
        quality_flags.append("missing_timestamp")

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
        "quality_flags": quality_flags,
    }


def stream_features(symbol="btcusdt", n_points=100, delay=1.0):
    hd = HuobiData()
    for i in range(n_points):
        ticker, depth, trades, klines = hd.fetch_all(symbol)
        features = compute_features(ticker, depth, trades, klines)
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
        sp = (ticker["ask"][0] - ticker["bid"][0]) / ticker["close"] * 100
        print(f"BTCUSDT: {ticker['close']} bid={ticker['bid'][0]} ask={ticker['ask'][0]} spread={sp:.4f}%  ({time.time()-t0:.1f}s)")
    print("Streaming...")
    for i, f in enumerate(stream_features("btcusdt", n_points=10, delay=0.0)):
        print(f"[{i}] p={f['price']:.1f} buy={f['buy_ratio']:.3f} imb={f['imbalance']*100:+.1f}% spread={f['spread']*100:.4f}%")
