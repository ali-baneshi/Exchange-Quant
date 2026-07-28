from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import time
from typing import Any

from exchange_q.domain import TERMINAL_FORECAST_STATUSES, ForecastStatus
from exchange_q.store import V7Store

TERMINAL_STATUS_NAMES = {status.value for status in TERMINAL_FORECAST_STATUSES}


class RunConsole:
    def __init__(
        self,
        store: V7Store,
        run_id: str,
        *,
        provider,
        database_path: str,
        artifact_path: str,
        display: str = "auto",
        refresh_s: float = 2.0,
    ):
        if refresh_s <= 0:
            raise ValueError("refresh interval must be positive")
        self.store = store
        self.run_id = run_id
        self.provider = provider
        self.database_path = database_path
        self.artifact_path = artifact_path
        self.refresh_s = refresh_s
        self.display = (
            "dashboard"
            if display == "auto" and sys.stdout.isatty()
            else "log"
            if display == "auto"
            else display
        )
        self._previous: dict[str, Any] | None = None
        self._last_event_id = 0
        self._started = False
        self._screen_active = False

    async def watch(self, runner_task: asyncio.Task) -> None:
        final_snapshot: dict[str, Any] | None = None
        try:
            if self.display == "dashboard":
                self._enter_screen()
            while True:
                previous = self._previous
                snapshot = self._snapshot()
                final_snapshot = snapshot
                if self.display == "dashboard":
                    self._render_dashboard(snapshot)
                else:
                    self._render_log(snapshot, previous)
                if runner_task.done():
                    return
                await asyncio.sleep(self.refresh_s)
        finally:
            if self.display == "dashboard":
                self._leave_screen()
                if final_snapshot is not None:
                    print(format_final_summary(final_snapshot), flush=True)

    def _snapshot(self) -> dict[str, Any]:
        snapshot = monitor_snapshot(self.store, self.run_id)
        snapshot["database_path"] = self.database_path
        snapshot["artifact_path"] = self.artifact_path
        health = self.provider.health()
        snapshot["provider_health"] = {
            "connected": health.connected,
            "last_event_received_ms": health.last_event_received_ms,
            "reconnects": health.reconnects,
            "sequence_gaps": health.sequence_gaps,
            "coverage_certifiable": health.coverage_certifiable,
            "detail": health.detail,
        }
        self._previous = snapshot
        return snapshot

    def _enter_screen(self) -> None:
        if self._screen_active:
            return
        print("\033[?1049h\033[?25l", end="", flush=True)
        self._screen_active = True

    def _leave_screen(self) -> None:
        if not self._screen_active:
            return
        print("\033[?25h\033[?1049l", end="", flush=True)
        self._screen_active = False

    def _render_dashboard(self, snapshot: dict[str, Any]) -> None:
        width = shutil.get_terminal_size((80, 24)).columns
        print(
            "\033[H" + format_monitor_report(snapshot, width=width) + "\033[J",
            end="",
            flush=True,
        )

    def _render_log(
        self,
        snapshot: dict[str, Any],
        previous: dict[str, Any] | None,
    ) -> None:
        if not self._started:
            print(
                f"[exchange-q] START run={self.run_id} "
                f"database={self.database_path} artifact={self.artifact_path}",
                flush=True,
            )
            self._started = True
            print(
                "[exchange-q] EVIDENCE diagnostic-only; HTX coverage is not certifiable",
                flush=True,
            )
        if previous is None or previous.get("stream_state") != snapshot["stream_state"]:
            print(
                f"[exchange-q] STREAM state={snapshot['stream_state']} "
                f"trades={snapshot['stream'].get('trade_count', 0)} "
                f"books={snapshot['stream'].get('book_count', 0)}",
                flush=True,
            )
        provider_health = snapshot["provider_health"]
        previous_health = previous.get("provider_health") if previous else None
        if (
            previous_health is None
            or previous_health["connected"] != provider_health["connected"]
            or previous_health["reconnects"] != provider_health["reconnects"]
            or previous_health["sequence_gaps"] != provider_health["sequence_gaps"]
        ):
            print(
                f"[exchange-q] PROVIDER connected={provider_health['connected']} "
                f"reconnects={provider_health['reconnects']} "
                f"gaps={provider_health['sequence_gaps']} "
                f"detail={provider_health['detail'] or '-'}",
                flush=True,
            )
        for event in _events_after(self.store, self.run_id, self._last_event_id):
            event_id = event["event_id"]
            if event_id <= self._last_event_id or event["event_type"] == "run_created":
                continue
            print(_format_log_event(event), flush=True)
            self._last_event_id = max(self._last_event_id, event_id)
        if snapshot["status"] != "running":
            print(
                f"[exchange-q] FINAL status={snapshot['status']} "
                f"terminal={_format_progress(snapshot['terminal_slots'], snapshot['terminal_slot_limit'])} "
                f"database={self.database_path}",
                flush=True,
            )


