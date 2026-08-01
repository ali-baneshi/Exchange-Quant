import asyncio
import time
from decimal import Decimal

from exchange_q.domain import BookEvent, RunManifest, TradeEvent
from exchange_q.models import ModelArtifact, NormalizedBornModel
from exchange_q.providers.replay import ReplayProvider
from exchange_q.runner import LiveRunner
from exchange_q.store import V7Store


def _trade(identifier, timestamp, side, provider="replay"):
    return TradeEvent(
        provider=provider,
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
        integrity = store.status(manifest.run_id)["integrity"]
        assert integrity["valid"] is True
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


def test_retroactive_label_trade_is_persisted_and_flags_integrity(tmp_path):
    model = NormalizedBornModel()
    artifact = ModelArtifact(model.model_id, (0.0, 0.5, 1.0, 0.0, 1.0), 10)
    manifest = RunManifest(
        run_id="retro-run",
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
        terminal_slot_limit=5,
    )
    events = [
        _book(100),
        _trade("history-1", 200, "buy"),
        _trade("history-2", 800, "sell"),
        _trade("label-1", 1100, "buy"),
        _trade("label-2", 1500, "sell"),
        _trade("advance", 2500, "buy"),
        TradeEvent(
            provider="replay",
            symbol="btcusdt",
            exchange_trade_id="retro-1",
            exchange_time_ms=1600,
            received_time_ms=2600,
            aggressor_side="sell",
            price=Decimal(100),
            quantity=Decimal(1),
            sequence=99,
            session_id="sess",
        ),
    ]
    store = V7Store(str(tmp_path / "retro.sqlite3"))
    store.create_run(manifest)
    try:
        asyncio.run(LiveRunner(store, ReplayProvider(events), manifest, artifact).run())
        # Lossless raw persistence: the retroactive trade is stored, not dropped.
        retro_count = store.connection.execute(
            """
            SELECT COUNT(*) FROM trades
            WHERE exchange_trade_id = 'retro-1'
            """
        ).fetchone()[0]
        assert retro_count == 1
        # The mutated resolved window is caught by the integrity scan.
        integrity = store.status(manifest.run_id)["integrity"]
        assert integrity["valid"] is False
        assert "label_trade_count_mismatch" in integrity["error_codes"]
        # ... and recorded as continuity evidence.
        gap_reasons = [
            row[0]
            for row in store.connection.execute(
                "SELECT reasons_json FROM continuity_intervals"
            )
        ]
        assert any("retroactive_label_trade" in reasons for reasons in gap_reasons)
    finally:
        store.close()


class _StubProvider:
    def __init__(self, health):
        self._health = health

    def health(self):
        return self._health

    async def close(self):
        return None


def _resolve_run(tmp_path, monkey_health, gaps=(), name="gating-run"):
    from exchange_q.domain import FeatureWindow, Forecast

    model = NormalizedBornModel()
    artifact = ModelArtifact(model.model_id, (0.0, 0.5, 1.0, 0.0, 1.0), 10)
    manifest = RunManifest(
        run_id=name,
        symbol="btcusdt",
        provider="kucoin-sequenced",
        model_artifact_hash=artifact.artifact_hash,
        feature_policy="causal_trade_book_v1",
        label_policy="half_open_streamed_trades_v1",
        primary_metric="per_trade_negative_log_likelihood",
        horizon_ms=1000,
        lookback_ms=1000,
        cadence_ms=1000,
        minimum_label_trades=1,
        target_eligible=1,
        mode="primary",
        decision_lead_ms=100,
        artifact_purpose="primary",
    )
    store = V7Store(str(tmp_path / f"{name}.sqlite3"))
    store.create_run(manifest)
    try:
        store.schedule_slot(name, 5000, 6000)
        features = FeatureWindow(3900, 4900, 2, 1, 1, 0.5, 0.0, 0.001, 0.0)
        store.create_forecast(
            name,
            5000,
            features,
            Forecast("model", 0.5, 0.5),
            artifact.artifact_hash,
            observed_decision_ms=4900,
        )
        store.save_trade(_trade("label-1", 5100, "buy", provider="kucoin-sequenced"))
        for gap in gaps:
            store.record_continuity_gap(
                "kucoin-sequenced",
                "btcusdt",
                gap[0],
                gap[1],
                gap[2],
                complete=False,
                reasons=("test_gap",),
            )
        runner = LiveRunner(store, _StubProvider(monkey_health), manifest, artifact)
        runner._stream_start_ms = 100
        runner._resolve(5000, 6000, 7000)
        row = store.connection.execute(
            "SELECT status FROM forecast_slots WHERE run_id = ? AND slot_start_ms = 5000",
            (name,),
        ).fetchone()
        return row["status"]
    finally:
        store.close()


def _health(**overrides):
    from exchange_q.providers.base import ProviderHealth

    values = {
        "connected": True,
        "last_event_received_ms": 1,
        "reconnects": 0,
        "sequence_gaps": 0,
        "coverage_certifiable": True,
        "unresolved_gaps": 0,
        "clock_uncertainty_ms": 10.0,
    }
    values.update(overrides)
    return ProviderHealth(**values)


def test_recovered_depth_gap_does_not_poison_resolution(tmp_path):
    health = _health(sequence_gaps=1, book_sequence_gaps=1)
    status = _resolve_run(tmp_path, health, name="depth-recovered")
    assert status == "resolved_scoreable"


def test_overlapping_trade_gap_forces_unscoreable(tmp_path):
    status = _resolve_run(
        tmp_path,
        _health(trade_sequence_gaps=1, unresolved_gaps=1),
        gaps=(("trades", 4950, 5050),),
        name="trade-gap-overlap",
    )
    assert status == "resolved_unscoreable"


def test_old_non_overlapping_trade_gap_keeps_slot_scoreable(tmp_path):
    status = _resolve_run(
        tmp_path,
        _health(trade_sequence_gaps=1, unresolved_gaps=1),
        gaps=(("trades", 1000, 2000),),
        name="trade-gap-old",
    )
    assert status == "resolved_scoreable"


def test_mid_stream_stall_fails_run(tmp_path):
    import pytest

    from exchange_q.providers.base import ProviderHealth

    class StallingProvider:
        def __init__(self):
            self._sent = False

        def health(self):
            return ProviderHealth(
                connected=True,
                last_event_received_ms=1,
                reconnects=0,
                sequence_gaps=0,
                coverage_certifiable=True,
                clock_uncertainty_ms=5.0,
                pending_events=0,
                last_ws_received_ms=1,
            )

        async def close(self):
            return None

        async def events(self, symbol):
            if not self._sent:
                self._sent = True
                yield _trade("only", 100, "buy")
            while True:
                await asyncio.sleep(60)
                yield _trade("never", 200, "sell")

    model = NormalizedBornModel()
    artifact = ModelArtifact(model.model_id, (0.0, 0.5, 1.0, 0.0, 1.0), 10)
    manifest = RunManifest(
        run_id="stall-run",
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
        target_eligible=5,
    )
    store = V7Store(str(tmp_path / "stall.sqlite3"))
    store.create_run(manifest)
    try:
        runner = LiveRunner(store, StallingProvider(), manifest, artifact)
        runner.EVENT_POLL_TIMEOUT_S = 0.01
        runner.STALL_TIMEOUT_MS = 1
        with pytest.raises(RuntimeError, match="provider_stalled"):
            asyncio.run(runner.run())
        assert store.status(manifest.run_id)["status"] == "failed"
        sessions = store.connection.execute(
            "SELECT status FROM capture_sessions"
        ).fetchall()
        assert sessions
        assert all(row["status"] == "failed" for row in sessions)
    finally:
        store.close()


def test_backpressure_not_reported_as_provider_stall(tmp_path):
    import pytest

    from exchange_q.providers.base import ProviderHealth

    class BackloggedProvider:
        def __init__(self):
            self._sent = False

        def health(self):
            now = int(time.time() * 1000)
            return ProviderHealth(
                connected=True,
                last_event_received_ms=1,
                reconnects=0,
                sequence_gaps=0,
                coverage_certifiable=True,
                clock_uncertainty_ms=5.0,
                pending_events=512,
                last_ws_received_ms=now,
                queue_dropped_trades=3,
                detail="queue_drop_trade count=3",
            )

        async def close(self):
            return None

        async def events(self, symbol):
            if not self._sent:
                self._sent = True
                yield _trade("only", 100, "buy")
            while True:
                await asyncio.sleep(60)
                yield _trade("never", 200, "sell")

    model = NormalizedBornModel()
    artifact = ModelArtifact(model.model_id, (0.0, 0.5, 1.0, 0.0, 1.0), 10)
    manifest = RunManifest(
        run_id="backpressure-run",
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
        target_eligible=5,
    )
    store = V7Store(str(tmp_path / "backpressure.sqlite3"))
    store.create_run(manifest)
    try:
        runner = LiveRunner(store, BackloggedProvider(), manifest, artifact)
        runner.EVENT_POLL_TIMEOUT_S = 0.01
        runner.BACKPRESSURE_TIMEOUT_MS = 1
        runner.STALL_TIMEOUT_MS = 1
        with pytest.raises(RuntimeError, match="consumer_backpressure"):
            asyncio.run(runner.run())
        assert store.status(manifest.run_id)["status"] == "failed"
    finally:
        store.close()


def test_event_poll_timeout_does_not_kill_async_generator(tmp_path):
    """Regression: wait_for(__anext__) used to cancel the provider generator."""
    from exchange_q.providers.base import ProviderHealth

    class SlowGapProvider:
        def __init__(self):
            self._last_ms = int(time.time() * 1000)

        def health(self):
            return ProviderHealth(
                connected=True,
                last_event_received_ms=self._last_ms,
                reconnects=0,
                sequence_gaps=0,
                coverage_certifiable=True,
                clock_uncertainty_ms=5.0,
            )

        async def close(self):
            return None

        async def events(self, symbol):
            self._last_ms = int(time.time() * 1000)
            yield _book(100)
            yield _trade("1", 200, "buy")
            yield _trade("2", 300, "sell")
            await asyncio.sleep(0.05)  # longer than EVENT_POLL_TIMEOUT_S
            self._last_ms = int(time.time() * 1000)
            yield _trade("3", 1100, "buy")
            yield _trade("4", 1200, "sell")
            yield _trade("5", 1999, "buy")
            yield _trade("6", 2500, "sell")

    model = NormalizedBornModel()
    artifact = ModelArtifact(model.model_id, (0.0, 0.5, 1.0, 0.0, 1.0), 10)
    manifest = RunManifest(
        run_id="poll-gap-run",
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
    store = V7Store(str(tmp_path / "poll-gap.sqlite3"))
    store.create_run(manifest)
    try:
        runner = LiveRunner(store, SlowGapProvider(), manifest, artifact)
        runner.EVENT_POLL_TIMEOUT_S = 0.01
        runner.STALL_TIMEOUT_MS = 60_000
        asyncio.run(runner.run())
        status = store.status(manifest.run_id)
        assert status["status"] == "completed"
        assert status["forecast_counts"].get("resolved_scoreable", 0) >= 1
    finally:
        store.close()


def test_fast_book_stream_persists_everything_and_completes(tmp_path):
    model = NormalizedBornModel()
    artifact = ModelArtifact(model.model_id, (0.0, 0.5, 1.0, 0.0, 1.0), 10)
    manifest = RunManifest(
        run_id="throughput-run",
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
        terminal_slot_limit=None,
    )
    events = [
        _book(100),
        _trade("history-1", 200, "buy"),
        _trade("history-2", 800, "sell"),
        _trade("label-1", 1100, "buy"),
        _trade("label-2", 1500, "sell"),
    ]
    events.extend(_book(100 + index) for index in range(1, 3001))
    events.append(_trade("advance", 3200, "buy"))
    store = V7Store(str(tmp_path / "throughput.sqlite3"))
    store.create_run(manifest)
    try:
        asyncio.run(LiveRunner(store, ReplayProvider(events), manifest, artifact).run())
        book_count = store.connection.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        trade_count = store.connection.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        assert book_count == 3001
        assert trade_count == 5
        assert store.status(manifest.run_id)["status"] == "stopped"
    finally:
        store.close()


def _diagnostic_manifest(run_id, target_eligible=5):
    model = NormalizedBornModel()
    artifact = ModelArtifact(model.model_id, (0.0, 0.5, 1.0, 0.0, 1.0), 10)
    manifest = RunManifest(
        run_id=run_id,
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
        target_eligible=target_eligible,
    )
    return manifest, artifact


def test_stale_book_skips_slot_with_reason(tmp_path):
    manifest, artifact = _diagnostic_manifest("stale-book-run")
    events = [
        _book(100),
        _trade("history-1", 200, "buy"),
        _trade("history-2", 800, "sell"),
        _trade("label-1", 1000, "buy"),
        _trade("label-2", 1500, "sell"),
        _trade("edge", 2000, "buy"),
        _trade("tail", 2500, "sell"),
    ]
    store = V7Store(str(tmp_path / "stale.sqlite3"))
    store.create_run(manifest)
    try:
        asyncio.run(LiveRunner(store, ReplayProvider(events), manifest, artifact).run())
        rows = {
            row["slot_start_ms"]: row
            for row in store.connection.execute(
                "SELECT slot_start_ms, status, exclusion_json FROM forecast_slots"
            ).fetchall()
        }
        assert rows[1000]["status"] == "resolved_scoreable"
        # Slot 2000's feature window ends at 2000 but the newest book is at
        # 100: older than one full lookback, so the slot must be skipped.
        assert rows[2000]["status"] == "skipped"
        assert rows[2000]["exclusion_json"] == '["stale_book"]'
    finally:
        store.close()


def test_stream_exhaustion_reason_on_natural_end(tmp_path):
    manifest, artifact = _diagnostic_manifest("exhaustion-run")
    events = [
        _book(100),
        _trade("history-1", 200, "buy"),
        _trade("history-2", 800, "sell"),
        _trade("label-1", 1000, "buy"),
        _book(1100),
        _trade("label-2", 1500, "sell"),
        _trade("edge", 2000, "buy"),
    ]
    store = V7Store(str(tmp_path / "exhausted.sqlite3"))
    store.create_run(manifest)
    try:
        asyncio.run(LiveRunner(store, ReplayProvider(events), manifest, artifact).run())
        assert store.status("exhaustion-run")["status"] == "stopped"
        cancelled = store.connection.execute(
            "SELECT exclusion_json FROM forecast_slots WHERE status = 'cancelled'"
        ).fetchall()
        assert cancelled
        for row in cancelled:
            assert row["exclusion_json"] == '["provider_stream_exhausted_before_slot_completion"]'
    finally:
        store.close()
