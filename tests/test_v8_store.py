import pytest

from exchange_q.domain import FeatureWindow, ForecastStatus, RunManifest
from exchange_q.store import V7Store


def _manifest(run_id="v8-run"):
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


def test_cancel_open_slots_on_stop(tmp_path):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.create_run(_manifest())
        store.schedule_slot("v8-run", 1000, 2000)
        store.schedule_slot("v8-run", 2000, 3000)
        cancelled = store.cancel_open_slots("v8-run", "operator_stop")
        assert cancelled == 2
        counts = store.status("v8-run")["forecast_counts"]
        assert counts.get(ForecastStatus.CANCELLED.value) == 2
    finally:
        store.close()


def test_capture_ledger_writes(tmp_path):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.start_capture_session("sess-trades", "replay", "btcusdt", "trades")
        assert store.checkpoint_capture("replay", "btcusdt", "trades", 1, 100, 101, "sess-trades")
        store.record_recovery("replay", "btcusdt", "trades", 2, 3, "success", 2)
        store.record_clock_sample("replay", 100, 120, 110)
        store.record_continuity_gap(
            "replay",
            "btcusdt",
            "trades",
            100,
            200,
            complete=False,
            reasons=("test_gap",),
        )
        assert store.unresolved_gap_count("replay", "btcusdt") == 1
    finally:
        store.close()


def test_interval_gap_query_uses_ms_bounds_and_stream_kind(tmp_path):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.record_continuity_gap(
            "kucoin-sequenced",
            "btcusdt",
            "trades",
            105,
            108,
            complete=False,
            first_sequence=6,
            last_sequence=7,
            reasons=("unrecovered_trade_gap",),
        )
        store.record_continuity_gap(
            "kucoin-sequenced",
            "btcusdt",
            "trades",
            5000,
            6000,
            complete=False,
            reasons=("late_trade_event",),
        )
        store.record_continuity_gap(
            "kucoin-sequenced",
            "btcusdt",
            "books",
            105,
            108,
            complete=True,
            reasons=("recovered_depth",),
        )
        assert store.interval_has_unresolved_gap("kucoin-sequenced", "btcusdt", 100, 200) is True
        assert store.interval_has_unresolved_gap("kucoin-sequenced", "btcusdt", 108, 200) is False
        assert store.interval_has_unresolved_gap("kucoin-sequenced", "btcusdt", 200, 300) is False
        assert store.interval_has_unresolved_gap("kucoin-sequenced", "btcusdt", 5500, 6500) is True
        assert (
            store.interval_has_unresolved_gap(
                "kucoin-sequenced", "btcusdt", 100, 200, stream_kind="books"
            )
            is False
        )
        assert (
            store.interval_has_unresolved_gap(
                "kucoin-sequenced", "btcusdt", 100, 200, stream_kind="trades"
            )
            is True
        )
    finally:
        store.close()


def test_status_includes_evidence_axes(tmp_path):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.create_run(_manifest())
        store.set_run_status("v8-run", "running")
        evidence = store.status("v8-run")["evidence"]
        assert evidence["integrity_state"] == "valid_so_far"
        assert evidence["capture_quality"] == "uncertified"
        assert evidence["evidence_status"] == "diagnostic"
    finally:
        store.close()


def test_terminal_run_rejects_open_slots(tmp_path):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.create_run(_manifest())
        store.schedule_slot("v8-run", 1000, 2000)
        store.set_run_status("v8-run", "stopped")
        integrity = store.status("v8-run")["integrity"]
        assert integrity["valid"] is False
        assert integrity["error_codes"]["terminal_run_has_open_slots"] == 1
    finally:
        store.close()


def test_database_is_single_run(tmp_path):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.create_run(_manifest("first"))
        with pytest.raises(RuntimeError, match="single-run"):
            store.create_run(_manifest("second"))
    finally:
        store.close()


def test_feature_export_canonical_names():
    feature = FeatureWindow(0, 1000, 2, 1, 1, 0.5, 0.1, 0.001, 0.0)
    record = feature.to_record()
    assert record["historical_aggressor_buy_share"] == 0.5
    assert record["closing_book_depth_imbalance"] == 0.1


