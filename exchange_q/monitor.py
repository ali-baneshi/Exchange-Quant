from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import time
from typing import Any

from exchange_q.artifacts import load_artifact
from exchange_q.domain import TERMINAL_FORECAST_STATUSES, ForecastStatus
from exchange_q.report import format_research_report, report_document_from_snapshot
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
        view: str = "outcome",
        hours: float | None = None,
    ):
        if refresh_s <= 0:
            raise ValueError("refresh interval must be positive")
        self.store = store
        self.run_id = run_id
        self.provider = provider
        self.database_path = database_path
        self.artifact_path = artifact_path
        self.refresh_s = refresh_s
        self.view = view
        self.hours = hours
        try:
            artifact = load_artifact(artifact_path)
            self.artifact_summary = {
                "purpose": artifact.purpose,
                "development_rows": artifact.development_rows,
                "calibration_status": artifact.calibration_status,
                "dataset_hash": artifact.dataset_hash,
            }
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self.artifact_summary = {}
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

    def _print_start(self) -> None:
        if self._started:
            return
        hours_part = f" hours={self.hours:g}" if self.hours is not None else ""
        print(
            f"[exchange-q] START run={self.run_id} "
            f"database={self.database_path} artifact={self.artifact_path}"
            f"{hours_part}; live monitor: this terminal (Ctrl+C stops)",
            flush=True,
        )
        self._started = True

    async def watch(self, runner_task: asyncio.Task) -> None:
        final_snapshot: dict[str, Any] | None = None
        try:
            self._print_start()
            if self.display == "dashboard":
                self._enter_screen()
            while True:
                try:
                    previous = self._previous
                    snapshot = self._snapshot()
                    final_snapshot = snapshot
                    if self.display == "dashboard":
                        self._render_dashboard(snapshot)
                    else:
                        self._render_log(snapshot, previous)
                except Exception as exc:  # noqa: BLE001 — never stop the run for UI errors
                    print(f"[exchange-q] console refresh error: {exc}", flush=True)
                if runner_task.done():
                    return
                await asyncio.sleep(self.refresh_s)
        finally:
            if self.display == "dashboard":
                self._leave_screen()
            if final_snapshot is not None:
                analysis = None
                try:
                    from exchange_q.report import build_analysis_document

                    analysis = build_analysis_document(self.store, self.run_id)
                except Exception:  # noqa: BLE001 — final summary must still print
                    analysis = None
                print(
                    format_final_summary(final_snapshot, analysis_document=analysis),
                    flush=True,
                )

    def _snapshot(self) -> dict[str, Any]:
        snapshot = monitor_snapshot(self.store, self.run_id)
        snapshot["database_path"] = self.database_path
        snapshot["artifact_path"] = self.artifact_path
        snapshot["artifact"] = self.artifact_summary
        health = self.provider.health()
        snapshot["provider_health"] = {
            "connected": health.connected,
            "last_event_received_ms": health.last_event_received_ms,
            "reconnects": health.reconnects,
            "sequence_gaps": health.sequence_gaps,
            "coverage_certifiable": health.coverage_certifiable,
            "detail": health.detail,
            "last_trade_sequence": health.last_trade_sequence,
            "last_book_sequence": health.last_book_sequence,
            "unresolved_gaps": health.unresolved_gaps,
            "clock_offset_ms": health.clock_offset_ms,
            "clock_uncertainty_ms": health.clock_uncertainty_ms,
            "trade_watermark_ms": health.trade_watermark_ms,
            "book_watermark_ms": health.book_watermark_ms,
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
            "\033[H" + format_monitor_report(snapshot, width=width, view=self.view) + "\033[J",
            end="",
            flush=True,
        )

    def _render_log(
        self,
        snapshot: dict[str, Any],
        previous: dict[str, Any] | None,
    ) -> None:
        self._print_start()
        if previous is None:
            manifest = snapshot.get("manifest") or {}
            provider_name = manifest.get("provider", "unknown")
            if manifest.get("mode") == "primary":
                print(
                    f"[exchange-q] EVIDENCE primary provider={provider_name}; "
                    "labels scoreable only with proven capture continuity",
                    flush=True,
                )
            else:
                print(
                    f"[exchange-q] EVIDENCE diagnostic-only provider={provider_name}; "
                    "not a preregistered primary record",
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
            "features": (json.loads(row["features_json"]) if row["features_json"] else None),
            "forecast": (json.loads(row["forecast_json"]) if row["forecast_json"] else None),
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
    terminal_slots = sum(forecast_counts.get(name, 0) for name in TERMINAL_STATUS_NAMES)
    eligible = forecast_counts.get(
        ForecastStatus.RESOLVED_SCOREABLE.value,
        forecast_counts.get(ForecastStatus.RESOLVED_ELIGIBLE.value, 0),
    )
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
    market = _market_snapshot(store, provider, symbol)
    latest_result = next(
        (
            slot
            for slot in slots
            if slot["status"]
            in {
                ForecastStatus.RESOLVED_SCOREABLE.value,
                ForecastStatus.RESOLVED_UNSCOREABLE.value,
                ForecastStatus.RESOLVED_ELIGIBLE.value,
                ForecastStatus.RESOLVED_INELIGIBLE.value,
            }
        ),
        None,
    )
    lease = status["lease"]
    writer_state = _writer_state(lease, observed_at_ms, status["status"])
    exclusions = _exclusion_counts(store, run_id)
    slot_tally = _slot_tally(forecast_counts)
    return {
        "observed_at_ms": observed_at_ms,
        "run_id": run_id,
        "status": status["status"],
        "created_at_ms": status["created_at_ms"],
        "updated_at_ms": status["updated_at_ms"],
        "manifest": status["manifest"],
        "integrity": status["integrity"],
        "evidence": status.get("evidence", {}),
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
        "market": market,
        "latest_slot_end_ms": latest_slot["slot_end_ms"] if latest_slot else None,
        "current_slot": current_slot,
        "latest_result": latest_result,
        "phase": _phase(status["status"], current_slot),
        "next_action": next_action,
        "next_action_ms": next_action_ms,
        "exclusion_counts": exclusions,
        "slot_tally": slot_tally,
        "recent_slots": list(reversed(slots)),
        "recent_events": list(reversed(events)),
    }


def format_monitor_report(
    snapshot: dict[str, Any],
    *,
    width: int = 80,
    view: str = "outcome",
) -> str:
    width = max(52, width)
    color = _supports_color()
    elapsed_end_ms = (
        snapshot["observed_at_ms"] if snapshot["status"] == "running" else snapshot["updated_at_ms"]
    )
    elapsed_s = max(0, (elapsed_end_ms - snapshot["created_at_ms"]) / 1000)
    status = snapshot["status"].upper()
    manifest = snapshot["manifest"]
    mode = manifest.get("mode", "diagnostic").upper()
    status_color = "green" if status == "RUNNING" else "red" if status == "FAILED" else "cyan"
    header = (
        f"EXCHANGE-Q | {mode} | {_style(status, status_color, color)}"
        f" | elapsed {_format_duration(elapsed_s)}"
    )

    goals_line = _format_goals_line(snapshot, mode=manifest.get("mode", "diagnostic"))
    blocker_line = _format_blocker_line(snapshot, color)

    provider = snapshot.get("provider_health") or {}
    connected = bool(provider.get("connected"))
    data_state = (
        _style("OK", "green", color)
        if connected and snapshot["stream_state"] == "active"
        else _style("WAIT", "yellow", color)
        if snapshot["stream_state"] == "no_data"
        else _style("WARN", "red", color)
    )
    stream = snapshot["stream"]
    provider_name = manifest["provider"]
    data_line = (
        f"DATA     [{data_state}] {provider_name}"
        f" | trade age {_format_ms_age(snapshot['observed_at_ms'], stream.get('last_trade_ms'))}"
        f" | book age {_format_ms_age(snapshot['observed_at_ms'], stream.get('last_book_ms'))}"
        f" | last minute {stream.get('trades_last_60s', 0)} trades,"
        f" {stream.get('books_last_60s', 0)} books"
    )

    market = snapshot["market"]
    market_line = (
        f"MARKET   latest trade {_format_price(market.get('last_price'))}"
        f" {str(market.get('last_side') or '-').upper()}"
        f" | top book {_format_price(market.get('best_bid'))} /"
        f" {_format_price(market.get('best_ask'))}"
        f" | spread {_format_spread(market.get('spread'))}"
    )
    market_detail_line = (
        f"         book-depth imbalance {_format_signed(market.get('book_imbalance'))}"
        f" | bid/ask depth {_format_compact_number(market.get('bid_quantity'))} /"
        f" {_format_compact_number(market.get('ask_quantity'))}"
        f" | latest trade quantity {_format_compact_number(market.get('last_quantity'))}"
    )

    terminal = snapshot["terminal_slots"]
    limit = snapshot["terminal_slot_limit"]
    progress = _progress_bar(terminal, limit, 18)
    remaining = max(0, limit - terminal) if limit is not None else None
    eta = _estimate_remaining_seconds(snapshot)
    scoreable = snapshot["eligible_progress"]["eligible"]
    target = snapshot["eligible_progress"]["target"]
    tally = snapshot.get("slot_tally") or _slot_tally(snapshot.get("forecast_counts", {}))
    slots_line = _format_slots_line(tally, mode=manifest.get("mode", "diagnostic"))
    exclusions_line = _format_exclusions_line(snapshot.get("exclusion_counts", {}))
    if manifest.get("mode") == "primary":
        run_line = (
            f"PROGRESS {progress} scoreable outcomes {scoreable}/{target}"
            f" | unscoreable {tally['unscoreable']}"
            f" | ETA {_format_duration(eta) if eta is not None else '-'}"
        )
    else:
        run_line = (
            f"PROGRESS {progress} diagnostic slots {_format_progress(terminal, limit)}"
            f" | remaining {remaining if remaining is not None else '-'}"
            f" | ETA {_format_duration(eta) if eta is not None else '-'}"
        )

    current = snapshot["current_slot"]
    phase = _style(snapshot["phase"], "cyan", color)
    if snapshot["status"] != "running":
        now_line = f"ACTION   {phase} | no active processing"
        window_line = "WINDOWS  no active forecast"
        forecast_line = "FORECAST no active forecast"
        outcome_line = "OUTCOME  no active target window"
        feature_line = "FEATURES no active feature window"
        model_line = "MODELS   no active forecast"
        label_line = ""
        label_detail_line = ""
    elif current:
        slot_range = (
            f"{_format_clock(current['slot_start_ms'])}->{_format_clock(current['slot_end_ms'])}"
        )
        action_s = (
            max(0, (snapshot["next_action_ms"] - snapshot["observed_at_ms"]) / 1000)
            if snapshot["next_action_ms"]
            else None
        )
        now_line = f"ACTION   {phase} | {_format_action(snapshot['next_action'], action_s)}"
        features = current.get("features") or {}
        feature_duration = manifest["lookback_ms"] / 1000
        target_duration = manifest["horizon_ms"] / 1000
        window_line = (
            f"WINDOWS  input {feature_duration:g}s ending "
            f"{_format_clock(features.get('end_ms')) if features else '-'}"
            f" | future target {target_duration:g}s {slot_range}"
        )
        forecast = current.get("forecast") or {}
        forecast_line = (
            "FORECAST future aggressor-buy trade share"
            f" | probability {_format_probability(forecast.get('probability_buy'))}"
        )
        minimum_trades = manifest["minimum_label_trades"]
        live_trades = current["live_label_trades"]
        if live_trades >= minimum_trades:
            label_state = "on track"
        elif live_trades > 0:
            label_state = "below minimum"
        else:
            label_state = "collecting"
        diagnostic_note = (
            " | diagnostic capture — not scored" if manifest.get("mode") == "diagnostic" else ""
        )
        if live_trades:
            outcome_line = (
                f"OUTCOME  {label_state}"
                f" | {live_trades}/{minimum_trades} label trades"
                f" | captured buy share {_format_probability(current.get('live_buy_ratio'))}"
                f"{diagnostic_note}"
            )
        else:
            outcome_line = (
                f"OUTCOME  {label_state}"
                f" | 0/{minimum_trades} label trades"
                f" | no trades observed yet{diagnostic_note}"
            )
        feature_line = (
            f"FEATURES input trades {features.get('trade_count', '-')}"
            f" | buy/sell {features.get('buy_count', '-')}/{features.get('sell_count', '-')}"
            f" | historical buy share {_format_probability(features.get('buy_ratio'))}"
            f" | closing book imbalance {_format_signed(features.get('signed_imbalance'))}"
        )
        diagnostics = forecast.get("diagnostics") or {}
        baselines = diagnostics.get("baseline_probabilities") or {}
        artifact = snapshot.get("artifact") or {}
        raw_probability = forecast.get("raw_probability_buy")
        calibration_note = ""
        if artifact.get("calibration_status") not in (None, "fitted"):
            calibration_note = f" | raw (uncalibrated) {_format_probability(raw_probability)}"
        model_line = (
            f"MODELS   Born {_format_probability(forecast.get('probability_buy'))}"
            f"{calibration_note}"
            f" | persistence {_format_probability(baselines.get('flow_persistence_v1'))}"
            f" | development prior {_format_probability(baselines.get('development_prior_v1'))}"
            f" | logistic {_format_probability(baselines.get('regularized_logistic_v1'))}"
        )
        label_line = (
            f"         minimum label trades {current['live_label_trades']}/"
            f"{snapshot['manifest']['minimum_label_trades']}"
        )
        label_detail_line = (
            f"      quantity {current['live_buy_quantity']}/"
            f"{current['live_sell_quantity']}"
            f" | quantity buy ratio {_format_probability(current.get('live_buy_quantity_ratio'))}"
        )
    else:
        now_line = f"ACTION   {phase} | waiting for the first finalized input window"
        window_line = "WINDOWS  waiting for sufficient causal history"
        forecast_line = "FORECAST not created"
        outcome_line = "OUTCOME  unavailable until a forecast exists"
        feature_line = "FEATURES waiting for first feature window"
        model_line = "MODELS   waiting for first forecast"
        label_line = ""
        label_detail_line = ""

    latest = snapshot["latest_result"]
    if latest:
        probability = latest.get("probability_buy")
        probability_text = f"{probability:.3f}" if probability is not None else "-"
        label = latest.get("label") or {}
        scoreable_statuses = {
            ForecastStatus.RESOLVED_SCOREABLE.value,
            ForecastStatus.RESOLVED_ELIGIBLE.value,
        }
        scoreable_result = latest["status"] in scoreable_statuses
        result = "SCOREABLE" if scoreable_result else "NOT SCORED"
        result_color = "green" if scoreable_result else "yellow"
        last_line = (
            f"LAST     forecast {probability_text}"
            f" | captured buy share {_format_probability(label.get('buy_ratio'))}"
            f" from {label.get('trade_count', '-')} trades"
            f" | {_style(result, result_color, color)}"
        )
        exclusions = ", ".join(latest.get("exclusions") or ()) or "-"
        last_detail_line = f"         reason {'none' if scoreable_result else exclusions}"
    else:
        last_line = "LAST  no completed slot yet"
        last_detail_line = ""

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
    integrity_line = f"SYSTEM   lifecycle integrity {integrity_text}"
    artifact = snapshot.get("artifact") or {}
    evidence_line = (
        f"EVIDENCE {manifest.get('mode', 'diagnostic').upper()}"
        f" | artifact {artifact.get('purpose', manifest.get('artifact_purpose', 'unknown'))}"
        f" | calibration {artifact.get('calibration_status', 'unknown')}"
        f" | continuity {'certifiable' if provider.get('coverage_certifiable') else 'not certifiable'}"
    )
    warning = _warning_line(snapshot, color)
    footer = (
        f"Ctrl-C stop | run ...{snapshot['run_id'][-24:]}"
        if snapshot["status"] == "running"
        else f"Run finished | ...{snapshot['run_id'][-24:]}"
    )
    lines = [
        header,
        _rule(width),
        goals_line,
        run_line,
        slots_line,
        exclusions_line,
    ]
    if blocker_line:
        lines.append(blocker_line)
    lines.extend(
        [
            now_line,
            window_line,
            forecast_line,
            outcome_line,
            last_line,
            evidence_line,
            data_line,
            integrity_line,
            warning,
        ]
    )
    if view == "detail":
        detail_lines = [
            _rule(width),
            market_line,
            market_detail_line,
            feature_line,
            model_line,
        ]
        if label_line:
            detail_lines.append(label_line)
        if label_detail_line:
            detail_lines.append(
                "         quantity context "
                f"{current['live_buy_quantity']} buy / "
                f"{current['live_sell_quantity']} sell"
                " (not the forecast target)"
            )
        provider_detail = (
            f"CAPTURE  reconnects {provider.get('reconnects', 0)}"
            f" | detected gaps {provider.get('sequence_gaps', 0)}"
            f" | unresolved gaps {provider.get('unresolved_gaps', 0)}"
            f" | clock uncertainty "
            f"{_format_decimal(provider.get('clock_uncertainty_ms'), 1)}ms"
        )
        detail_lines.append(provider_detail)
        lines.extend(detail_lines)
    if last_detail_line:
        lines.append(last_detail_line)
    lines.extend(
        [
            _rule(width),
            footer,
        ]
    )
    return "\n".join(_fit_line(line, width) for line in lines) + "\n"


def format_final_summary(
    snapshot: dict[str, Any],
    analysis_document: dict[str, Any] | None = None,
) -> str:
    elapsed_s = max(
        0,
        (snapshot["updated_at_ms"] - snapshot["created_at_ms"]) / 1000,
    )
    integrity = snapshot["integrity"]
    manifest = snapshot["manifest"]
    mode = manifest.get("mode", "diagnostic")
    evidence = snapshot.get("evidence") or {}
    scoreable = snapshot["eligible_progress"]["eligible"]
    target = snapshot["eligible_progress"]["target"]
    tally = snapshot.get("slot_tally") or _slot_tally(snapshot.get("forecast_counts", {}))
    exclusions = snapshot.get("exclusion_counts", {})
    database = snapshot.get("database_path") or "-"
    run_id = snapshot["run_id"]
    lines = [
        f"Exchange-Q {mode} run finished",
        f"status:      {snapshot['status']}",
        f"duration:    {_format_duration(elapsed_s)}",
        f"progress:    {_format_progress(snapshot['terminal_slots'], snapshot['terminal_slot_limit'])}",
        f"scoreable:   {scoreable}/{target}",
        (
            "slot tally:  "
            f"awaiting {tally['awaiting']} | "
            f"scoreable {tally['scoreable']} | "
            f"unscoreable {tally['unscoreable']} | "
            f"skipped {tally['skipped']} | "
            f"cancelled {tally['cancelled']}"
        ),
        f"exclusions:  {_format_exclusions_line(exclusions, limit=5).removeprefix('EXCLUSIONS ')}",
        f"integrity:   {integrity['state']} ({integrity['error_count']} errors)",
        f"capture:     {evidence.get('capture_quality', 'uncertified')}",
        f"evidence:    {evidence.get('evidence_status', mode)}",
        f"run ID:      {run_id}",
        f"database:    {database}",
        f"artifact:    {snapshot.get('artifact_path') or '-'}",
    ]
    if mode == "diagnostic":
        lines.append("note:        diagnostic captured ratios are descriptive, not scored evidence")
    report_document = analysis_document or report_document_from_snapshot(snapshot)
    lines.append("")
    lines.append(
        format_research_report(
            report_document,
            database=None if database == "-" else database,
        )
    )
    if database != "-":
        lines.extend(
            [
                (
                    "status cmd:  ./scripts/exchange-q status "
                    f"--database {database} --run-id {run_id} --json"
                ),
                (
                    "analyze cmd: ./scripts/exchange-q analyze "
                    f"--database {database} --run-id {run_id}"
                ),
                (
                    "report cmd:  ./scripts/exchange-q report "
                    f"--database {database} --run-id {run_id}"
                ),
            ]
        )
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
    return f"[exchange-q] EVENT type={event['event_type']} slot={slot} detail={detail}"


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
        ForecastStatus.FORECASTED,
        ForecastStatus.AWAITING_LABEL,
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
    live_buy_count = 0
    live_sell_count = 0
    live_buy_quantity = 0.0
    live_sell_quantity = 0.0
    if slot["status"] in {
        ForecastStatus.FORECASTED,
        ForecastStatus.AWAITING_LABEL,
        ForecastStatus.CREATED,
        ForecastStatus.PENDING_LABEL,
    }:
        row = store.connection.execute(
            """
            SELECT
                SUM(CASE WHEN aggressor_side = 'buy' THEN 1 ELSE 0 END),
                SUM(CASE WHEN aggressor_side = 'sell' THEN 1 ELSE 0 END),
                SUM(CASE WHEN aggressor_side = 'buy' THEN CAST(quantity AS REAL) ELSE 0 END),
                SUM(CASE WHEN aggressor_side = 'sell' THEN CAST(quantity AS REAL) ELSE 0 END)
            FROM trades
            WHERE provider = ? AND symbol = ?
              AND exchange_time_ms >= ? AND exchange_time_ms < ?
            """,
            (
                provider,
                symbol,
                slot["slot_start_ms"],
                slot["slot_end_ms"],
            ),
        ).fetchone()
        live_buy_count = row[0] or 0
        live_sell_count = row[1] or 0
        live_buy_quantity = row[2] or 0.0
        live_sell_quantity = row[3] or 0.0
    live_label_trades = live_buy_count + live_sell_count
    live_quantity = live_buy_quantity + live_sell_quantity
    return {
        **slot,
        "live_label_trades": live_label_trades,
        "live_buy_count": live_buy_count,
        "live_sell_count": live_sell_count,
        "live_buy_ratio": (live_buy_count / live_label_trades if live_label_trades else None),
        "live_buy_quantity": _format_quantity(live_buy_quantity),
        "live_sell_quantity": _format_quantity(live_sell_quantity),
        "live_buy_quantity_ratio": (live_buy_quantity / live_quantity if live_quantity else None),
    }


def _market_snapshot(store: V7Store, provider: str, symbol: str) -> dict[str, Any]:
    trade = store.connection.execute(
        """
        SELECT aggressor_side, price, quantity, received_time_ms
        FROM trades
        WHERE provider = ? AND symbol = ?
        ORDER BY received_time_ms DESC
        LIMIT 1
        """,
        (provider, symbol),
    ).fetchone()
    book = store.connection.execute(
        """
        SELECT data_json, received_time_ms
        FROM books
        WHERE provider = ? AND symbol = ?
        ORDER BY received_time_ms DESC
        LIMIT 1
        """,
        (provider, symbol),
    ).fetchone()
    result: dict[str, Any] = {
        "last_price": None,
        "last_side": None,
        "last_quantity": None,
        "last_trade_ms": None,
        "best_bid": None,
        "best_ask": None,
        "bid_quantity": None,
        "ask_quantity": None,
        "midpoint": None,
        "spread": None,
        "book_imbalance": None,
        "last_book_ms": None,
    }
    if trade:
        result.update(
            {
                "last_side": trade["aggressor_side"],
                "last_price": float(trade["price"]),
                "last_quantity": trade["quantity"],
                "last_trade_ms": trade["received_time_ms"],
            }
        )
    if book:
        payload = json.loads(book["data_json"])
        best_bid = float(payload["best_bid"])
        best_ask = float(payload["best_ask"])
        bid_quantity = float(payload["bid_quantity"])
        ask_quantity = float(payload["ask_quantity"])
        midpoint = (best_bid + best_ask) / 2
        total_quantity = bid_quantity + ask_quantity
        result.update(
            {
                "best_bid": best_bid,
                "best_ask": best_ask,
                "bid_quantity": payload["bid_quantity"],
                "ask_quantity": payload["ask_quantity"],
                "midpoint": midpoint,
                "spread": (best_ask - best_bid) / midpoint if midpoint else None,
                "book_imbalance": (
                    (bid_quantity - ask_quantity) / total_quantity if total_quantity else 0.0
                ),
                "last_book_ms": book["received_time_ms"],
            }
        )
    return result


def _phase(run_status: str, slot: dict[str, Any] | None) -> str:
    if run_status != "running":
        return run_status.upper()
    if not slot:
        return "CONNECTING"
    if slot["status"] == ForecastStatus.SCHEDULED:
        return "WAITING"
    if slot["status"] in {
        ForecastStatus.FORECASTED,
        ForecastStatus.AWAITING_LABEL,
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
        ForecastStatus.FORECASTED,
        ForecastStatus.AWAITING_LABEL,
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
    manifest = snapshot.get("manifest") or {}
    if not integrity["valid"]:
        codes = ", ".join(
            f"{_integrity_label(name)}={count}" for name, count in integrity["error_codes"].items()
        )
        return f"WARN  {_style('RUN QUARANTINED', 'red', color)} | {codes}"
    # Recovered sequence gaps (e.g. KuCoin depth resync that succeeded) must
    # not paint a permanent red WARN; only unresolved continuity defects do.
    if provider.get("unresolved_gaps", 0):
        return f"WARN  {_style('PROVIDER GAPS DETECTED', 'red', color)}"
    if snapshot["stream_state"] == "stale":
        return f"WARN  {_style('MARKET DATA IS STALE', 'red', color)}"
    if manifest.get("provider") == "htx-ws":
        return (
            f"NOTE  {_style('DIAGNOSTIC ONLY', 'yellow', color)}"
            " | HTX continuity cannot be certified"
        )
    return ""


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


def _format_goals_line(snapshot: dict[str, Any], *, mode: str) -> str:
    manifest = snapshot["manifest"]
    terminal = snapshot["terminal_slots"]
    limit = snapshot["terminal_slot_limit"]
    scoreable = snapshot["eligible_progress"]["eligible"]
    target = snapshot["eligible_progress"]["target"]
    horizon_s = manifest["horizon_ms"] / 1000
    lookback_s = manifest["lookback_ms"] / 1000
    minimum_trades = manifest["minimum_label_trades"]
    objective = "PRIMARY SCOREABLE" if mode == "primary" else "DIAGNOSTIC CAPTURE"
    if mode == "primary":
        scoreable_text = f"scoreable {scoreable}/{target}"
    else:
        scoreable_text = "scoreable n/a (diagnostic)"
    limit_text = _format_progress(terminal, limit) if limit is not None else "-"
    return (
        f"GOALS    {objective}"
        f" | terminal slots {limit_text}"
        f" | {scoreable_text}"
        f" | horizon {horizon_s:g}s | lookback {lookback_s:g}s"
        f" | min label trades {minimum_trades}"
    )


def _format_blocker_line(snapshot: dict[str, Any], color: bool) -> str:
    if snapshot["status"] != "running":
        return ""
    if snapshot["stream_state"] != "no_data":
        return ""
    elapsed_s = max(
        0,
        (snapshot["observed_at_ms"] - snapshot["created_at_ms"]) / 1000,
    )
    if elapsed_s <= 30:
        return ""
    provider = snapshot.get("provider_health") or {}
    detail = provider.get("detail") or "none"
    connected = "connected" if provider.get("connected") else "disconnected"
    return (
        f"BLOCKER  {_style('NO MARKET EVENTS', 'red', color)}"
        f" | provider {connected}"
        f" | check connectivity"
        f" | detail: {detail}"
    )


def _integrity_label(code: str) -> str:
    return {
        "label_resolved_early": "early resolution",
        "label_trade_count_mismatch": "label mismatch",
        "forecast_created_early": "early forecast",
        "missing_forecast_transition": "missing forecast event",
        "missing_resolution_transition": "missing resolution event",
        "missing_resolved_label": "missing label",
        "terminal_run_has_open_slots": "terminal run has open slots",
    }.get(code, code.replace("_", " "))


def _rule(width: int) -> str:
    return "-" * width


def _fit_line(line: str, width: int) -> str:
    visible = re.sub(r"\x1b\[[0-9;]*m", "", line)
    if len(visible) <= width:
        return line + " " * (width - len(visible))
    return visible[: max(1, width - 1)] + "…"


def _format_probability(value: Any) -> str:
    return f"{float(value):.3f}" if value is not None else "-"


def _format_signed(value: Any) -> str:
    return f"{float(value):+.3f}" if value is not None else "-"


def _format_decimal(value: Any, places: int) -> str:
    return f"{float(value):.{places}f}" if value is not None else "-"


def _format_bps(value: Any) -> str:
    return f"{float(value) * 10_000:.2f}bp" if value is not None else "-"


def _format_spread(value: Any) -> str:
    if value is None:
        return "-"
    basis_points = float(value) * 10_000
    if basis_points >= 0.01:
        return f"{basis_points:.3f} bp"
    return f"{float(value) * 1_000_000:.3f} ppm"


def _format_price(value: Any) -> str:
    if value is None:
        return "-"
    number = float(value)
    return f"{number:,.2f}" if number >= 10 else f"{number:.6f}"


def _format_quantity(value: float) -> str:
    return f"{value:.8g}"


def _format_compact_number(value: Any) -> str:
    if value is None:
        return "-"
    number = float(value)
    absolute = abs(number)
    if absolute >= 1_000_000:
        return f"{number / 1_000_000:.2f}M"
    if absolute >= 1_000:
        return f"{number / 1_000:.2f}K"
    return f"{number:.4g}"


def _format_ms_age(observed_at_ms: int, timestamp_ms: int | None) -> str:
    if timestamp_ms is None:
        return "-"
    return _format_age(max(0.0, (observed_at_ms - timestamp_ms) / 1000))


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


def _slot_tally(counts: dict[str, int]) -> dict[str, int]:
    awaiting_statuses = (
        ForecastStatus.SCHEDULED,
        ForecastStatus.FORECASTED,
        ForecastStatus.AWAITING_LABEL,
        ForecastStatus.CREATED,
        ForecastStatus.PENDING_LABEL,
    )
    scoreable = counts.get(ForecastStatus.RESOLVED_SCOREABLE.value, 0) + counts.get(
        ForecastStatus.RESOLVED_ELIGIBLE.value, 0
    )
    unscoreable = counts.get(ForecastStatus.RESOLVED_UNSCOREABLE.value, 0) + counts.get(
        ForecastStatus.RESOLVED_INELIGIBLE.value, 0
    )
    return {
        "awaiting": sum(counts.get(status.value, 0) for status in awaiting_statuses),
        "scoreable": scoreable,
        "unscoreable": unscoreable,
        "skipped": counts.get(ForecastStatus.SKIPPED.value, 0),
        "cancelled": counts.get(ForecastStatus.CANCELLED.value, 0),
        "failed": counts.get(ForecastStatus.FAILED.value, 0),
    }


def _format_slots_line(tally: dict[str, int], *, mode: str) -> str:
    scoreable_label = "not scored" if mode == "diagnostic" else "scoreable"
    return (
        f"SLOTS    awaiting {tally['awaiting']}"
        f" | {scoreable_label} {tally['scoreable']}"
        f" | unscoreable {tally['unscoreable']}"
        f" | skipped {tally['skipped']}"
        f" | cancelled {tally['cancelled']}"
    )


def _format_exclusions_line(
    exclusion_counts: dict[str, int],
    *,
    limit: int = 3,
) -> str:
    if not exclusion_counts:
        return "EXCLUSIONS none yet"
    parts = [
        f"{reason}={count}"
        for reason, count in sorted(
            exclusion_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:limit]
    ]
    return "EXCLUSIONS " + " | ".join(parts)


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
