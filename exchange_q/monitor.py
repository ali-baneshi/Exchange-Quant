from __future__ import annotations

import json
import os
import time
from typing import Any

from exchange_q.domain import TERMINAL_FORECAST_STATUSES, ForecastStatus
from exchange_q.store import V7Store


TERMINAL_STATUS_NAMES = {status.value for status in TERMINAL_FORECAST_STATUSES}


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
            SELECT created_at_ms, event_type, slot_start_ms, payload_json
            FROM lifecycle_events
            WHERE run_id = ?
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
    lease = status["lease"]
    writer_state = _writer_state(lease, observed_at_ms, status["status"])
    return {
        "observed_at_ms": observed_at_ms,
        "run_id": run_id,
        "status": status["status"],
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
        "recent_slots": list(reversed(slots)),
        "recent_events": list(reversed(events)),
    }


def format_monitor_report(snapshot: dict[str, Any]) -> str:
    lines: list[str] = []
    observed = _format_time(snapshot["observed_at_ms"])
    lines.append(f"exchange-q monitor  run={snapshot['run_id']}  at={observed}")
    lines.append("")

    manifest = snapshot["manifest"]
    lines.append(f"run status: {snapshot['status']}")
    lines.append(f"run health: {snapshot['writer_state']}")
    lines.append(
        f"provider: {manifest['provider']}  symbol: {manifest['symbol']}  "
        f"cadence: {manifest['cadence_ms'] // 1000}s  horizon: {manifest['horizon_ms'] // 1000}s"
    )

    progress = snapshot["eligible_progress"]
    lines.append(
        f"eligible: {progress['eligible']}/{progress['target']}  "
        f"terminal slots: {_format_progress(snapshot['terminal_slots'], snapshot['terminal_slot_limit'])}"
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
        f"last_trade={_format_time(stream.get('last_trade_ms'))}  "
        f"last_book={_format_time(stream.get('last_book_ms'))}"
    )
    if snapshot["latest_slot_end_ms"] and snapshot["status"] == "running":
        remaining_s = max(
            0,
            (snapshot["latest_slot_end_ms"] - snapshot["observed_at_ms"]) / 1000,
        )
        lines.append(
            f"next slot boundary: {_format_time(snapshot['latest_slot_end_ms'])}  "
            f"in {remaining_s:.0f}s"
        )
    lines.append("")

    lines.append("recent slots:")
    if snapshot["recent_slots"]:
        for slot in snapshot["recent_slots"]:
            exclusions = ", ".join(slot["exclusions"]) or "-"
            probability = slot["probability_buy"]
            probability_text = f"{probability:.3f}" if isinstance(probability, float) else "-"
            updated = _format_time(slot["updated_at_ms"])
            lines.append(
                f"  {slot['slot_start_ms']}  {slot['status']:<22}  "
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


def _format_time(timestamp_ms: int | None) -> str:
    if not timestamp_ms:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp_ms / 1000))


def _format_progress(value: int, limit: int | None) -> str:
    return f"{value}/{limit}" if limit is not None else str(value)


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