def monitor_snapshot(
    store: V7Store,
    run_id: str,
    *,
    recent_slots: int = 5,
    recent_events: int = 8,
) -> dict[str, Any]:
    status = store.status(run_id)
    symbol = status["manifest"]["symbol"]
    provider = status["manifest"]["provider"]
    observed_at_ms = int(time.time() * 1000)
    stream = store.connection.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM trades WHERE symbol = ? AND provider = ?) AS trade_count,
            (SELECT COUNT(*) FROM books WHERE symbol = ? AND provider = ?) AS book_count,
            (SELECT MAX(received_time_ms) FROM trades WHERE symbol = ? AND provider = ?) AS last_trade_ms,
            (SELECT MAX(received_time_ms) FROM books WHERE symbol = ? AND provider = ?) AS last_book_ms,
            (SELECT COUNT(*) FROM trades
             WHERE symbol = ? AND provider = ? AND received_time_ms >= ?) AS trades_last_60s,
            (SELECT COUNT(*) FROM books
             WHERE symbol = ? AND provider = ? AND received_time_ms >= ?) AS books_last_60s
        """,
        (
            symbol,
            provider,
            symbol,
            provider,
            symbol,
            provider,
            symbol,
            provider,
            symbol,
            provider,
            observed_at_ms - 60_000,
            symbol,
            provider,
            observed_at_ms - 60_000,
        ),
    ).fetchone()
    slots = [
        {
            **dict(row),
            "features": (
                json.loads(row["features_json"]) if row["features_json"] else None
            ),
            "forecast": (
                json.loads(row["forecast_json"]) if row["forecast_json"] else None
            ),
            "label": json.loads(row["label_json"]) if row["label_json"] else None,
            "exclusions": json.loads(row["exclusion_json"]),
            "probability_buy": (
                json.loads(row["forecast_json"]).get("probability_buy")
                if row["forecast_json"]
                else None
            ),
        }
        for row in store.connection.execute(
            """
            SELECT slot_start_ms, slot_end_ms, status, features_json,
                   forecast_json, label_json, exclusion_json, updated_at_ms
            FROM forecast_slots
            WHERE run_id = ?
            ORDER BY slot_start_ms DESC
            LIMIT ?
            """,
            (run_id, recent_slots),
        )
    ]
    events = [
        {
            **dict(row),
            "payload": json.loads(row["payload_json"]),
        }
        for row in store.connection.execute(
            """
            SELECT event_id, created_at_ms, event_type, slot_start_ms, payload_json
            FROM lifecycle_events
            WHERE run_id = ? AND event_type != 'run_created'
            ORDER BY event_id DESC
            LIMIT ?
            """,
            (run_id, recent_events),
        )
    ]
    forecast_counts = status["forecast_counts"]
    terminal_slots = sum(
        forecast_counts.get(name, 0) for name in TERMINAL_STATUS_NAMES
    )
    eligible = forecast_counts.get(ForecastStatus.RESOLVED_ELIGIBLE.value, 0)
    stream_data = dict(stream) if stream else {}
    latest_stream_ms = max(
        stream_data.get("last_trade_ms") or 0,
        stream_data.get("last_book_ms") or 0,
    )
    freshness_limit_ms = max(30_000, status["manifest"]["cadence_ms"] * 2)
    if latest_stream_ms == 0:
        stream_state = "no_data"
    elif observed_at_ms - latest_stream_ms > freshness_limit_ms:
        stream_state = "stale"
    else:
        stream_state = "active"
    latest_slot = slots[0] if slots else None
    next_action, next_action_ms = _next_action(latest_slot)
    current_slot = _current_slot(store, provider, symbol, latest_slot)
    latest_result = next(
        (
            slot
            for slot in slots
            if slot["status"] in TERMINAL_STATUS_NAMES
        ),
        None,
    )
    lease = status["lease"]
    writer_state = _writer_state(lease, observed_at_ms, status["status"])
    exclusions = _exclusion_counts(store, run_id)
    return {
        "observed_at_ms": observed_at_ms,
        "run_id": run_id,
        "status": status["status"],
        "created_at_ms": status["created_at_ms"],
        "updated_at_ms": status["updated_at_ms"],
        "manifest": status["manifest"],
        "integrity": status["integrity"],
        "forecast_counts": forecast_counts,
        "terminal_slots": terminal_slots,
        "terminal_slot_limit": status["manifest"].get("terminal_slot_limit"),
        "eligible_progress": {
            "eligible": eligible,
            "target": status["manifest"]["target_eligible"],
        },
        "lease": lease,
        "writer_state": writer_state,
        "stream": stream_data,
        "stream_state": stream_state,
        "latest_slot_end_ms": latest_slot["slot_end_ms"] if latest_slot else None,
        "current_slot": current_slot,
        "latest_result": latest_result,
        "phase": _phase(status["status"], current_slot),
        "next_action": next_action,
        "next_action_ms": next_action_ms,
        "exclusion_counts": exclusions,
        "recent_slots": list(reversed(slots)),
        "recent_events": list(reversed(events)),
    }


def format_monitor_report(
    snapshot: dict[str, Any],
    *,
    width: int = 80,
) -> str:
    width = max(52, width)
    color = _supports_color()
    elapsed_end_ms = (
        snapshot["observed_at_ms"]
        if snapshot["status"] == "running"
        else snapshot["updated_at_ms"]
    )
    elapsed_s = max(0, (elapsed_end_ms - snapshot["created_at_ms"]) / 1000)
    status = snapshot["status"].upper()
    status_color = "green" if status == "RUNNING" else "red" if status == "FAILED" else "cyan"
    header = (
        f"EXCHANGE-Q  DIAGNOSTIC  {_style(status, status_color, color)}"
        f"  elapsed {_format_duration(elapsed_s)}"
    )

    provider = snapshot.get("provider_health") or {}
    connected = bool(provider.get("connected"))
    last_event_ms = provider.get("last_event_received_ms")
    event_age = (
        max(0.0, (snapshot["observed_at_ms"] - last_event_ms) / 1000)
        if last_event_ms
        else None
    )
    data_state = (
        _style("OK", "green", color)
        if connected and snapshot["stream_state"] == "active"
        else _style("WAIT", "yellow", color)
        if snapshot["stream_state"] == "no_data"
        else _style("WARN", "red", color)
    )
    stream = snapshot["stream"]
    data_line = (
        f"DATA  [{data_state}] HTX {'connected' if connected else 'disconnected'}"
        f" | age {_format_age(event_age)}"
        f" | {stream.get('trades_last_60s', 0)} t/min"
        f" | {stream.get('books_last_60s', 0)} b/min"
        f" | r{provider.get('reconnects', 0)}"
        f" g{provider.get('sequence_gaps', 0)}"
    )

    terminal = snapshot["terminal_slots"]
    limit = snapshot["terminal_slot_limit"]
    progress = _progress_bar(terminal, limit, 18)
    remaining = max(0, limit - terminal) if limit is not None else None
    eta = _estimate_remaining_seconds(snapshot)
    run_line = (
        f"RUN   {progress} {_format_progress(terminal, limit)}"
        f" | remaining {remaining if remaining is not None else '-'}"
        f" | ETA {_format_duration(eta) if eta is not None else '-'}"
    )

    current = snapshot["current_slot"]
    phase = _style(snapshot["phase"], "cyan", color)
    if snapshot["status"] != "running":
        now_line = f"NOW   {phase} | no active processing"
        detail_line = "      p(buy) - | label trades -"
    elif current:
        slot_range = (
            f"{_format_clock(current['slot_start_ms'])}"
            f"->{_format_clock(current['slot_end_ms'])}"
        )
        action_s = (
            max(0, (snapshot["next_action_ms"] - snapshot["observed_at_ms"]) / 1000)
            if snapshot["next_action_ms"]
            else None
        )
        now_line = (
            f"NOW   {phase} | {slot_range}"
            f" | {_format_action(snapshot['next_action'], action_s)}"
        )
        probability = current.get("probability_buy")
        probability_text = f"{probability:.3f}" if probability is not None else "-"
        detail_line = (
            f"      p(buy) {probability_text}"
            f" | label trades {current['live_label_trades']}/"
            f"{snapshot['manifest']['minimum_label_trades']}"
        )
    else:
        now_line = f"NOW   {phase} | waiting for the first actionable slot"
        detail_line = "      p(buy) - | label trades -"

    latest = snapshot["latest_result"]
    if latest:
        probability = latest.get("probability_buy")
        probability_text = f"{probability:.3f}" if probability is not None else "-"
        label = latest.get("label") or {}
        result = (
            "ELIGIBLE"
            if latest["status"] == ForecastStatus.RESOLVED_ELIGIBLE
            else "INELIGIBLE"
            if latest["status"] == ForecastStatus.RESOLVED_INELIGIBLE
            else latest["status"].upper()
        )
        result_color = "green" if result == "ELIGIBLE" else "yellow"
        last_line = (
            f"LAST  {_format_clock(latest['slot_start_ms'])}"
            f" | p {probability_text}"
            f" | trades {label.get('trade_count', '-')}"
            f" | {_style(result, result_color, color)}"
        )
    else:
        last_line = "LAST  no completed slot yet"

    integrity = snapshot["integrity"]
    integrity_text = (
        _style("VALID SO FAR", "green", color)
        if integrity["valid"]
        else _style(
            f"QUARANTINED ({integrity['error_count']} errors)",
            "red",
            color,
        )
    )
    integrity_line = f"CHECK integrity {integrity_text}"
    warning = _warning_line(snapshot, color)
    footer = (
        f"Ctrl-C stop | run ...{snapshot['run_id'][-24:]}"
        if snapshot["status"] == "running"
        else f"Run finished | ...{snapshot['run_id'][-24:]}"
    )
    lines = [
        header,
        _rule(width),
        data_line,
        run_line,
        now_line,
        detail_line,
        last_line,
        integrity_line,
        warning,
        _rule(width),
        footer,
    ]
    return "\n".join(_fit_line(line, width) for line in lines) + "\n"


def format_final_summary(snapshot: dict[str, Any]) -> str:
    elapsed_s = max(
        0,
        (snapshot["updated_at_ms"] - snapshot["created_at_ms"]) / 1000,
    )
    integrity = snapshot["integrity"]
    lines = [
        "Exchange-Q diagnostic finished",
        f"status:    {snapshot['status']}",
        f"duration:  {_format_duration(elapsed_s)}",
        f"slots:     {_format_progress(snapshot['terminal_slots'], snapshot['terminal_slot_limit'])}",
        f"integrity: {integrity['state']} ({integrity['error_count']} errors)",
        f"run ID:    {snapshot['run_id']}",
        f"database:  {snapshot.get('database_path') or '-'}",
        f"artifact:  {snapshot.get('artifact_path') or '-'}",
        "evidence:  diagnostic-only; HTX continuity is not certifiable",
    ]
    return "\n".join(lines)


def _format_event_detail(event: dict[str, Any]) -> str:
    payload = event["payload"]
    if event["event_type"] == "forecast_transition":
        return f"{payload.get('from')} -> {payload.get('to')}"
    if event["event_type"] == "run_status":
        return str(payload.get("status") or payload)
    return json.dumps(payload, sort_keys=True)


def _format_log_event(event: dict[str, Any]) -> str:
    detail = _format_event_detail(event)
    slot = event["slot_start_ms"] if event["slot_start_ms"] is not None else "-"
    return (
        f"[exchange-q] EVENT type={event['event_type']} "
        f"slot={slot} detail={detail}"
    )


def _format_time(timestamp_ms: int | None) -> str:
    if not timestamp_ms:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp_ms / 1000))


def _format_progress(value: int, limit: int | None) -> str:
    return f"{value}/{limit}" if limit is not None else str(value)


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def _format_clock(timestamp_ms: int) -> str:
    return time.strftime("%H:%M:%S", time.localtime(timestamp_ms / 1000))


def _format_age(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    if seconds < 10:
        return f"{seconds:.1f}s"
    return f"{int(seconds)}s"


def _format_action(action: str | None, seconds: float | None) -> str:
    if not action:
        return "advancing"
    if seconds is None:
        return action
    return f"{action} in {int(seconds)}s"


def _next_action(slot: dict[str, Any] | None) -> tuple[str | None, int | None]:
    if not slot:
        return "waiting for first market event", None
    if slot["status"] == ForecastStatus.SCHEDULED:
        return "create forecast", slot["slot_start_ms"]
    if slot["status"] in {
        ForecastStatus.CREATED,
        ForecastStatus.PENDING_LABEL,
    }:
        return "resolve label", slot["slot_end_ms"]
    return None, None


def _current_slot(
    store: V7Store,
    provider: str,
    symbol: str,
    slot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not slot or slot["status"] in TERMINAL_STATUS_NAMES:
        return None
    live_label_trades = 0
    if slot["status"] in {
        ForecastStatus.CREATED,
        ForecastStatus.PENDING_LABEL,
    }:
        live_label_trades = store.connection.execute(
            """
            SELECT COUNT(*) FROM trades
            WHERE provider = ? AND symbol = ?
              AND exchange_time_ms >= ? AND exchange_time_ms < ?
            """,
            (
                provider,
                symbol,
                slot["slot_start_ms"],
                slot["slot_end_ms"],
            ),
        ).fetchone()[0]
    return {
        **slot,
        "live_label_trades": live_label_trades,
    }


def _phase(run_status: str, slot: dict[str, Any] | None) -> str:
    if run_status != "running":
        return run_status.upper()
    if not slot:
        return "CONNECTING"
    if slot["status"] == ForecastStatus.SCHEDULED:
        return "WAITING"
    if slot["status"] in {
        ForecastStatus.CREATED,
        ForecastStatus.PENDING_LABEL,
    }:
        return "COLLECTING LABEL"
    return "ADVANCING"


def _estimate_remaining_seconds(snapshot: dict[str, Any]) -> float | None:
    limit = snapshot["terminal_slot_limit"]
    if limit is None or snapshot["status"] != "running":
        return None
    remaining = max(0, limit - snapshot["terminal_slots"])
    if remaining == 0:
        return 0
    now = snapshot["observed_at_ms"]
    current = snapshot["current_slot"]
    cadence_s = snapshot["manifest"]["cadence_ms"] / 1000
    horizon_s = snapshot["manifest"]["horizon_ms"] / 1000
    if current and current["status"] in {
        ForecastStatus.CREATED,
        ForecastStatus.PENDING_LABEL,
    }:
        first_s = max(0, (current["slot_end_ms"] - now) / 1000)
    elif current:
        first_s = max(0, (current["slot_start_ms"] - now) / 1000) + horizon_s
    else:
        first_s = cadence_s
    return first_s + max(0, remaining - 1) * cadence_s


def _progress_bar(value: int, limit: int | None, width: int) -> str:
    if limit is None or limit <= 0:
        return f"[{'-' * width}]"
    filled = min(width, max(0, round(width * value / limit)))
    return f"[{'#' * filled}{'-' * (width - filled)}]"


def _warning_line(snapshot: dict[str, Any], color: bool) -> str:
    integrity = snapshot["integrity"]
    provider = snapshot.get("provider_health") or {}
    if not integrity["valid"]:
        codes = ", ".join(
            f"{_integrity_label(name)}={count}"
            for name, count in integrity["error_codes"].items()
        )
        return f"WARN  {_style('RUN QUARANTINED', 'red', color)} | {codes}"
    if provider.get("sequence_gaps", 0):
        return f"WARN  {_style('PROVIDER GAPS DETECTED', 'red', color)}"
    if snapshot["stream_state"] == "stale":
        return f"WARN  {_style('MARKET DATA IS STALE', 'red', color)}"
    return (
        f"NOTE  {_style('DIAGNOSTIC ONLY', 'yellow', color)}"
        " | HTX continuity cannot be certified"
    )


def _supports_color() -> bool:
    return (
        sys.stdout.isatty()
        and os.environ.get("TERM", "") != "dumb"
        and "NO_COLOR" not in os.environ
    )


def _style(text: str, color_name: str, enabled: bool) -> str:
    if not enabled:
        return text
    codes = {
        "red": "31",
        "green": "32",
        "yellow": "33",
        "cyan": "36",
    }
    return f"\033[{codes[color_name]}m{text}\033[0m"


def _integrity_label(code: str) -> str:
    return {
        "label_resolved_early": "early resolution",
        "label_trade_count_mismatch": "label mismatch",
        "forecast_created_early": "early forecast",
        "missing_forecast_transition": "missing forecast event",
        "missing_resolution_transition": "missing resolution event",
        "missing_resolved_label": "missing label",
    }.get(code, code.replace("_", " "))


def _rule(width: int) -> str:
    return "-" * width


def _fit_line(line: str, width: int) -> str:
    visible = re.sub(r"\x1b\[[0-9;]*m", "", line)
    if len(visible) <= width:
        return line
    return visible[: max(1, width - 1)] + "…"


def _exclusion_counts(store: V7Store, run_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    rows = store.connection.execute(
        """
        SELECT exclusion_json FROM forecast_slots
        WHERE run_id = ? AND exclusion_json != '[]'
        """,
        (run_id,),
    )
    for row in rows:
        for reason in json.loads(row["exclusion_json"]):
            counts[reason] = counts.get(reason, 0) + 1
    return counts


def _events_after(
    store: V7Store,
    run_id: str,
    event_id: int,
) -> list[dict[str, Any]]:
    return [
        {
            **dict(row),
            "payload": json.loads(row["payload_json"]),
        }
        for row in store.connection.execute(
            """
            SELECT event_id, created_at_ms, event_type, slot_start_ms, payload_json
            FROM lifecycle_events
            WHERE run_id = ? AND event_id > ?
            ORDER BY event_id
            """,
            (run_id, event_id),
        )
    ]


def _writer_state(lease: dict[str, Any] | None, observed_at_ms: int, run_status: str) -> str:
    if run_status != "running":
        return "terminal"
    if not lease:
        return "orphaned"
    heartbeat_age_ms = observed_at_ms - int(lease["heartbeat_ms"])
    if heartbeat_age_ms > 30_000:
        return "stale"
    try:
        os.kill(int(lease["pid"]), 0)
    except ProcessLookupError:
        return "dead"
    except PermissionError:
        return "active_unverified"
    return "active"
