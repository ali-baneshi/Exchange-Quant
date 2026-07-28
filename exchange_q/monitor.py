from __future__ import annotations

import asyncio
import json
import os
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

    async def watch(self, runner_task: asyncio.Task) -> None:
        while True:
            previous = self._previous
            snapshot = self._snapshot()
            if self.display == "dashboard":
                self._render_dashboard(snapshot, clear=not runner_task.done())
            else:
                self._render_log(snapshot, previous)
            if runner_task.done():
                return
            await asyncio.sleep(self.refresh_s)

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
        if self._previous is not None:
            elapsed_s = max(
                0.001,
                (snapshot["observed_at_ms"] - self._previous["observed_at_ms"]) / 1000,
            )
            snapshot["trade_rate"] = max(
                0,
                snapshot["stream"].get("trade_count", 0)
                - self._previous["stream"].get("trade_count", 0),
            ) / elapsed_s
            snapshot["book_rate"] = max(
                0,
                snapshot["stream"].get("book_count", 0)
                - self._previous["stream"].get("book_count", 0),
            ) / elapsed_s
        else:
            snapshot["trade_rate"] = 0.0
            snapshot["book_rate"] = 0.0
        self._previous = snapshot
        return snapshot

    def _render_dashboard(self, snapshot: dict[str, Any], *, clear: bool) -> None:
        if clear or self.display == "dashboard":
            print("\033[2J\033[H", end="")
        print(format_monitor_report(snapshot), flush=True)

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
    stream = store.connection.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM trades WHERE symbol = ? AND provider = ?) AS trade_count,
            (SELECT COUNT(*) FROM books WHERE symbol = ? AND provider = ?) AS book_count,
            (SELECT MAX(received_time_ms) FROM trades WHERE symbol = ? AND provider = ?) AS last_trade_ms,
            (SELECT MAX(received_time_ms) FROM books WHERE symbol = ? AND provider = ?) AS last_book_ms
        """,
        (symbol, provider, symbol, provider, symbol, provider, symbol, provider),
    ).fetchone()
    slots = [
        {
            **dict(row),
            "exclusions": json.loads(row["exclusion_json"]),
            "probability_buy": (
                json.loads(row["forecast_json"]).get("probability_buy")
                if row["forecast_json"]
                else None
            ),
        }
        for row in store.connection.execute(
            """
            SELECT slot_start_ms, slot_end_ms, status, forecast_json,
                   exclusion_json, updated_at_ms
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
    observed_at_ms = int(time.time() * 1000)
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
        "next_action": next_action,
        "next_action_ms": next_action_ms,
        "exclusion_counts": exclusions,
        "recent_slots": list(reversed(slots)),
        "recent_events": list(reversed(events)),
    }


