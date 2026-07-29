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
