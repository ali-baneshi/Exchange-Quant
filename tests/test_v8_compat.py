import json
import sqlite3

import pytest

from exchange_q.store import V7Store


def _create_v7_database(path: str) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE runs(
            run_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            manifest_json TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL
        );
        CREATE TABLE forecast_slots(
            run_id TEXT NOT NULL,
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
        CREATE TABLE lifecycle_events(
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            slot_start_ms INTEGER,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL
        );
        CREATE TABLE leases(
            run_id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            pid INTEGER NOT NULL,
            heartbeat_ms INTEGER NOT NULL
        );
        """
    )
    manifest = {
        "run_id": "legacy-run",
        "symbol": "btcusdt",
        "provider": "replay",
        "schema_version": 7,
    }
    connection.execute(
        """
        INSERT INTO runs(run_id, status, manifest_json, created_at_ms, updated_at_ms)
        VALUES(?, 'completed', ?, 1, 1)
        """,
        ("legacy-run", json.dumps(manifest)),
    )
    connection.execute("PRAGMA user_version=7")
    connection.commit()
    connection.close()


def test_v7_database_is_read_only(tmp_path):
    path = str(tmp_path / "legacy.sqlite3")
    _create_v7_database(path)
    store = V7Store(path)
    try:
        assert store.legacy_read_only is True
        assert store.schema_version == 7
        status = store.status("legacy-run")
        assert status["run_id"] == "legacy-run"
        with pytest.raises(RuntimeError, match="read-only"):
            store.create_run(
                __import__("exchange_q.domain", fromlist=["RunManifest"]).RunManifest(
                    run_id="new",
                    symbol="btcusdt",
                    provider="replay",
                    model_artifact_hash="hash",
                    feature_policy="causal_trade_book_v1",
                    label_policy="half_open_streamed_trades_v1",
                    primary_metric="per_trade_negative_log_likelihood",
                    horizon_ms=1000,
                    lookback_ms=1000,
                    cadence_ms=1000,
                    minimum_label_trades=2,
                    target_eligible=2,
                    schema_version=7,
                )
            )
    finally:
        store.close()


def test_v7_export_is_allowed(tmp_path):
    path = str(tmp_path / "legacy.sqlite3")
    _create_v7_database(path)
    store = V7Store(path)
    try:
        exported = store.export_run("legacy-run")
        assert exported["schema_version"] == 7
        assert exported["run_id"] == "legacy-run"
    finally:
        store.close()