def format_monitor_report(snapshot: dict[str, Any]) -> str:
    lines: list[str] = []
    observed = _format_time(snapshot["observed_at_ms"])
    lines.append(f"exchange-q diagnostic  run={snapshot['run_id']}  at={observed}")
    if snapshot.get("database_path"):
        lines.append(f"database: {snapshot['database_path']}")
    if snapshot.get("artifact_path"):
        lines.append(f"artifact: {snapshot['artifact_path']} (diagnostic-only)")
    lines.append("")

    manifest = snapshot["manifest"]
    elapsed_s = max(
        0,
        (snapshot["observed_at_ms"] - snapshot["created_at_ms"]) / 1000,
    )
    lines.append(f"run status: {snapshot['status']}")
    lines.append(f"run health: {snapshot['writer_state']}")
    lines.append(f"elapsed: {_format_duration(elapsed_s)}")
    provider_health = snapshot.get("provider_health")
    provider_text = manifest["provider"]
    if provider_health:
        provider_text += (
            f" connected={provider_health['connected']} "
            f"reconnects={provider_health['reconnects']} "
            f"gaps={provider_health['sequence_gaps']}"
        )
    lines.append(
        f"provider: {provider_text}  symbol: {manifest['symbol']}  "
        f"cadence: {manifest['cadence_ms'] // 1000}s  horizon: {manifest['horizon_ms'] // 1000}s"
    )
    if provider_health and provider_health["detail"]:
        lines.append(f"provider detail: {provider_health['detail']}")

    progress = snapshot["eligible_progress"]
    if manifest["provider"] == "htx-ws":
        eligible_text = f"unavailable ({progress['eligible']} stored)"
    else:
        eligible_text = f"{progress['eligible']}/{progress['target']}"
    lines.append(
        f"eligible: {eligible_text}  terminal slots: "
        f"{_format_progress(snapshot['terminal_slots'], snapshot['terminal_slot_limit'])}"
    )

    counts = snapshot["forecast_counts"]
    if counts:
        count_parts = ", ".join(f"{name}={value}" for name, value in sorted(counts.items()))
        lines.append(f"forecast counts: {count_parts}")

    lease = snapshot["lease"]
    if lease:
        age_s = max(0, (snapshot["observed_at_ms"] - lease["heartbeat_ms"]) / 1000)
        lines.append(
            f"writer: pid={lease['pid']}  heartbeat_age={age_s:.1f}s  owner={lease['owner_id'][:8]}"
        )
    else:
        lines.append("writer: none")

    stream = snapshot["stream"]
    lines.append(
        f"stream: {snapshot['stream_state']}  "
        f"trades={stream.get('trade_count', 0)}  "
        f"books={stream.get('book_count', 0)}  "
        f"rates={snapshot.get('trade_rate', 0.0):.1f} trades/s, "
        f"{snapshot.get('book_rate', 0.0):.1f} books/s  "
        f"last_trade={_format_time(stream.get('last_trade_ms'))}  "
        f"last_book={_format_time(stream.get('last_book_ms'))}"
    )
    if snapshot["next_action_ms"] and snapshot["status"] == "running":
        remaining_s = max(
            0,
            (snapshot["next_action_ms"] - snapshot["observed_at_ms"]) / 1000,
        )
        lines.append(
            f"next action: {snapshot['next_action']} at "
            f"{_format_time(snapshot['next_action_ms'])}  "
            f"in {remaining_s:.0f}s"
        )
    remaining_slots = (
        max(0, snapshot["terminal_slot_limit"] - snapshot["terminal_slots"])
        if snapshot["terminal_slot_limit"] is not None
        else None
    )
    if remaining_slots is not None and snapshot["status"] == "running":
        estimate_s = remaining_slots * manifest["cadence_ms"] / 1000
        lines.append(f"estimated remaining: ~{_format_duration(estimate_s)}")
    if snapshot["exclusion_counts"]:
        exclusions = ", ".join(
            f"{name}={count}"
            for name, count in sorted(snapshot["exclusion_counts"].items())
        )
        lines.append(f"exclusions: {exclusions}")
    lines.append("")
    lines.append("EVIDENCE: DIAGNOSTIC ONLY — HTX continuity is not certifiable.")
    lines.append("")

    lines.append("recent slots:")
    if snapshot["recent_slots"]:
        for slot in snapshot["recent_slots"]:
            exclusions = ", ".join(slot["exclusions"]) or "-"
            probability = slot["probability_buy"]
            probability_text = f"{probability:.3f}" if isinstance(probability, float) else "-"
            updated = _format_time(slot["updated_at_ms"])
            lines.append(
                f"  {_format_time(slot['slot_start_ms'])}  {slot['status']:<22}  "
                f"p={probability_text}  updated={updated}  [{exclusions}]"
            )
    else:
        lines.append("  (none yet)")

    lines.append("")
    lines.append("recent events:")
    if snapshot["recent_events"]:
        for event in snapshot["recent_events"]:
            slot = event["slot_start_ms"]
            slot_text = str(slot) if slot is not None else "-"
            detail = _format_event_detail(event)
            lines.append(
                f"  {_format_time(event['created_at_ms'])}  "
                f"{event['event_type']:<20}  slot={slot_text}  {detail}"
            )
    else:
        lines.append("  (none yet)")

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
