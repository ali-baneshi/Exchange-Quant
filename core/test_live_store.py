#!/usr/bin/env python3

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from live_store import LiveRunStore


class LiveRunStoreTests(unittest.TestCase):
    def test_round_trip_and_duplicate_timestamp_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "run.sqlite3")
            store = LiveRunStore(path)
            state = {"schema_version": 4, "run_id": "run-1"}
            store.save_state(state)
            first = {"id": 0, "timestamp": 100, "buy_ratio": 0.5}
            duplicate = {"id": 1, "timestamp": 100, "buy_ratio": 0.6}
            self.assertTrue(store.save_observation(first))
            self.assertFalse(store.save_observation(duplicate))
            forecast = {"id": "f-1", "step": 0, "status": "pending"}
            store.save_forecast(forecast)
            forecast["status"] = "resolved"
            store.save_forecast(forecast)

            restored = store.load_state()
            document = store.export_document(restored)
            store.close()

            self.assertEqual(document["schema_version"], 4)
            self.assertEqual(len(document["observations"]), 1)
            self.assertEqual(document["predictions"][0]["status"], "resolved")

    def test_trade_batches_deduplicate_and_report_complete_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LiveRunStore(os.path.join(tmp, "run.sqlite3"))
            try:
                trades = [
                    {
                        "trade_id": "a",
                        "ts": 1_000,
                        "direction": "buy",
                        "amount": 1.0,
                        "price": 100.0,
                    },
                    {
                        "trade_id": "b",
                        "ts": 2_000,
                        "direction": "sell",
                        "amount": 1.0,
                        "price": 100.0,
                    },
                ]
                self.assertEqual(store.save_trade_batch("btcusdt", trades, 1_000, 10), 2)
                self.assertEqual(store.save_trade_batch("btcusdt", trades, 2_000, 10), 0)
                window = store.trade_window("btcusdt", 1_000, 2_000, 1.0)
                self.assertTrue(window["capture_complete"])
                self.assertEqual(
                    [trade["trade_id"] for trade in window["trades"]],
                    ["a", "b"],
                )
            finally:
                store.close()

    def test_full_page_with_overlap_is_complete(self):
        """Liquid markets often return a full page; overlap means no missed trades."""
        with tempfile.TemporaryDirectory() as tmp:
            store = LiveRunStore(os.path.join(tmp, "run.sqlite3"))
            try:
                # Full pages whose oldest trade still reaches before the prior capture,
                # while still contributing trades inside [start, end].
                first = [
                    {
                        "trade_id": f"t{i}",
                        "ts": 1_000 + i * 120,
                        "direction": "buy" if i % 2 == 0 else "sell",
                        "amount": 1.0,
                        "price": 100.0,
                    }
                    for i in range(10)
                ]  # oldest=1000 < start; includes 2080.. within window
                second = [
                    {
                        "trade_id": f"u{i}",
                        "ts": 500 + i * 250,
                        "direction": "buy",
                        "amount": 1.0,
                        "price": 100.0,
                    }
                    for i in range(10)
                ]  # oldest=500 < prev capture 2000; includes 2250.. within window
                self.assertEqual(store.save_trade_batch("btcusdt", first, 2_000, 10), 10)
                self.assertEqual(store.save_trade_batch("btcusdt", second, 3_000, 10), 10)
                window = store.trade_window("btcusdt", 2_000, 3_000, 1.0)
                self.assertTrue(window["capture_saturated"])
                self.assertTrue(window["capture_complete"])
                self.assertGreaterEqual(len(window["trades"]), 1)
            finally:
                store.close()

    def test_full_page_without_overlap_is_incomplete(self):
        """A saturated page whose oldest trade is after the prior capture may have holes."""
        with tempfile.TemporaryDirectory() as tmp:
            store = LiveRunStore(os.path.join(tmp, "run.sqlite3"))
            try:
                first = [
                    {
                        "trade_id": "a",
                        "ts": 1_000,
                        "direction": "buy",
                        "amount": 1.0,
                        "price": 100.0,
                    }
                ]
                # Full page of 1 requested, oldest after previous capture frontier.
                second = [
                    {
                        "trade_id": "b",
                        "ts": 2_500,
                        "direction": "sell",
                        "amount": 1.0,
                        "price": 100.0,
                    }
                ]
                store.save_trade_batch("btcusdt", first, 1_000, 2)
                store.save_trade_batch("btcusdt", second, 2_000, 1)
                window = store.trade_window("btcusdt", 1_000, 2_000, 1.0)
                self.assertTrue(window["capture_saturated"])
                self.assertFalse(window["capture_complete"])
            finally:
                store.close()

    def test_capture_gap_overrun_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LiveRunStore(os.path.join(tmp, "run.sqlite3"))
            try:
                trades = [
                    {
                        "trade_id": "a",
                        "ts": 1_000,
                        "direction": "buy",
                        "amount": 1.0,
                        "price": 100.0,
                    },
                    {
                        "trade_id": "b",
                        "ts": 5_000,
                        "direction": "sell",
                        "amount": 1.0,
                        "price": 100.0,
                    },
                ]
                store.save_trade_batch("btcusdt", trades[:1], 1_000, 10)
                store.save_trade_batch("btcusdt", trades[1:], 5_000, 10)
                # sample_interval=1s => allowed max gap 2s; actual gap 4s.
                window = store.trade_window("btcusdt", 1_000, 5_000, 1.0)
                self.assertFalse(window["capture_complete"])
                self.assertEqual(window["capture_max_gap_ms"], 4_000)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
