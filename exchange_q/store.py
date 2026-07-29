from __future__ import annotations

import json
import math
import os
import sqlite3
import statistics
import time
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from itertools import pairwise
from typing import Any

from exchange_q import IMPLEMENTATION_REVISION, SCHEMA_VERSION
from exchange_q.domain import (
    TERMINAL_FORECAST_STATUSES,
    BookEvent,
    EvidenceSummary,
    FeatureWindow,
    Forecast,
    ForecastStatus,
    Label,
    OPEN_SLOT_STATUSES,
    RunManifest,
    SCOREABLE_STATUSES,
    TradeEvent,
    compute_capture_quality,
    compute_evidence_status,
    forecast_created_statuses,
    resolution_statuses,
    transition_timestamp,
)


ALLOWED_TRANSITIONS = {
    ForecastStatus.SCHEDULED: {
        ForecastStatus.FORECASTED,
        ForecastStatus.CREATED,
        ForecastStatus.SKIPPED,
        ForecastStatus.CANCELLED,
        ForecastStatus.FAILED,
    },
    ForecastStatus.FORECASTED: {
        ForecastStatus.AWAITING_LABEL,
        ForecastStatus.FAILED,
        ForecastStatus.CANCELLED,
    },
    ForecastStatus.AWAITING_LABEL: {
        ForecastStatus.RESOLVED_SCOREABLE,
        ForecastStatus.RESOLVED_UNSCOREABLE,
        ForecastStatus.EXPIRED,
        ForecastStatus.CANCELLED,
        ForecastStatus.FAILED,
    },
    ForecastStatus.CREATED: {
        ForecastStatus.PENDING_LABEL,
        ForecastStatus.FAILED,
    },
    ForecastStatus.PENDING_LABEL: {
        ForecastStatus.RESOLVED_ELIGIBLE,
        ForecastStatus.RESOLVED_INELIGIBLE,
        ForecastStatus.EXPIRED,
        ForecastStatus.FAILED,
    },
}


