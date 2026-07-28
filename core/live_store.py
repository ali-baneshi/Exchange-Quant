#!/usr/bin/env python3

"""Durable SQLite storage for live evaluation runs."""

import json
import os
import sqlite3
import time
import hashlib


class LiveRunStore:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS run_state (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                data_json TEXT NOT NULL,
                updated_at_ms INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observations (
                observation_id TEXT PRIMARY KEY,
                sequence_no INTEGER NOT NULL,
                exchange_timestamp INTEGER,
                data_json TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS observations_run_timestamp
                ON observations(exchange_timestamp)
                WHERE exchange_timestamp IS NOT NULL AND exchange_timestamp != 0;
            CREATE TABLE IF NOT EXISTS forecasts (
                forecast_id TEXT PRIMARY KEY,
                sequence_no INTEGER NOT NULL,
                status TEXT NOT NULL,
                data_json TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS forecasts_one_pending
                ON forecasts(status) WHERE status = 'pending';
            CREATE TABLE IF NOT EXISTS trades (
                symbol TEXT NOT NULL,
                trade_key TEXT NOT NULL,
                exchange_timestamp INTEGER NOT NULL,
                captured_at_ms INTEGER NOT NULL,
                data_json TEXT NOT NULL,
                PRIMARY KEY(symbol, trade_key)
            );
            CREATE INDEX IF NOT EXISTS trades_symbol_timestamp
                ON trades(symbol, exchange_timestamp);
            CREATE TABLE IF NOT EXISTS trade_capture_batches (
                capture_id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                captured_at_ms INTEGER NOT NULL,
                requested_size INTEGER NOT NULL,
                received_count INTEGER NOT NULL,
                oldest_trade_ms INTEGER,
                newest_trade_ms INTEGER,
                saturated INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS store_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS trade_capture_batches_symbol_time
                ON trade_capture_batches(symbol, captured_at_ms);
            """
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO store_metadata(key, value) VALUES('store_version', '2')"
        )
        self.conn.commit()

    def close(self):
        self.conn.close()

    def save_state(self, state):
        payload = json.dumps(state, sort_keys=True, separators=(",", ":"))
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO run_state(singleton, data_json, updated_at_ms)
                VALUES(1, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    data_json=excluded.data_json,
                    updated_at_ms=excluded.updated_at_ms
                """,
                (payload, int(time.time() * 1000)),
            )

    def load_state(self):
        row = self.conn.execute(
            "SELECT data_json FROM run_state WHERE singleton = 1"
        ).fetchone()
        return json.loads(row[0]) if row else None

    def save_observation(self, observation):
        payload = json.dumps(observation, sort_keys=True, separators=(",", ":"))
        observation_id = str(observation["id"])
        exchange_timestamp = observation.get("timestamp")
        try:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO observations(
                        observation_id, sequence_no, exchange_timestamp, data_json
                    ) VALUES(?, ?, ?, ?)
                    """,
                    (
                        observation_id,
                        int(observation.get("id", 0)),
                        int(exchange_timestamp) if exchange_timestamp else None,
                        payload,
                    ),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def save_forecast(self, forecast):
        payload = json.dumps(forecast, sort_keys=True, separators=(",", ":"))
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO forecasts(forecast_id, sequence_no, status, data_json)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(forecast_id) DO UPDATE SET
                    status=excluded.status,
                    data_json=excluded.data_json
                """,
                (
                    str(forecast["id"]),
                    int(forecast.get("step", 0)),
                    str(forecast.get("status", "unknown")),
                    payload,
                ),
            )

    @staticmethod
    def _trade_key(trade):
        trade_id = trade.get("trade_id")
        if trade_id is not None:
            return f"id:{trade_id}"
        raw = json.dumps(
            {
                "ts": trade.get("ts"),
                "direction": trade.get("direction"),
                "amount": trade.get("amount"),
                "price": trade.get("price"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"fingerprint:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"

    def save_trade_batch(self, symbol, trades, captured_at_ms, requested_size):
        """Persist a raw exchange response and deduplicate its individual trades."""
        normalized = [
            trade for trade in trades
            if isinstance(trade.get("ts"), (int, float)) and int(trade["ts"]) > 0
        ]
        timestamps = [int(trade["ts"]) for trade in normalized]
        inserted = 0
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO trade_capture_batches(
                    symbol, captured_at_ms, requested_size, received_count,
                    oldest_trade_ms, newest_trade_ms, saturated
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    int(captured_at_ms),
                    int(requested_size),
                    len(normalized),
                    min(timestamps) if timestamps else None,
                    max(timestamps) if timestamps else None,
                    int(len(normalized) >= requested_size),
                ),
            )
            for trade in normalized:
                cursor = self.conn.execute(
                    """
                    INSERT OR IGNORE INTO trades(
                        symbol, trade_key, exchange_timestamp, captured_at_ms, data_json
                    ) VALUES(?, ?, ?, ?, ?)
                    """,
                    (
                        symbol,
                        self._trade_key(trade),
                        int(trade["ts"]),
                        int(captured_at_ms),
                        json.dumps(trade, sort_keys=True, separators=(",", ":")),
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    def trade_window(self, symbol, start_ms, end_ms, sample_interval_s):
        """Return locally captured forward trades and conservative coverage metadata.

        A full-page (saturated) response is only coverage-breaking when its oldest
        trade is newer than the previous capture frontier — i.e. trades may have
        fallen off the page between polls. A full page that still overlaps the
        prior frontier is expected on liquid symbols and does not by itself make
        the label incomplete.
        """
        trades = [
            json.loads(row[0])
            for row in self.conn.execute(
                """
                SELECT data_json FROM trades
                WHERE symbol = ? AND exchange_timestamp >= ? AND exchange_timestamp <= ?
                ORDER BY exchange_timestamp, trade_key
                """,
                (symbol, int(start_ms), int(end_ms)),
            )
        ]
        expected_gap_ms = max(1, int(float(sample_interval_s) * 1000))
        batches = self.conn.execute(
            """
            SELECT captured_at_ms, saturated, oldest_trade_ms, newest_trade_ms
            FROM trade_capture_batches
            WHERE symbol = ? AND captured_at_ms >= ? AND captured_at_ms <= ?
            ORDER BY captured_at_ms
            """,
            (
                symbol,
                int(start_ms - expected_gap_ms),
                int(end_ms + expected_gap_ms),
            ),
        ).fetchall()
        capture_times = [row[0] for row in batches]
        max_gap = max(
            [capture_times[index] - capture_times[index - 1] for index in range(1, len(capture_times))],
            default=0,
        )
        saturated_hole = False
        failure_reasons = []
        for index, row in enumerate(batches):
            saturated = row[1]
            oldest_trade_ms = row[2]
            if not saturated or oldest_trade_ms is None or index == 0:
                continue
            previous_newest_ms = batches[index - 1][3]
            if (
                previous_newest_ms is not None
                and int(oldest_trade_ms) > int(previous_newest_ms)
            ):
                saturated_hole = True
                failure_reasons.append("saturated_page_gap")
                break
        complete = bool(trades and batches) and not saturated_hole
        if not trades:
            failure_reasons.append("no_window_trades")
        if not batches:
            failure_reasons.append("no_capture_batches")
        if capture_times:
            if capture_times[0] > start_ms + expected_gap_ms:
                complete = False
                failure_reasons.append("missing_start_boundary")
            if capture_times[-1] < end_ms - expected_gap_ms:
                complete = False
                failure_reasons.append("missing_end_boundary")
            if max_gap > expected_gap_ms * 2:
                complete = False
                failure_reasons.append("capture_gap")
            first_saturated, first_oldest = batches[0][1], batches[0][2]
            if first_saturated and first_oldest is not None and first_oldest > start_ms:
                complete = False
                failure_reasons.append("saturated_start_not_covered")
        return {
            "trades": trades,
            "capture_complete": complete,
            "capture_batch_count": len(batches),
            "capture_max_gap_ms": max_gap,
            "capture_saturated": any(row[1] for row in batches),
            "capture_failure_reasons": sorted(set(failure_reasons)),
        }

    def prune_trades_before(self, cutoff_ms):
        with self.conn:
            self.conn.execute(
                "DELETE FROM trades WHERE captured_at_ms < ?",
                (int(cutoff_ms),),
            )
            self.conn.execute(
                "DELETE FROM trade_capture_batches WHERE captured_at_ms < ?",
                (int(cutoff_ms),),
            )

    def checkpoint(self, truncate=False):
        mode = "TRUNCATE" if truncate else "PASSIVE"
        return self.conn.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()

    def database_size_bytes(self):
        total = 0
        for suffix in ("", "-wal", "-shm"):
            try:
                total += os.path.getsize(self.path + suffix)
            except OSError:
                pass
        return total

    def export_document(self, state):
        observations = [
            json.loads(row[0])
            for row in self.conn.execute(
                "SELECT data_json FROM observations ORDER BY sequence_no"
            )
        ]
        predictions = [
            json.loads(row[0])
            for row in self.conn.execute(
                "SELECT data_json FROM forecasts ORDER BY sequence_no"
            )
        ]
        document = dict(state)
        document["observations"] = observations
        document["predictions"] = predictions
        return document
