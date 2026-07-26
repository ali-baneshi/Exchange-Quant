#!/usr/bin/env python3

"""Unit tests for data_historical ordering contract (no network)."""

import json
import os
import tempfile
import unittest
from unittest import mock

import data_historical as dh


def _candle(cid, close=100.0):
    return {
        "id": cid,
        "open": close,
        "close": close,
        "high": close + 1,
        "low": close - 1,
        "amount": 1.0,
        "vol": 1.0,
        "count": 1,
    }


class TestAscendingContract(unittest.TestCase):
    def test_to_ascending_sorts_and_dedupes(self):
        raw = [_candle(3), _candle(1), _candle(2), _candle(2, close=200)]
        asc = dh.to_ascending(raw)
        self.assertEqual([c["id"] for c in asc], [1, 2, 3])
        self.assertEqual(asc[1]["close"], 200.0)

    def test_newest_n_keeps_latest_window(self):
        # Simulate legacy newest-first cache larger than n
        legacy_newest_first = [_candle(i) for i in range(10, 0, -1)]  # 10..1
        window = dh.newest_n(legacy_newest_first, 5)
        self.assertEqual([c["id"] for c in window], [6, 7, 8, 9, 10])

    def test_parse_klines_ascending_no_reverse_bug(self):
        raw = [_candle(5), _candle(1), _candle(3)]
        candles = dh.parse_klines(raw)
        self.assertEqual([c["ts"] for c in candles], [1, 3, 5])
        tv, ho = dh.held_out_split(candles)
        self.assertEqual(ho[-1]["ts"], 5)

    def test_to_gate_pair_known_quotes(self):
        self.assertEqual(dh.to_gate_pair("btcusdt"), "BTC_USDT")
        self.assertEqual(dh.to_gate_pair("dogeusdt"), "DOGE_USDT")
        self.assertEqual(dh.to_gate_pair("ethbtc"), "ETH_BTC")
        self.assertEqual(dh.to_gate_pair("BTC_USDT"), "BTC_USDT")

    def test_fetch_uses_newest_slice_from_oversized_cache(self):
        oversized = [_candle(i) for i in range(1, 21)]  # ascending 1..20
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "btcusdt_15min.json")
            with mock.patch.object(dh, "_CACHE_DIR", tmp):
                with mock.patch.object(dh, "_refresh_cache_tail", side_effect=lambda _s, _p, c: c):
                    with open(path, "w") as f:
                        json.dump(oversized, f)
                    got = dh.fetch_klines_range("btcusdt", "15min", 8)
        self.assertEqual([c["id"] for c in got], list(range(13, 21)))

    def test_held_out_split_requires_minimum_candles(self):
        with self.assertRaises(ValueError):
            dh.held_out_split([_candle(1)])

    def test_held_out_split_guarantees_min_held_out(self):
        candles = [_candle(i) for i in range(1, 6)]
        tv, ho = dh.held_out_split(candles, min_held_out=1)
        self.assertGreaterEqual(len(ho), 1)
        self.assertEqual(len(tv) + len(ho), 5)


if __name__ == "__main__":
    unittest.main()