def test_integrity_timing_uses_decision_domain_and_lead(tmp_path):
    from dataclasses import replace

    from exchange_q.domain import Forecast

    manifest = replace(_manifest("timing-run"), decision_lead_ms=100)
    store = V7Store(str(tmp_path / "timing.sqlite3"))
    try:
        store.create_run(manifest)
        features = FeatureWindow(0, 900, 2, 1, 1, 0.5, 0.0, 0.001, 0.0)
        store.schedule_slot("timing-run", 1000, 2000)
        store.create_forecast(
            "timing-run",
            1000,
            features,
            Forecast("model", 0.5, 0.5),
            "hash",
            observed_decision_ms=899,
        )
        store.schedule_slot("timing-run", 2000, 3000)
        store.create_forecast(
            "timing-run",
            2000,
            features,
            Forecast("model", 0.5, 0.5),
            "hash",
            observed_decision_ms=1900,
        )
        label = store.build_label("replay", "btcusdt", 2000, 3000)
        store.resolve_slot("timing-run", 2000, label, 1, observed_decision_ms=2999)
        store.schedule_slot("timing-run", 3000, 4000)
        store.create_forecast(
            "timing-run",
            3000,
            features,
            Forecast("model", 0.5, 0.5),
            "hash",
            observed_decision_ms=2900,
        )
        label = store.build_label("replay", "btcusdt", 3000, 4000)
        store.resolve_slot("timing-run", 3000, label, 1, observed_decision_ms=4000)
        store.cancel_open_slots("timing-run", "test_complete")

        integrity = store.run_integrity("timing-run")
        assert integrity["valid"] is False
        assert integrity["error_codes"] == {
            "forecast_created_early": 1,
            "label_resolved_early": 1,
        }
        flagged = {error["slot_start_ms"] for error in integrity["errors"]}
        assert flagged == {1000, 2000}
    finally:
        store.close()


def test_export_includes_capture_ledger_and_raw_stream_summary(tmp_path):
    from decimal import Decimal

    from exchange_q.domain import BookEvent, TradeEvent

    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.create_run(_manifest())
        store.save_trade(
            TradeEvent(
                provider="replay",
                symbol="btcusdt",
                exchange_trade_id="t1",
                exchange_time_ms=100,
                received_time_ms=101,
                aggressor_side="buy",
                price=Decimal(100),
                quantity=Decimal(1),
            )
        )
        store.save_book(
            BookEvent(
                provider="replay",
                symbol="btcusdt",
                exchange_time_ms=100,
                received_time_ms=101,
                best_bid=Decimal(99),
                best_ask=Decimal(101),
                bid_quantity=Decimal(6),
                ask_quantity=Decimal(4),
            )
        )
        store.mark_coverage("replay", "btcusdt", 1000, 2000, False, ("test_gap",))
        store.start_capture_session("sess-trades", "replay", "btcusdt", "trades")
        store.checkpoint_capture("replay", "btcusdt", "trades", 1, 100, 101, "sess-trades")
        store.record_recovery("replay", "btcusdt", "trades", 2, 3, "success", 2)
        store.record_clock_sample("replay", 100, 120, 110)
        store.record_continuity_gap(
            "replay",
            "btcusdt",
            "trades",
            105,
            108,
            complete=False,
            first_sequence=6,
            last_sequence=7,
            reasons=("unrecovered_trade_gap",),
        )
        store.save_provider_certification(
            "cert-1",
            "replay",
            "btcusdt",
            "replay-adapter-v1",
            True,
            {"valid": True},
        )

        document = store.export_run("v8-run")

        ledger = document["capture_ledger"]
        intervals = ledger["continuity_intervals"]
        assert len(intervals) == 1
        assert intervals[0]["start_ms"] == 105
        assert intervals[0]["end_ms"] == 108
        assert intervals[0]["complete"] == 0
        assert intervals[0]["first_sequence"] == 6
        assert intervals[0]["last_sequence"] == 7
        assert intervals[0]["reasons"] == ["unrecovered_trade_gap"]
        assert "reasons_json" not in intervals[0]

        coverage = ledger["coverage"]
        assert len(coverage) == 1
        assert coverage[0]["start_ms"] == 1000
        assert coverage[0]["complete"] == 0
        assert coverage[0]["reasons"] == ["test_gap"]

        sessions = ledger["capture_sessions"]
        assert [session["session_id"] for session in sessions] == ["sess-trades"]
        assert sessions[0]["detail"] == {}

        checkpoints = ledger["capture_checkpoints"]
        assert len(checkpoints) == 1
        assert checkpoints[0]["sequence_no"] == 1

        recoveries = ledger["recovery_attempts"]
        assert len(recoveries) == 1
        assert recoveries[0]["status"] == "success"

        assert len(ledger["clock_samples"]) == 1

        certifications = ledger["provider_certifications"]
        assert len(certifications) == 1
        assert certifications[0]["certification_id"] == "cert-1"
        assert certifications[0]["report"] == {"valid": True}

        raw = document["raw_streams"]
        assert raw["trades"]["count"] == 1
        assert raw["trades"]["first_exchange_time_ms"] == 100
        assert raw["trades"]["last_exchange_time_ms"] == 100
        assert raw["books"]["count"] == 1
    finally:
        store.close()