class V7Store:
    def __init__(self, path: str):
        self.path = path
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        existing_version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        self.schema_version = existing_version or SCHEMA_VERSION
        self.legacy_read_only = existing_version == 7 and SCHEMA_VERSION != 7
        if existing_version not in (0, 7, SCHEMA_VERSION):
            self.connection.close()
            raise RuntimeError(
                f"unsupported SQLite schema version {existing_version}; "
                f"expected 7 or {SCHEMA_VERSION}"
            )
        if self.legacy_read_only:
            self.connection.execute("PRAGMA query_only=ON")
            return
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                manifest_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS leases (
                run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
                owner_id TEXT NOT NULL,
                pid INTEGER NOT NULL,
                heartbeat_ms INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS trades (
                provider TEXT NOT NULL,
                symbol TEXT NOT NULL,
                exchange_trade_id TEXT NOT NULL,
                exchange_time_ms INTEGER NOT NULL,
                received_time_ms INTEGER NOT NULL,
                aggressor_side TEXT NOT NULL CHECK(aggressor_side IN ('buy', 'sell')),
                price TEXT NOT NULL,
                quantity TEXT NOT NULL,
                sequence_no INTEGER,
                session_id TEXT,
                PRIMARY KEY(provider, symbol, exchange_trade_id)
            );
            CREATE INDEX IF NOT EXISTS trades_time
                ON trades(symbol, exchange_time_ms);
            CREATE TABLE IF NOT EXISTS books (
                provider TEXT NOT NULL,
                symbol TEXT NOT NULL,
                exchange_time_ms INTEGER NOT NULL,
                received_time_ms INTEGER NOT NULL,
                data_json TEXT NOT NULL,
                PRIMARY KEY(provider, symbol, exchange_time_ms, received_time_ms)
            );
            CREATE TABLE IF NOT EXISTS coverage (
                provider TEXT NOT NULL,
                symbol TEXT NOT NULL,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,
                complete INTEGER NOT NULL,
                reasons_json TEXT NOT NULL,
                PRIMARY KEY(provider, symbol, start_ms, end_ms)
            );
            CREATE TABLE IF NOT EXISTS forecast_slots (
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                slot_start_ms INTEGER NOT NULL,
                slot_end_ms INTEGER NOT NULL,
                status TEXT NOT NULL,
                model_id TEXT,
                artifact_hash TEXT,
                features_json TEXT,
                forecast_json TEXT,
                label_json TEXT,
                exclusion_json TEXT NOT NULL DEFAULT '[]',
                updated_at_ms INTEGER NOT NULL,
                PRIMARY KEY(run_id, slot_start_ms)
            );
            CREATE TABLE IF NOT EXISTS lifecycle_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                slot_start_ms INTEGER,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS capture_sessions (
                session_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                symbol TEXT NOT NULL,
                stream_kind TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at_ms INTEGER NOT NULL,
                ended_at_ms INTEGER,
                first_sequence INTEGER,
                last_sequence INTEGER,
                detail_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS capture_checkpoints (
                provider TEXT NOT NULL,
                symbol TEXT NOT NULL,
                stream_kind TEXT NOT NULL,
                sequence_no INTEGER NOT NULL,
                exchange_time_ms INTEGER NOT NULL,
                received_time_ms INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                source TEXT NOT NULL,
                PRIMARY KEY(provider, symbol, stream_kind, sequence_no)
            );
            CREATE TABLE IF NOT EXISTS continuity_intervals (
                interval_id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                symbol TEXT NOT NULL,
                stream_kind TEXT NOT NULL,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,
                complete INTEGER NOT NULL,
                first_sequence INTEGER,
                last_sequence INTEGER,
                reasons_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS recovery_attempts (
                attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                symbol TEXT NOT NULL,
                stream_kind TEXT NOT NULL,
                missing_from INTEGER NOT NULL,
                missing_to INTEGER NOT NULL,
                status TEXT NOT NULL,
                recovered_count INTEGER NOT NULL,
                detail TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS clock_samples (
                sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                local_send_ms INTEGER NOT NULL,
                local_receive_ms INTEGER NOT NULL,
                exchange_time_ms INTEGER NOT NULL,
                offset_ms REAL NOT NULL,
                uncertainty_ms REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS provider_certifications (
                certification_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                symbol TEXT NOT NULL,
                adapter_revision TEXT NOT NULL,
                valid INTEGER NOT NULL,
                issued_at_ms INTEGER NOT NULL,
                expires_at_ms INTEGER,
                report_json TEXT NOT NULL
            );
            """
        )
        self.connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self.schema_version = SCHEMA_VERSION

    def close(self) -> None:
        self.connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self._require_writable()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        else:
            self.connection.execute("COMMIT")

    def create_run(self, manifest: RunManifest) -> None:
        self._require_writable()
        now = int(time.time() * 1000)
        with self.transaction() as connection:
            existing_run = connection.execute(
                "SELECT run_id FROM runs WHERE run_id != ? LIMIT 1",
                (manifest.run_id,),
            ).fetchone()
            if existing_run:
                raise RuntimeError(
                    "a database is single-run; use a new database for another run"
                )
            connection.execute(
                """
                INSERT INTO runs(run_id, manifest_json, status, created_at_ms, updated_at_ms)
                VALUES(?, ?, 'created', ?, ?)
                """,
                (manifest.run_id, json.dumps(manifest.to_record(), sort_keys=True), now, now),
            )
            self._append_event(connection, manifest.run_id, None, "run_created", manifest.to_record(), now)

    def set_run_status(self, run_id: str, status: str, detail: str = "") -> None:
        now = int(time.time() * 1000)
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE runs SET status = ?, updated_at_ms = ? WHERE run_id = ?",
                (status, now, run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(run_id)
            self._append_event(
                connection,
                run_id,
                None,
                "run_status",
                {"status": status, "detail": detail},
                now,
            )

    def acquire_lease(self, run_id: str, owner_id: str, pid: int, ttl_ms: int = 30_000) -> None:
        now = int(time.time() * 1000)
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT owner_id, heartbeat_ms FROM leases WHERE run_id = ?", (run_id,)
            ).fetchone()
            if existing and existing["owner_id"] != owner_id and existing["heartbeat_ms"] >= now - ttl_ms:
                raise RuntimeError(f"run {run_id} already has an active writer")
            connection.execute(
                """
                INSERT INTO leases(run_id, owner_id, pid, heartbeat_ms)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    owner_id=excluded.owner_id,
                    pid=excluded.pid,
                    heartbeat_ms=excluded.heartbeat_ms
                """,
                (run_id, owner_id, pid, now),
            )

    def heartbeat(self, run_id: str, owner_id: str) -> None:
        cursor = self.connection.execute(
            "UPDATE leases SET heartbeat_ms = ? WHERE run_id = ? AND owner_id = ?",
            (int(time.time() * 1000), run_id, owner_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("writer lease was lost")

    def release_lease(self, run_id: str, owner_id: str) -> None:
        self.connection.execute(
            "DELETE FROM leases WHERE run_id = ? AND owner_id = ?", (run_id, owner_id)
        )

    def save_trade(self, event: TradeEvent) -> bool:
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO trades(
                provider, symbol, exchange_trade_id, exchange_time_ms,
                received_time_ms, aggressor_side, price, quantity,
                sequence_no, session_id
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.provider,
                event.symbol,
                event.exchange_trade_id,
                event.exchange_time_ms,
                event.received_time_ms,
                event.aggressor_side,
                str(event.price),
                str(event.quantity),
                event.sequence,
                event.session_id,
            ),
        )
        return cursor.rowcount == 1

    def save_book(self, event: BookEvent) -> None:
        self.connection.execute(
            """
            INSERT OR IGNORE INTO books(
                provider, symbol, exchange_time_ms, received_time_ms, data_json
            ) VALUES(?, ?, ?, ?, ?)
            """,
            (
                event.provider,
                event.symbol,
                event.exchange_time_ms,
                event.received_time_ms,
                json.dumps(event.to_record(), sort_keys=True),
            ),
        )

    def mark_coverage(
        self,
        provider: str,
        symbol: str,
        start_ms: int,
        end_ms: int,
        complete: bool,
        reasons: tuple[str, ...] = (),
    ) -> None:
        if complete and reasons:
            raise ValueError("complete coverage cannot contain failure reasons")
        self.connection.execute(
            """
            INSERT INTO coverage(provider, symbol, start_ms, end_ms, complete, reasons_json)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, symbol, start_ms, end_ms) DO UPDATE SET
                complete=excluded.complete,
                reasons_json=excluded.reasons_json
            """,
            (provider, symbol, start_ms, end_ms, int(complete), json.dumps(reasons)),
        )

    def schedule_slot(self, run_id: str, start_ms: int, end_ms: int) -> None:
        now = int(time.time() * 1000)
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO forecast_slots(
                    run_id, slot_start_ms, slot_end_ms, status, updated_at_ms
                ) VALUES(?, ?, ?, ?, ?)
                """,
                (run_id, start_ms, end_ms, ForecastStatus.SCHEDULED, now),
            )
            self._append_event(connection, run_id, start_ms, "slot_scheduled", {"end_ms": end_ms}, now)

    def create_forecast(
        self,
        run_id: str,
        slot_start_ms: int,
        features: FeatureWindow,
        forecast: Forecast,
        artifact_hash: str,
    ) -> None:
        now = int(time.time() * 1000)
        with self.transaction() as connection:
            created_status = (
                ForecastStatus.FORECASTED
                if self.schema_version >= 8
                else ForecastStatus.CREATED
            )
            awaiting_status = (
                ForecastStatus.AWAITING_LABEL
                if self.schema_version >= 8
                else ForecastStatus.PENDING_LABEL
            )
            self._transition(
                connection,
                run_id,
                slot_start_ms,
                created_status,
                {
                    "model_id": forecast.model_id,
                    "artifact_hash": artifact_hash,
                    "features_json": json.dumps(features.to_record(), sort_keys=True),
                    "forecast_json": json.dumps(
                        {
                            "model_id": forecast.model_id,
                            "probability_buy": forecast.probability_buy,
                            "raw_probability_buy": forecast.raw_probability_buy,
                            "diagnostics": forecast.diagnostics,
                        },
                        sort_keys=True,
                    ),
                },
                now,
            )
            self._transition(
                connection,
                run_id,
                slot_start_ms,
                awaiting_status,
                {},
                now,
            )

    def skip_slot(self, run_id: str, slot_start_ms: int, reasons: list[str]) -> None:
        now = int(time.time() * 1000)
        with self.transaction() as connection:
            self._transition(
                connection,
                run_id,
                slot_start_ms,
                ForecastStatus.SKIPPED,
                {"exclusion_json": json.dumps(sorted(set(reasons)))},
                now,
            )

    def resolve_slot(
        self,
        run_id: str,
        slot_start_ms: int,
        label: Label,
        minimum_trades: int,
    ) -> ForecastStatus:
        reasons = list(label.exclusion_reasons)
        if not label.coverage_complete:
            reasons.append("incomplete_coverage")
        if label.trade_count < minimum_trades:
            reasons.append("insufficient_label_trades")
        status = (
            ForecastStatus.RESOLVED_SCOREABLE
            if not reasons
            else ForecastStatus.RESOLVED_UNSCOREABLE
        )
        now = int(time.time() * 1000)
        with self.transaction() as connection:
            self._transition(
                connection,
                run_id,
                slot_start_ms,
                status,
                {
                    "label_json": json.dumps(label.to_record(), sort_keys=True),
                    "exclusion_json": json.dumps(sorted(set(reasons))),
                },
                now,
            )
        return status

    def cancel_open_slots(self, run_id: str, reason: str) -> int:
        now = int(time.time() * 1000)
        cancelled = 0
        open_statuses = tuple(status.value for status in OPEN_SLOT_STATUSES)
        placeholders = ", ".join("?" for _ in open_statuses)
        with self.transaction() as connection:
            rows = connection.execute(
                f"""
                SELECT slot_start_ms, status FROM forecast_slots
                WHERE run_id = ? AND status IN ({placeholders})
                ORDER BY slot_start_ms
                """,
                (run_id, *open_statuses),
            ).fetchall()
            for row in rows:
                self._transition(
                    connection,
                    run_id,
                    row["slot_start_ms"],
                    ForecastStatus.CANCELLED,
                    {"exclusion_json": json.dumps([reason])},
                    now,
                )
                cancelled += 1
        return cancelled

    def build_label(self, provider: str, symbol: str, start_ms: int, end_ms: int) -> Label:
        rows = self.connection.execute(
            """
            SELECT aggressor_side, quantity FROM trades
            WHERE provider = ? AND symbol = ?
              AND exchange_time_ms >= ? AND exchange_time_ms < ?
            """,
            (provider, symbol, start_ms, end_ms),
        ).fetchall()
        coverage = self.connection.execute(
            """
            SELECT complete, reasons_json FROM coverage
            WHERE provider = ? AND symbol = ?
              AND start_ms <= ? AND end_ms >= ?
            ORDER BY (end_ms - start_ms) ASC LIMIT 1
            """,
            (provider, symbol, start_ms, end_ms),
        ).fetchone()
        buy_rows = [row for row in rows if row["aggressor_side"] == "buy"]
        sell_rows = [row for row in rows if row["aggressor_side"] == "sell"]
        return Label(
            start_ms=start_ms,
            end_ms=end_ms,
            buy_count=len(buy_rows),
            sell_count=len(sell_rows),
            buy_quantity=sum((Decimal(row["quantity"]) for row in buy_rows), Decimal(0)),
            sell_quantity=sum((Decimal(row["quantity"]) for row in sell_rows), Decimal(0)),
            coverage_complete=bool(coverage and coverage["complete"]),
            exclusion_reasons=tuple(json.loads(coverage["reasons_json"])) if coverage else ("missing_coverage",),
        )

    def build_features(
        self,
        provider: str,
        symbol: str,
        start_ms: int,
        end_ms: int,
    ) -> FeatureWindow | None:
        trade_rows = self.connection.execute(
            """
            SELECT aggressor_side, price FROM trades
            WHERE provider = ? AND symbol = ?
              AND exchange_time_ms >= ? AND exchange_time_ms < ?
            ORDER BY exchange_time_ms, exchange_trade_id
            """,
            (provider, symbol, start_ms, end_ms),
        ).fetchall()
        book_row = self.connection.execute(
            """
            SELECT data_json FROM books
            WHERE provider = ? AND symbol = ? AND exchange_time_ms < ?
            ORDER BY exchange_time_ms DESC, received_time_ms DESC LIMIT 1
            """,
            (provider, symbol, end_ms),
        ).fetchone()
        if not trade_rows or not book_row:
            return None
        buy_count = sum(row["aggressor_side"] == "buy" for row in trade_rows)
        sell_count = len(trade_rows) - buy_count
        prices = [float(row["price"]) for row in trade_rows]
        log_returns = [
            math.log(current / previous)
            for previous, current in pairwise(prices)
            if previous > 0 and current > 0
        ]
        book = json.loads(book_row["data_json"])
        bid_quantity = Decimal(book["bid_quantity"])
        ask_quantity = Decimal(book["ask_quantity"])
        total_quantity = bid_quantity + ask_quantity
        imbalance = (
            float((bid_quantity - ask_quantity) / total_quantity)
            if total_quantity > 0
            else 0.0
        )
        best_bid = Decimal(book["best_bid"])
        best_ask = Decimal(book["best_ask"])
        midpoint = (best_bid + best_ask) / 2
        return FeatureWindow(
            start_ms=start_ms,
            end_ms=end_ms,
            trade_count=len(trade_rows),
            buy_count=buy_count,
            sell_count=sell_count,
            buy_ratio=buy_count / len(trade_rows),
            signed_imbalance=imbalance,
            spread=float((best_ask - best_bid) / midpoint),
            volatility=statistics.pstdev(log_returns) if len(log_returns) >= 2 else 0.0,
        )

    def status(self, run_id: str) -> dict[str, Any]:
        run = self.connection.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if not run:
            raise KeyError(run_id)
        counts = {
            row["status"]: row["count"]
            for row in self.connection.execute(
                """
                SELECT status, COUNT(*) AS count FROM forecast_slots
                WHERE run_id = ? GROUP BY status
                """,
                (run_id,),
            )
        }
        lease = self.connection.execute(
            "SELECT owner_id, pid, heartbeat_ms FROM leases WHERE run_id = ?", (run_id,)
        ).fetchone()
        integrity = self.run_integrity(run_id)
        manifest = json.loads(run["manifest_json"])
        scoreable = sum(
            counts.get(status.value, 0) for status in SCOREABLE_STATUSES
        )
        unresolved_gaps = self.unresolved_gap_count(
            manifest["provider"], manifest["symbol"]
        )
        evidence = EvidenceSummary(
            integrity_state=integrity["state"],
            capture_quality=compute_capture_quality(
                mode=manifest.get("mode", "diagnostic"),
                unresolved_gaps=unresolved_gaps,
                coverage_certifiable=unresolved_gaps == 0
                and manifest.get("mode") == "primary",
            ),
            evidence_status=compute_evidence_status(
                mode=manifest.get("mode", "diagnostic"),
                scoreable_slots=scoreable,
                unresolved_gaps=unresolved_gaps,
            ),
        )
        return {
            "run_id": run_id,
            "status": run["status"],
            "created_at_ms": run["created_at_ms"],
            "updated_at_ms": run["updated_at_ms"],
            "manifest": manifest,
            "forecast_counts": counts,
            "lease": dict(lease) if lease else None,
            "integrity": integrity,
            "evidence": evidence.to_record(),
        }

    def eligible_rows(self, run_id: str) -> list[dict[str, Any]]:
        status = self.status(run_id)
        if not status["integrity"]["valid"]:
            raise ValueError("run timing integrity is invalid; analysis is blocked")
        manifest = status["manifest"]
        rows = self.connection.execute(
            """
            SELECT slot_start_ms, slot_end_ms, model_id, artifact_hash,
                   features_json, forecast_json, label_json
            FROM forecast_slots
            WHERE run_id = ? AND status = ?
            ORDER BY slot_start_ms
            """,
            (
                run_id,
                ForecastStatus.RESOLVED_SCOREABLE,
            ),
        ).fetchall()
        if not rows and self.schema_version == 7:
            rows = self.connection.execute(
                """
                SELECT slot_start_ms, slot_end_ms, model_id, artifact_hash,
                       features_json, forecast_json, label_json
                FROM forecast_slots
                WHERE run_id = ? AND status = ?
                ORDER BY slot_start_ms
                """,
                (run_id, ForecastStatus.RESOLVED_ELIGIBLE),
            ).fetchall()
        parsed_rows = [
            {
                **dict(row),
                "features": json.loads(row["features_json"]),
                "forecast": json.loads(row["forecast_json"]),
                "label": json.loads(row["label_json"]),
            }
            for row in rows
        ]
        for row in parsed_rows:
            forecast = row["forecast"]
            label = row["label"]
            probability = forecast.get("probability_buy")
            if (
                not isinstance(probability, (int, float))
                or isinstance(probability, bool)
                or not math.isfinite(probability)
                or not 0.0 <= probability <= 1.0
            ):
                raise ValueError("eligible row contains an invalid probability")
            if row["artifact_hash"] != manifest["model_artifact_hash"]:
                raise ValueError("eligible row artifact does not match the run manifest")
            if label.get("coverage_complete") is not True:
                raise ValueError("eligible row does not have complete coverage")
            if label.get("trade_count") != label.get("buy_count", 0) + label.get(
                "sell_count", 0
            ):
                raise ValueError("eligible row label counts do not add up")
            if label["trade_count"] < manifest["minimum_label_trades"]:
                raise ValueError("eligible row does not meet the minimum trade count")
        return parsed_rows

    def run_integrity(self, run_id: str) -> dict[str, Any]:
        run = self.connection.execute(
            "SELECT manifest_json, status FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if not run:
            raise KeyError(run_id)
        manifest = json.loads(run["manifest_json"])
        transitions: dict[tuple[int, str], int] = {}
        for row in self.connection.execute(
            """
            SELECT slot_start_ms, payload_json, created_at_ms
            FROM lifecycle_events
            WHERE run_id = ? AND event_type = 'forecast_transition'
            ORDER BY event_id
            """,
            (run_id,),
        ):
            payload = json.loads(row["payload_json"])
            transitions[(row["slot_start_ms"], payload["to"])] = row["created_at_ms"]

        errors: list[dict[str, Any]] = []
        checked_slots = 0
        for slot in self.connection.execute(
            """
            SELECT slot_start_ms, slot_end_ms, status, forecast_json, label_json
            FROM forecast_slots WHERE run_id = ? ORDER BY slot_start_ms
            """,
            (run_id,),
        ):
            checked_slots += 1
            slot_start = int(slot["slot_start_ms"])
            slot_end = int(slot["slot_end_ms"])
            if slot["forecast_json"]:
                created_at = transition_timestamp(
                    transitions, slot_start, forecast_created_statuses()
                )
                if created_at is None:
                    errors.append(
                        {"code": "missing_forecast_transition", "slot_start_ms": slot_start}
                    )
                elif created_at < slot_start:
                    errors.append(
                        {
                            "code": "forecast_created_early",
                            "slot_start_ms": slot_start,
                            "observed_at_ms": created_at,
                            "required_at_ms": slot_start,
                        }
                    )
            status = ForecastStatus(slot["status"])
            if status in SCOREABLE_STATUSES or status in {
                ForecastStatus.RESOLVED_UNSCOREABLE,
                ForecastStatus.RESOLVED_INELIGIBLE,
            }:
                resolved_at = transition_timestamp(
                    transitions, slot_start, resolution_statuses()
                )
                if resolved_at is None:
                    errors.append(
                        {"code": "missing_resolution_transition", "slot_start_ms": slot_start}
                    )
                elif resolved_at < slot_end:
                    errors.append(
                        {
                            "code": "label_resolved_early",
                            "slot_start_ms": slot_start,
                            "observed_at_ms": resolved_at,
                            "required_at_ms": slot_end,
                        }
                    )
                if not slot["label_json"]:
                    errors.append(
                        {"code": "missing_resolved_label", "slot_start_ms": slot_start}
                    )
                else:
                    persisted_count = json.loads(slot["label_json"])["trade_count"]
                    raw_count = self.connection.execute(
                        """
                        SELECT COUNT(*) FROM trades
                        WHERE provider = ? AND symbol = ?
                          AND exchange_time_ms >= ? AND exchange_time_ms < ?
                        """,
                        (
                            manifest["provider"],
                            manifest["symbol"],
                            slot_start,
                            slot_end,
                        ),
                    ).fetchone()[0]
                    if persisted_count != raw_count:
                        errors.append(
                            {
                                "code": "label_trade_count_mismatch",
                                "slot_start_ms": slot_start,
                                "persisted_count": persisted_count,
                                "raw_count": raw_count,
                            }
                        )

        codes: dict[str, int] = {}
        for error in errors:
            codes[error["code"]] = codes.get(error["code"], 0) + 1
        valid = not errors
        terminal = run["status"] != "running"
        if terminal:
            open_statuses = tuple(status.value for status in OPEN_SLOT_STATUSES)
            placeholders = ", ".join("?" for _ in open_statuses)
            open_count = self.connection.execute(
                f"""
                SELECT COUNT(*) FROM forecast_slots
                WHERE run_id = ? AND status IN ({placeholders})
                """,
                (run_id, *open_statuses),
            ).fetchone()[0]
            if open_count:
                errors.append(
                    {
                        "code": "terminal_run_has_open_slots",
                        "open_slot_count": open_count,
                    }
                )
                codes["terminal_run_has_open_slots"] = open_count
                valid = False
        return {
            "valid": valid,
            "state": (
                "valid"
                if valid and terminal
                else "valid_so_far"
                if valid
                else "quarantined"
            ),
            "checked_slots": checked_slots,
            "error_count": len(errors),
            "error_codes": codes,
            "errors": errors,
        }

    def export_run(self, run_id: str) -> dict[str, Any]:
        self.connection.execute("BEGIN")
        try:
            status = self.status(run_id)
            slots = [
                {
                    **dict(row),
                    "features": json.loads(row["features_json"]) if row["features_json"] else None,
                    "forecast": json.loads(row["forecast_json"]) if row["forecast_json"] else None,
                    "label": json.loads(row["label_json"]) if row["label_json"] else None,
                    "exclusions": json.loads(row["exclusion_json"]),
                }
                for row in self.connection.execute(
                    """
                    SELECT * FROM forecast_slots
                    WHERE run_id = ? ORDER BY slot_start_ms
                    """,
                    (run_id,),
                )
            ]
            lifecycle = [
                {
                    **dict(row),
                    "payload": json.loads(row["payload_json"]),
                }
                for row in self.connection.execute(
                    """
                    SELECT * FROM lifecycle_events
                    WHERE run_id = ? ORDER BY event_id
                    """,
                    (run_id,),
                )
            ]
            return {
                "schema_version": self.schema_version,
                "implementation_revision": IMPLEMENTATION_REVISION,
                **status,
                "forecast_slots": slots,
                "lifecycle_events": lifecycle,
            }
        finally:
            self.connection.execute("ROLLBACK")

    def start_capture_session(
        self,
        session_id: str,
        provider: str,
        symbol: str,
        stream_kind: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO capture_sessions(
                session_id, provider, symbol, stream_kind, status,
                started_at_ms, detail_json
            ) VALUES(?, ?, ?, ?, 'running', ?, ?)
            """,
            (
                session_id,
                provider,
                symbol,
                stream_kind,
                int(time.time() * 1000),
                json.dumps(detail or {}, sort_keys=True),
            ),
        )

    def checkpoint_capture(
        self,
        provider: str,
        symbol: str,
        stream_kind: str,
        sequence_no: int,
        exchange_time_ms: int,
        received_time_ms: int,
        session_id: str,
        source: str = "websocket",
    ) -> bool:
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO capture_checkpoints(
                provider, symbol, stream_kind, sequence_no,
                exchange_time_ms, received_time_ms, session_id, source
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                provider,
                symbol,
                stream_kind,
                sequence_no,
                exchange_time_ms,
                received_time_ms,
                session_id,
                source,
            ),
        )
        self.connection.execute(
            """
            UPDATE capture_sessions
            SET first_sequence=COALESCE(first_sequence, ?), last_sequence=?
            WHERE session_id=?
            """,
            (sequence_no, sequence_no, session_id),
        )
        return cursor.rowcount == 1

    def record_recovery(
        self,
        provider: str,
        symbol: str,
        stream_kind: str,
        missing_from: int,
        missing_to: int,
        status: str,
        recovered_count: int,
        detail: str = "",
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO recovery_attempts(
                provider, symbol, stream_kind, missing_from, missing_to,
                status, recovered_count, detail, created_at_ms
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                provider,
                symbol,
                stream_kind,
                missing_from,
                missing_to,
                status,
                recovered_count,
                detail,
                int(time.time() * 1000),
            ),
        )

    def record_clock_sample(
        self,
        provider: str,
        local_send_ms: int,
        local_receive_ms: int,
        exchange_time_ms: int,
    ) -> None:
        midpoint = (local_send_ms + local_receive_ms) / 2
        self.connection.execute(
            """
            INSERT INTO clock_samples(
                provider, local_send_ms, local_receive_ms, exchange_time_ms,
                offset_ms, uncertainty_ms
            ) VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                provider,
                local_send_ms,
                local_receive_ms,
                exchange_time_ms,
                exchange_time_ms - midpoint,
                (local_receive_ms - local_send_ms) / 2,
            ),
        )

    def record_continuity_gap(
        self,
        provider: str,
        symbol: str,
        stream_kind: str,
        start_ms: int,
        end_ms: int,
        *,
        complete: bool,
        first_sequence: int | None = None,
        last_sequence: int | None = None,
        reasons: tuple[str, ...] = (),
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO continuity_intervals(
                provider, symbol, stream_kind, start_ms, end_ms, complete,
                first_sequence, last_sequence, reasons_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                provider,
                symbol,
                stream_kind,
                start_ms,
                end_ms,
                int(complete),
                first_sequence,
                last_sequence,
                json.dumps(list(reasons)),
            ),
        )

    def unresolved_gap_count(self, provider: str, symbol: str) -> int:
        if self.schema_version < 8:
            return 0
        row = self.connection.execute(
            """
            SELECT COUNT(*) FROM continuity_intervals
            WHERE provider = ? AND symbol = ? AND complete = 0
            """,
            (provider, symbol),
        ).fetchone()
        return int(row[0]) if row else 0

    def interval_has_unresolved_gap(
        self, provider: str, symbol: str, start_ms: int, end_ms: int
    ) -> bool:
        if self.schema_version < 8:
            return False
        row = self.connection.execute(
            """
            SELECT 1 FROM continuity_intervals
            WHERE provider = ? AND symbol = ? AND complete = 0
              AND start_ms < ? AND end_ms > ?
            LIMIT 1
            """,
            (provider, symbol, end_ms, start_ms),
        ).fetchone()
        return row is not None

    def save_provider_certification(
        self,
        certification_id: str,
        provider: str,
        symbol: str,
        adapter_revision: str,
        valid: bool,
        report: dict[str, Any],
        *,
        expires_at_ms: int | None = None,
    ) -> None:
        self._require_writable()
        self.connection.execute(
            """
            INSERT OR REPLACE INTO provider_certifications(
                certification_id, provider, symbol, adapter_revision, valid,
                issued_at_ms, expires_at_ms, report_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                certification_id,
                provider,
                symbol.lower(),
                adapter_revision,
                int(valid),
                int(time.time() * 1000),
                expires_at_ms,
                json.dumps(report, sort_keys=True),
            ),
        )

    def _require_writable(self) -> None:
        if self.legacy_read_only:
            raise RuntimeError(
                "schema-v7 databases are read-only under schema v8; "
                "export or inspect them instead of resuming"
            )

    def _transition(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        slot_start_ms: int,
        new_status: ForecastStatus,
        updates: dict[str, Any],
        now: int,
    ) -> None:
        row = connection.execute(
            "SELECT status FROM forecast_slots WHERE run_id = ? AND slot_start_ms = ?",
            (run_id, slot_start_ms),
        ).fetchone()
        if not row:
            raise KeyError((run_id, slot_start_ms))
        current = ForecastStatus(row["status"])
        if current in TERMINAL_FORECAST_STATUSES:
            raise ValueError(f"terminal slot cannot transition from {current}")
        if new_status not in ALLOWED_TRANSITIONS.get(current, set()):
            raise ValueError(f"illegal forecast transition {current} -> {new_status}")
        assignments = ["status = ?", "updated_at_ms = ?"]
        parameters: list[Any] = [new_status, now]
        for column, value in updates.items():
            assignments.append(f"{column} = ?")
            parameters.append(value)
        parameters.extend([run_id, slot_start_ms])
        connection.execute(
            f"""
            UPDATE forecast_slots SET {", ".join(assignments)}
            WHERE run_id = ? AND slot_start_ms = ?
            """,
            parameters,
        )
        self._append_event(
            connection,
            run_id,
            slot_start_ms,
            "forecast_transition",
            {"from": current, "to": new_status},
            now,
        )

    @staticmethod
    def _append_event(connection, run_id, slot_start_ms, event_type, payload, now):
        connection.execute(
            """
            INSERT INTO lifecycle_events(
                run_id, slot_start_ms, event_type, payload_json, created_at_ms
            ) VALUES(?, ?, ?, ?, ?)
            """,
            (run_id, slot_start_ms, event_type, json.dumps(payload, sort_keys=True), now),
        )
