import asyncio
from decimal import Decimal

from exchange_q.domain import BookEvent, RunManifest, TradeEvent
from exchange_q.models import ModelArtifact, NormalizedBornModel
from exchange_q.providers.replay import ReplayProvider
from exchange_q.runner import LiveRunner
from exchange_q.store import V7Store


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
        sequence=int(identifier.split("-")[-1]) if "-" in identifier else 1,
        session_id="sess",
    )


def _book(timestamp):
    return BookEvent(
        provider="replay",
        symbol="btcusdt",
        exchange_time_ms=timestamp,
        received_time_ms=timestamp + 1,
        best_bid=Decimal(99),
        best_ask=Decimal(101),
        bid_quantity=Decimal(6),
        ask_quantity=Decimal(4),
        sequence=1,
        session_id="sess",
    )


def test_primary_timing_requires_settlement(tmp_path):
    model = NormalizedBornModel()
    artifact = ModelArtifact(model.model_id, (0.0, 0.5, 1.0, 0.0, 1.0), 10, purpose="primary")
    manifest = RunManifest(
        run_id="primary-run",
        symbol="btcusdt",
        provider="replay",
        model_artifact_hash=artifact.artifact_hash,
        feature_policy="causal_trade_book_v1",
        label_policy="half_open_streamed_trades_v1",
        primary_metric="per_trade_negative_log_likelihood",
        horizon_ms=1000,
        lookback_ms=1000,
        cadence_ms=1000,
        minimum_label_trades=2,
        target_eligible=1,
        mode="primary",
        decision_lead_ms=100,
        settlement_delay_ms=500,
        artifact_purpose="primary",
    )
    events = [
        _book(100),
        _trade("history-1", 200, "buy"),
        _trade("history-2", 800, "sell"),
        _trade("label-1", 1100, "buy"),
        _trade("label-2", 1500, "sell"),
        _trade("label-3", 1999, "buy"),
        _trade("after", 2600, "sell"),
    ]
    store = V7Store(str(tmp_path / "primary.sqlite3"))
    store.create_run(manifest)
    try:
        asyncio.run(LiveRunner(store, ReplayProvider(events), manifest, artifact).run())
        row = store.connection.execute(
            """
            SELECT status FROM forecast_slots
            WHERE run_id = ? AND slot_start_ms = 1000
            """,
            (manifest.run_id,),
        ).fetchone()
        assert row["status"] in {"resolved_scoreable", "resolved_unscoreable"}
    finally:
        store.close()


def test_completed_run_cancels_open_slots(tmp_path):
    model = NormalizedBornModel()
    artifact = ModelArtifact(model.model_id, (0.0, 0.5, 1.0, 0.0, 1.0), 10)
    manifest = RunManifest(
        run_id="complete-run",
        symbol="btcusdt",
        provider="replay",
        model_artifact_hash=artifact.artifact_hash,
        feature_policy="causal_trade_book_v1",
        label_policy="half_open_streamed_trades_v1",
        primary_metric="per_trade_negative_log_likelihood",
        horizon_ms=1000,
        lookback_ms=1000,
        cadence_ms=1000,
        minimum_label_trades=2,
        target_eligible=1,
    )
    events = [
        _book(100),
        _trade("history-1", 200, "buy"),
        _trade("history-2", 800, "sell"),
        _trade("label-1", 1000, "buy"),
        _trade("label-2", 1500, "sell"),
        _trade("edge", 2000, "buy"),
        _trade("future-1", 3000, "sell"),
    ]
    store = V7Store(str(tmp_path / "complete.sqlite3"))
    store.create_run(manifest)
    try:
        asyncio.run(LiveRunner(store, ReplayProvider(events), manifest, artifact).run())
        open_slots = store.connection.execute(
            """
            SELECT COUNT(*) FROM forecast_slots
            WHERE run_id = ? AND status IN ('scheduled', 'forecasted', 'awaiting_label')
            """,
            (manifest.run_id,),
        ).fetchone()[0]
        assert open_slots == 0
        assert store.status(manifest.run_id)["status"] == "completed"
    finally:
        store.close()
