from exchange_q.domain import FeatureWindow, Forecast
from exchange_q.monitor import format_final_summary, format_monitor_report, monitor_snapshot
from exchange_q.store import V7Store
from tests.test_v7_monitor import _manifest


def test_final_summary_is_mode_aware(tmp_path):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.create_run(_manifest())
        store.set_run_status("monitor-run", "diagnostic_limit")
        snapshot = monitor_snapshot(store, "monitor-run")
        snapshot["database_path"] = "runs/monitor-run.sqlite3"
        summary = format_final_summary(snapshot)
        assert "diagnostic run finished" in summary
        assert "scoreable:" in summary
        assert "slot tally:" in summary
        assert "exclusions:" in summary
        assert "not scored evidence" in summary
        assert "--database runs/monitor-run.sqlite3" in summary
        assert "--run-id monitor-run" in summary
    finally:
        store.close()


def test_outcome_view_hides_detail_sections(tmp_path):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.create_run(_manifest())
        store.set_run_status("monitor-run", "running")
        snapshot = monitor_snapshot(store, "monitor-run")
        outcome = format_monitor_report(snapshot, width=100, view="outcome")
        detail = format_monitor_report(snapshot, width=100, view="detail")
        assert "FEATURES " not in outcome
        assert "SLOTS    " in outcome
        assert "EXCLUSIONS " in outcome
        assert "FEATURES " in detail or "waiting for first feature window" in detail
    finally:
        store.close()


def test_slots_and_exclusions_reflect_resolved_slots(tmp_path):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.create_run(_manifest())
        store.schedule_slot("monitor-run", 1000, 2000)
        store.create_forecast(
            "monitor-run",
            1000,
            FeatureWindow(0, 1000, 2, 1, 1, 0.5, 0.0, 0.001, 0.0),
            Forecast("model", 0.5, 0.5),
            "hash",
        )
        label = store.build_label("replay", "btcusdt", 1000, 2000)
        store.resolve_slot("monitor-run", 1000, label, 2)
        store.set_run_status("monitor-run", "running")
        snapshot = monitor_snapshot(store, "monitor-run")
        assert snapshot["slot_tally"]["unscoreable"] >= 1
        report = format_monitor_report(snapshot, width=120, view="outcome")
        assert "unscoreable 1" in report
        assert "EXCLUSIONS " in report
    finally:
        store.close()
