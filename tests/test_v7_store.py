import json
import os
import sqlite3
from decimal import Decimal

import pytest

from exchange_q.domain import (
    BookEvent,
    FeatureWindow,
    Forecast,
    ForecastStatus,
    RunManifest,
    TradeEvent,
)
from exchange_q.store import V7Store


def _manifest(run_id="run-1"):
    return RunManifest(
        run_id=run_id,
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
    )


def _trade(identifier, timestamp, side):
    return TradeEvent(
        provider="replay",
        symbol="btcusdt",
        exchange_trade_id=identifier,
        exchange_time_ms=timestamp,
        received_time_ms=timestamp + 1,
        aggressor_side=side,
        price=Decimal(100),
        quantity=Decimal(1),
    )


def test_half_open_labels_and_transactional_resolution(tmp_path):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.create_run(_manifest())
        for event in (
            _trade("before", 999, "sell"),
            _trade("start", 1000, "buy"),
            _trade("inside", 1500, "sell"),
            _trade("end", 2000, "buy"),
        ):
            store.save_trade(event)
        store.mark_coverage("replay", "btcusdt", 1000, 2000, True)
        store.schedule_slot("run-1", 1000, 2000)
        features = FeatureWindow(0, 1000, 1, 0, 1, 0.0, 0.0, 0.001, 0.0)
        store.create_forecast(
            "run-1",
            1000,
            features,
            Forecast("model", 0.5, 0.5),
            "hash",
        )
        label = store.build_label("replay", "btcusdt", 1000, 2000)
        assert label.buy_count == 1
        assert label.sell_count == 1
        status = store.resolve_slot("run-1", 1000, label, 2)
        assert status == ForecastStatus.RESOLVED_SCOREABLE
        assert len(store.eligible_rows("run-1")) == 1
    finally:
        store.close()


def test_active_lease_rejects_second_writer(tmp_path):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.create_run(_manifest())
        store.acquire_lease("run-1", "owner-a", os.getpid())
        with pytest.raises(RuntimeError):
            store.acquire_lease("run-1", "owner-b", os.getpid())
    finally:
        store.close()


def test_terminal_state_cannot_transition(tmp_path):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.create_run(_manifest())
        store.schedule_slot("run-1", 1000, 2000)
        store.skip_slot("run-1", 1000, ["missing"])
        with pytest.raises(ValueError):
            store.skip_slot("run-1", 1000, ["again"])
    finally:
        store.close()


def test_feature_window_is_causal(tmp_path):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.save_book(
            BookEvent(
                provider="replay",
                symbol="btcusdt",
                exchange_time_ms=900,
                received_time_ms=901,
                best_bid=Decimal(99),
                best_ask=Decimal(101),
                bid_quantity=Decimal(6),
                ask_quantity=Decimal(4),
            )
        )
        store.save_trade(_trade("past", 999, "buy"))
        store.save_trade(_trade("boundary", 1000, "sell"))
        features = store.build_features("replay", "btcusdt", 0, 1000)
        assert features.trade_count == 1
        assert features.buy_ratio == 1.0
        assert features.signed_imbalance > 0
    finally:
        store.close()


def test_incompatible_database_schema_is_rejected(tmp_path):
    path = str(tmp_path / "old.sqlite3")
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version=6")
    connection.close()
    with pytest.raises(RuntimeError):
        V7Store(path)


def test_forged_eligible_probability_is_rejected(tmp_path):
    store = V7Store(str(tmp_path / "forged.sqlite3"))
    try:
        store.create_run(_manifest())
        store.mark_coverage("replay", "btcusdt", 1000, 2000, True)
        store.schedule_slot("run-1", 1000, 2000)
        features = FeatureWindow(0, 1000, 2, 1, 1, 0.5, 0.0, 0.001, 0.0)
        store.create_forecast(
            "run-1",
            1000,
            features,
            Forecast("model", 0.5, 0.5),
            "hash",
        )
        label = store.build_label("replay", "btcusdt", 1000, 2000)
        label = label.__class__(
            start_ms=1000,
            end_ms=2000,
            buy_count=1,
            sell_count=1,
            buy_quantity=Decimal(1),
            sell_quantity=Decimal(1),
            coverage_complete=True,
        )
        store.resolve_slot("run-1", 1000, label, 2)
        row = store.connection.execute(
            "SELECT forecast_json FROM forecast_slots WHERE run_id='run-1'"
        ).fetchone()
        forecast = json.loads(row[0])
        forecast["probability_buy"] = 4.0
        store.connection.execute(
            "UPDATE forecast_slots SET forecast_json=? WHERE run_id='run-1'",
            (json.dumps(forecast),),
        )
        with pytest.raises(ValueError):
            store.eligible_rows("run-1")
    finally:
        store.close()


def test_early_resolution_is_quarantined_and_blocks_analysis(tmp_path):
    store = V7Store(str(tmp_path / "quarantined.sqlite3"))
    try:
        store.create_run(_manifest())
        store.save_trade(_trade("label-1", 1000, "buy"))
        store.mark_coverage("replay", "btcusdt", 1000, 2000, True)
        store.schedule_slot("run-1", 1000, 2000)
        features = FeatureWindow(0, 1000, 2, 1, 1, 0.5, 0.0, 0.001, 0.0)
        store.create_forecast(
            "run-1",
            1000,
            features,
            Forecast("model", 0.5, 0.5),
            "hash",
        )
        label = store.build_label("replay", "btcusdt", 1000, 2000)
        store.resolve_slot("run-1", 1000, label, 1)
        store.connection.execute(
            """
            UPDATE lifecycle_events SET created_at_ms = 1500
            WHERE run_id = 'run-1' AND slot_start_ms = 1000
              AND event_type = 'forecast_transition'
              AND json_extract(payload_json, '$.to') IN (
                  'resolved_eligible', 'resolved_scoreable'
              )
            """
        )
        store.save_trade(_trade("label-2", 1500, "sell"))

        integrity = store.status("run-1")["integrity"]
        assert integrity["state"] == "quarantined"
        assert integrity["error_codes"] == {
            "label_resolved_early": 1,
            "label_trade_count_mismatch": 1,
        }
        with pytest.raises(ValueError, match="timing integrity"):
            store.eligible_rows("run-1")
    finally:
        store.close()
