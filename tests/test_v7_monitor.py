import json
import re
import sys
from decimal import Decimal

from exchange_q.domain import BookEvent, FeatureWindow, Forecast, RunManifest, TradeEvent
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


def _trade(identifier, timestamp, side, quantity):
    return TradeEvent(
        provider="replay",
        symbol="btcusdt",
        exchange_trade_id=identifier,
        exchange_time_ms=timestamp,
        received_time_ms=timestamp + 1,
        aggressor_side=side,
        price=Decimal(100),
        quantity=Decimal(quantity),
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


def test_monitor_snapshot_reports_slots_and_stream(tmp_path):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.create_run(_manifest())
        store.schedule_slot("monitor-run", 1000, 2000)
        store.create_forecast(
            "monitor-run",
            1000,
            FeatureWindow(0, 1000, 1, 0, 1, 0.0, 0.0, 0.001, 0.0),
            Forecast(
                "model",
                0.55,
                0.52,
                diagnostics={
                    "baseline_probabilities": {
                        "flow_persistence_v1": 0.4,
                        "development_prior_v1": 0.5,
                        "regularized_logistic_v1": 0.6,
                    }
                },
            ),
            "hash",
        )
        store.save_book(_book(1500))
        store.save_trade(_trade("buy", 1600, "buy", 2))
        store.save_trade(_trade("sell", 1700, "sell", 1))
        store.set_run_status("monitor-run", "running")
        snapshot = monitor_snapshot(store, "monitor-run")
        assert snapshot["run_id"] == "monitor-run"
        assert snapshot["recent_slots"]
        assert snapshot["recent_slots"][-1]["status"] in {
            "created",
            "pending_label",
            "forecasted",
            "awaiting_label",
        }
        assert snapshot["writer_state"] == "orphaned"
        assert snapshot["next_action"] == "resolve label"
        assert snapshot["next_action_ms"] == 2000
        assert snapshot["market"]["last_price"] == 100.0
        assert snapshot["market"]["book_imbalance"] == 0.2
        assert snapshot["current_slot"]["live_buy_count"] == 1
        assert snapshot["current_slot"]["live_sell_count"] == 1
        assert snapshot["current_slot"]["live_buy_quantity_ratio"] == 2 / 3
        report = format_monitor_report(snapshot, width=120, view="detail")
        visible_report = _visible(report)
        assert "EXCHANGE-Q | DIAGNOSTIC" in visible_report
        assert "ACTION   COLLECTING LABEL" in visible_report
        assert "MARKET   latest trade 100.00 SELL" in visible_report
        assert "FEATURES input trades 1" in visible_report
        assert "MODELS   Born 0.550" in visible_report
        assert "SLOTS    awaiting" in visible_report
        assert "EXCLUSIONS none yet" in visible_report
        assert "OUTCOME  on track" in visible_report
        assert "diagnostic capture — not scored" in visible_report
        assert "SYSTEM   lifecycle integrity VALID SO FAR" in visible_report
        assert "recent events:" not in visible_report
        assert all(len(_visible(line)) == 120 for line in report.splitlines())
        json.dumps(snapshot)
    finally:
        store.close()


def test_dashboard_adapts_to_terminal_width_and_clears_each_line(tmp_path):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.create_run(_manifest())
        store.set_run_status("monitor-run", "running")
        snapshot = monitor_snapshot(store, "monitor-run")

        narrow = format_monitor_report(snapshot, width=52)
        standard = format_monitor_report(snapshot, width=80)
        wide = format_monitor_report(snapshot, width=120, view="detail")

        assert "MARKET   " not in narrow
        assert "FEATURES " not in narrow
        assert "PROGRESS " in standard
        assert "SLOTS    " in standard
        assert "EXCLUSIONS " in standard
        assert "EVIDENCE " in standard
        assert "book-depth imbalance" not in standard
        assert "book-depth imbalance" in wide
        for width, report in ((52, narrow), (80, standard), (120, wide)):
            assert all(len(_visible(line)) == width for line in report.splitlines())
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


def _visible(line):
    return re.sub(r"\x1b\[[0-9;]*m", "", line)
