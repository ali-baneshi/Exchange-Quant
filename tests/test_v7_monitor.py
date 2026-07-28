import json
import sys

from exchange_q.domain import FeatureWindow, Forecast, RunManifest
from exchange_q.monitor import RunConsole, format_monitor_report, monitor_snapshot
from exchange_q.providers.replay import ReplayProvider
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
        assert snapshot["next_action"] == "resolve label"
        assert snapshot["next_action_ms"] == 2000
        report = format_monitor_report(snapshot)
        assert "EXCHANGE-Q  DIAGNOSTIC" in report
        assert "NOW   COLLECTING LABEL" in report
        assert "CHECK integrity VALID SO FAR" in report
        assert "recent events:" not in report
        assert all(len(line) <= 80 for line in report.splitlines())
        json.dumps(snapshot)
    finally:
        store.close()


def test_console_auto_selects_log_without_tty(tmp_path, monkeypatch):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.create_run(_manifest())
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
        console = RunConsole(
            store,
            "monitor-run",
            provider=ReplayProvider([]),
            database_path="runs/monitor.sqlite3",
            artifact_path="artifacts/v7/model.json",
        )
        assert console.display == "log"
    finally:
        store.close()


def test_console_auto_selects_dashboard_with_tty(tmp_path, monkeypatch):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.create_run(_manifest())
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        console = RunConsole(
            store,
            "monitor-run",
            provider=ReplayProvider([]),
            database_path="runs/monitor.sqlite3",
            artifact_path="artifacts/v7/model.json",
        )
        assert console.display == "dashboard"
    finally:
        store.close()


def test_dashboard_restores_terminal_screen(tmp_path, monkeypatch, capsys):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.create_run(_manifest())
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        console = RunConsole(
            store,
            "monitor-run",
            provider=ReplayProvider([]),
            database_path="runs/monitor.sqlite3",
            artifact_path="artifacts/v7/model.json",
            display="dashboard",
        )
        console._enter_screen()
        console._leave_screen()
        output = capsys.readouterr().out
        assert "\033[?1049h" in output
        assert "\033[?25l" in output
        assert "\033[?25h" in output
        assert "\033[?1049l" in output
    finally:
        store.close()


def test_no_color_disables_dashboard_styling(tmp_path, monkeypatch):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.create_run(_manifest())
        store.set_run_status("monitor-run", "running")
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        report = format_monitor_report(monitor_snapshot(store, "monitor-run"))
        assert "\033[" not in report
    finally:
        store.close()
