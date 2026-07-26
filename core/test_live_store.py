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


if __name__ == "__main__":
    unittest.main()
