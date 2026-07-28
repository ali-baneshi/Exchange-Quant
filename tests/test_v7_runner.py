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
    )


def test_replay_run_creates_one_causal_eligible_forecast(tmp_path):
    model = NormalizedBornModel()
    artifact = ModelArtifact(model.model_id, (0.0, 0.5, 1.0, 0.0, 1.0), 10)
    manifest = RunManifest(
        run_id="replay-run",
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
        _book(900),
        _trade("boundary-start", 1000, "buy"),
        _trade("label-2", 1500, "sell"),
        _trade("boundary-end", 2000, "buy"),
    ]
    store = V7Store(str(tmp_path / "run.sqlite3"))
    store.create_run(manifest)
    try:
        runner = LiveRunner(store, ReplayProvider(events), manifest, artifact)
        asyncio.run(runner.run())
        rows = store.eligible_rows(manifest.run_id)
        assert len(rows) == 1
        assert rows[0]["features"]["end_ms"] == 1000
        assert rows[0]["label"]["buy_count"] == 1
        assert rows[0]["label"]["sell_count"] == 1
        status = store.status(manifest.run_id)
        assert status["status"] == "completed"
        assert status["lease"] is None
    finally:
        store.close()


def test_resume_continues_after_terminal_slot_without_duplicate(tmp_path):
    model = NormalizedBornModel()
    artifact = ModelArtifact(model.model_id, (0.0, 0.5, 1.0, 0.0, 1.0), 10)
    manifest = RunManifest(
        run_id="resume-run",
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
        target_eligible=2,
    )
    database = str(tmp_path / "resume.sqlite3")
    store = V7Store(database)
    store.create_run(manifest)
    first_events = [
        _book(100),
        _trade("h1", 200, "buy"),
        _trade("h2", 800, "sell"),
        _trade("l1", 1000, "buy"),
        _trade("l2", 1500, "sell"),
        _trade("edge", 2000, "buy"),
    ]
    asyncio.run(
        LiveRunner(store, ReplayProvider(first_events), manifest, artifact).run()
    )
    second_events = [
        _book(2100),
        _trade("h3", 2200, "buy"),
        _trade("h4", 2800, "sell"),
        _trade("l3", 3000, "buy"),
        _trade("l4", 3500, "sell"),
        _trade("edge-2", 4000, "buy"),
    ]
    asyncio.run(LiveRunner(store, ReplayProvider(second_events), manifest, artifact).run())
    try:
        rows = store.eligible_rows(manifest.run_id)
        assert len(rows) == 2
        assert len({row["slot_start_ms"] for row in rows}) == 2
    finally:
        store.close()


def test_terminal_slot_limit_is_a_hard_bound_during_catch_up(tmp_path):
    model = NormalizedBornModel()
    artifact = ModelArtifact(model.model_id, (0.0, 0.5, 1.0, 0.0, 1.0), 10)
    manifest = RunManifest(
        run_id="bounded-run",
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
        target_eligible=100,
        terminal_slot_limit=2,
    )
    events = [
        _trade("first", 100, "buy"),
        _trade("jump", 10_000, "sell"),
    ]
    store = V7Store(str(tmp_path / "bounded.sqlite3"))
    store.create_run(manifest)
    try:
        asyncio.run(LiveRunner(store, ReplayProvider(events), manifest, artifact).run())
        status = store.status(manifest.run_id)
        assert status["status"] == "diagnostic_limit"
        assert sum(status["forecast_counts"].values()) == 2
        assert status["forecast_counts"] == {"skipped": 2}
    finally:
        store.close()


def test_live_scheduling_uses_receipt_time_to_avoid_stale_slot_catch_up(tmp_path):
    model = NormalizedBornModel()
    artifact = ModelArtifact(model.model_id, (0.0, 0.5, 1.0, 0.0, 1.0), 10)
    manifest = RunManifest(
        run_id="receipt-clock-run",
        symbol="btcusdt",
        provider="replay",
        model_artifact_hash=artifact.artifact_hash,
        feature_policy="causal_trade_book_v1",
        label_policy="half_open_streamed_trades_v1",
        primary_metric="per_trade_negative_log_likelihood",
        horizon_ms=1000,
        lookback_ms=1000,
        cadence_ms=1000,
        minimum_label_trades=1,
        target_eligible=100,
        terminal_slot_limit=1,
    )
    stale_exchange_event = TradeEvent(
        provider="replay",
        symbol="btcusdt",
        exchange_trade_id="stale",
        exchange_time_ms=100,
        received_time_ms=10_100,
        aggressor_side="buy",
        price=Decimal(100),
        quantity=Decimal(1),
    )
    next_event = TradeEvent(
        provider="replay",
        symbol="btcusdt",
        exchange_trade_id="next",
        exchange_time_ms=200,
        received_time_ms=11_100,
        aggressor_side="sell",
        price=Decimal(100),
        quantity=Decimal(1),
    )
    store = V7Store(str(tmp_path / "receipt-clock.sqlite3"))
    store.create_run(manifest)
    try:
        asyncio.run(
            LiveRunner(
                store,
                ReplayProvider([stale_exchange_event, next_event]),
                manifest,
                artifact,
            ).run()
        )
        slots = store.connection.execute(
            """
            SELECT slot_start_ms, status FROM forecast_slots
            WHERE run_id = ? ORDER BY slot_start_ms
            """,
            (manifest.run_id,),
        ).fetchall()
        assert [(row["slot_start_ms"], row["status"]) for row in slots] == [
            (11_000, "skipped")
        ]
    finally:
        store.close()
