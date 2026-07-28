import json

from exchange_q.domain import FeatureWindow, Forecast, RunManifest
from exchange_q.monitor import format_monitor_report, monitor_snapshot
from exchange_q.store import V7Store


def _manifest(run_id="monitor-run"):
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
        target_eligible=5,
    )


def test_monitor_snapshot_reports_slots_and_stream(tmp_path):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.create_run(_manifest())
        store.schedule_slot("monitor-run", 1000, 2000)
        store.create_forecast(
            "monitor-run",
            1000,
            FeatureWindow(0, 1000, 1, 0, 1, 0.0, 0.0, 0.001, 0.0),
            Forecast("model", 0.5, 0.5),
            "hash",
        )
        store.set_run_status("monitor-run", "running")
        snapshot = monitor_snapshot(store, "monitor-run")
        assert snapshot["run_id"] == "monitor-run"
        assert snapshot["recent_slots"]
        assert snapshot["recent_slots"][-1]["status"] in {"created", "pending_label"}
        assert snapshot["writer_state"] == "orphaned"
        report = format_monitor_report(snapshot)
        assert "recent slots:" in report
        assert "stream:" in report
        assert "run health: orphaned" in report
        json.dumps(snapshot)
    finally:
        store.close()
