from __future__ import annotations

import asyncio
import os
import signal
import time
import uuid

from exchange_q.capture import CaptureHooks
from exchange_q.domain import (
    TERMINAL_FORECAST_STATUSES,
    BookEvent,
    ForecastStatus,
    RunManifest,
    TradeEvent,
)
from exchange_q.models import ModelArtifact, NormalizedBornModel
from exchange_q.scheduler import FixedSlotScheduler
from exchange_q.store import V7Store


class LiveRunner:
    LEASE_TTL_MS = 30_000
    HEARTBEAT_INTERVAL_S = 5.0
    FIRST_EVENT_TIMEOUT_MS = 60_000
    EVENT_POLL_TIMEOUT_S = 5.0

    def __init__(
        self,
        store: V7Store,
        provider,
        manifest: RunManifest,
        artifact: ModelArtifact,
    ):
        if artifact.artifact_hash != manifest.model_artifact_hash:
            raise ValueError("manifest and model artifact hashes differ")
        self.store = store
        self.provider = provider
        self.manifest = manifest
        self.artifact = artifact
        self.model = NormalizedBornModel()
        self.scheduler = FixedSlotScheduler(manifest.horizon_ms, manifest.cadence_ms)
        self.owner_id = uuid.uuid4().hex
        self._stopping = asyncio.Event()
        self._last_slot_start: int | None = None
        self._stream_start_ms: int | None = None
        self._capture_sessions: set[tuple[str, str]] = set()
        self._install_capture_hooks()

    def _install_capture_hooks(self) -> None:
        if not hasattr(self.provider, "set_capture_hooks"):
            return
        self.provider.set_capture_hooks(
            CaptureHooks(
                record_clock_sample=self._record_clock_sample,
                record_recovery=self._record_recovery,
                record_continuity_gap=self._record_continuity_gap,
            )
        )

    def _record_clock_sample(
        self, local_send_ms: int, local_receive_ms: int, exchange_time_ms: int
    ) -> None:
        self.store.record_clock_sample(
            self.manifest.provider,
            local_send_ms,
            local_receive_ms,
            exchange_time_ms,
        )

    def _record_recovery(
        self,
        stream_kind: str,
        missing_from: int,
        missing_to: int,
        status: str,
        recovered_count: int,
        detail: str,
    ) -> None:
        self.store.record_recovery(
            self.manifest.provider,
            self.manifest.symbol,
            stream_kind,
            missing_from,
            missing_to,
            status,
            recovered_count,
            detail,
        )

    def _record_continuity_gap(
        self,
        stream_kind: str,
        start_ms: int,
        end_ms: int,
        *,
        complete: bool,
        first_sequence: int | None,
        last_sequence: int | None,
        reasons: tuple[str, ...],
    ) -> None:
        self.store.record_continuity_gap(
            self.manifest.provider,
            self.manifest.symbol,
            stream_kind,
            start_ms,
            end_ms,
            complete=complete,
            first_sequence=first_sequence,
            last_sequence=last_sequence,
            reasons=reasons,
        )

    async def run(self) -> None:
        self.store.acquire_lease(
            self.manifest.run_id,
            self.owner_id,
            os.getpid(),
            ttl_ms=self.LEASE_TTL_MS,
        )
        self.store.set_run_status(self.manifest.run_id, "running")
        self._restore_progress()
        self._install_signal_handlers()
        terminal_status = "stopped"
        detail = ""
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        run_started_ms = int(time.time() * 1000)
        try:
            events = self.provider.events(self.manifest.symbol)
            while not self._stopping.is_set():
                try:
                    event = await asyncio.wait_for(
                        events.__anext__(),
                        timeout=self.EVENT_POLL_TIMEOUT_S,
                    )
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    if self._stream_start_ms is None:
                        elapsed_ms = int(time.time() * 1000) - run_started_ms
                        if elapsed_ms >= self.FIRST_EVENT_TIMEOUT_MS:
                            health = self.provider.health()
                            if health.last_event_received_ms is None or not health.connected:
                                raise RuntimeError(
                                    "provider_no_events_timeout: no market events "
                                    f"after {elapsed_ms}ms; "
                                    f"detail={health.detail or 'none'}"
                                )
                    continue
                if self._stream_start_ms is None:
                    self._stream_start_ms = event.exchange_time_ms
                if isinstance(event, TradeEvent):
                    if self._is_late_event(event) or self._is_retroactive_label_trade(event):
                        continue
                    self.store.save_trade(event)
                    self._checkpoint_event(event, "trades")
                elif isinstance(event, BookEvent):
                    self.store.save_book(event)
                    self._checkpoint_event(event, "books")
                scheduling_time_ms = (
                    event.exchange_time_ms
                    if self.manifest.mode == "primary"
                    else max(event.exchange_time_ms, event.received_time_ms)
                )
                await self._advance(scheduling_time_ms)
                self.store.heartbeat(self.manifest.run_id, self.owner_id)
                status = self.store.status(self.manifest.run_id)
                eligible = status["forecast_counts"].get(ForecastStatus.RESOLVED_SCOREABLE.value, 0)
                if eligible >= self.manifest.target_eligible:
                    terminal_status = "completed"
                    break
                terminal_slots = sum(
                    status["forecast_counts"].get(slot_status, 0)
                    for slot_status in (
                        ForecastStatus.SKIPPED,
                        ForecastStatus.RESOLVED_SCOREABLE,
                        ForecastStatus.RESOLVED_UNSCOREABLE,
                        ForecastStatus.CANCELLED,
                        ForecastStatus.RESOLVED_ELIGIBLE,
                        ForecastStatus.RESOLVED_INELIGIBLE,
                        ForecastStatus.EXPIRED,
                        ForecastStatus.FAILED,
                    )
                )
                if (
                    self.manifest.terminal_slot_limit is not None
                    and terminal_slots >= self.manifest.terminal_slot_limit
                ):
                    terminal_status = "diagnostic_limit"
                    break
        except Exception as exc:
            terminal_status = "failed"
            detail = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._stopping.set()
            await self.provider.close()
            heartbeat_task.cancel()
            heartbeat_error = None
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001
                heartbeat_error = exc
                terminal_status = "failed"
                detail = f"{type(exc).__name__}: {exc}"
            if terminal_status in {"stopped", "failed", "completed", "diagnostic_limit"}:
                reason = {
                    "stopped": "operator_stop_before_slot_completion",
                    "failed": "runner_failed_before_slot_completion",
                    "completed": "target_reached_before_slot_completion",
                    "diagnostic_limit": "diagnostic_limit_before_slot_completion",
                }[terminal_status]
                self.store.cancel_open_slots(self.manifest.run_id, reason)
            self.store.set_run_status(self.manifest.run_id, terminal_status, detail)
            self.store.release_lease(self.manifest.run_id, self.owner_id)
            if heartbeat_error is not None:
                raise heartbeat_error

    async def _advance(self, observed_time_ms: int) -> None:
        current_slot = self.scheduler.slot_at_or_before(observed_time_ms)
        if self._last_slot_start is None:
            next_slot = self.scheduler.next_after(current_slot.start_ms)
            self._last_slot_start = next_slot.start_ms
            self.store.schedule_slot(self.manifest.run_id, next_slot.start_ms, next_slot.end_ms)
            return

        while self._last_slot_start - self.manifest.decision_lead_ms <= observed_time_ms:
            if self._terminal_limit_reached():
                return
            active_start = self._last_slot_start
            active_end = active_start + self.manifest.horizon_ms
            row = self.store.connection.execute(
                """
                SELECT status FROM forecast_slots
                WHERE run_id = ? AND slot_start_ms = ?
                """,
                (self.manifest.run_id, active_start),
            ).fetchone()
            if not row:
                raise RuntimeError(f"missing active slot {active_start}")
            status = ForecastStatus(row["status"])
            if status == ForecastStatus.SCHEDULED:
                decision_at = active_start - self.manifest.decision_lead_ms
                if observed_time_ms < decision_at:
                    return
                self._create_or_skip(active_start, active_end)
                if self._terminal_limit_reached():
                    return
                row = self.store.connection.execute(
                    """
                    SELECT status FROM forecast_slots
                    WHERE run_id = ? AND slot_start_ms = ?
                    """,
                    (self.manifest.run_id, active_start),
                ).fetchone()
                status = ForecastStatus(row["status"])
            if status in (
                ForecastStatus.FORECASTED,
                ForecastStatus.AWAITING_LABEL,
                ForecastStatus.CREATED,
                ForecastStatus.PENDING_LABEL,
            ):
                resolution_at = active_end + self.manifest.settlement_delay_ms
                if observed_time_ms < resolution_at:
                    return
                if not self._capture_is_settled(active_end):
                    return
                self._resolve(active_start, active_end)
            if self._terminal_limit_reached():
                return
            if self._target_reached():
                return
            row = self.store.connection.execute(
                """
                SELECT status FROM forecast_slots
                WHERE run_id = ? AND slot_start_ms = ?
                """,
                (self.manifest.run_id, active_start),
            ).fetchone()
            if ForecastStatus(row["status"]) not in (
                ForecastStatus.SKIPPED,
                ForecastStatus.RESOLVED_SCOREABLE,
                ForecastStatus.RESOLVED_UNSCOREABLE,
                ForecastStatus.CANCELLED,
                ForecastStatus.RESOLVED_ELIGIBLE,
                ForecastStatus.RESOLVED_INELIGIBLE,
                ForecastStatus.EXPIRED,
                ForecastStatus.FAILED,
            ):
                return
            next_slot = self.scheduler.next_after(active_start)
            self.store.schedule_slot(self.manifest.run_id, next_slot.start_ms, next_slot.end_ms)
            self._last_slot_start = next_slot.start_ms

    def _create_or_skip(self, slot_start_ms: int, slot_end_ms: int) -> None:
        feature_end = slot_start_ms - self.manifest.decision_lead_ms
        feature_start = feature_end - self.manifest.lookback_ms
        features = self.store.build_features(
            self.manifest.provider,
            self.manifest.symbol,
            feature_start,
            feature_end,
        )
        if features is None:
            self.store.skip_slot(self.manifest.run_id, slot_start_ms, ["insufficient_feature_data"])
            return
        forecast = self.model.predict(features, self.artifact)
        self.store.create_forecast(
            self.manifest.run_id,
            slot_start_ms,
            features,
            forecast,
            self.artifact.artifact_hash,
        )

    def _resolve(self, slot_start_ms: int, slot_end_ms: int) -> None:
        row = self.store.connection.execute(
            """
            SELECT status FROM forecast_slots
            WHERE run_id = ? AND slot_start_ms = ?
            """,
            (self.manifest.run_id, slot_start_ms),
        ).fetchone()
        if not row or row["status"] not in {
            ForecastStatus.AWAITING_LABEL,
            ForecastStatus.PENDING_LABEL,
        }:
            return
        health = self.provider.health()
        complete = (
            health.coverage_certifiable
            and health.sequence_gaps == 0
            and health.unresolved_gaps == 0
            and self._stream_start_ms is not None
            and self._stream_start_ms <= slot_start_ms
            and not self.store.interval_has_unresolved_gap(
                self.manifest.provider,
                self.manifest.symbol,
                slot_start_ms,
                slot_end_ms,
            )
        )
        reasons = () if complete else ("provider_coverage_not_certifiable",)
        self.store.mark_coverage(
            self.manifest.provider,
            self.manifest.symbol,
            slot_start_ms,
            slot_end_ms,
            complete,
            reasons,
        )
        label = self.store.build_label(
            self.manifest.provider,
            self.manifest.symbol,
            slot_start_ms,
            slot_end_ms,
        )
        self.store.resolve_slot(
            self.manifest.run_id,
            slot_start_ms,
            label,
            self.manifest.minimum_label_trades,
        )

    def _restore_progress(self) -> None:
        row = self.store.connection.execute(
            """
            SELECT slot_start_ms, status FROM forecast_slots
            WHERE run_id = ? ORDER BY slot_start_ms DESC LIMIT 1
            """,
            (self.manifest.run_id,),
        ).fetchone()
        if not row:
            return
        latest_start = int(row["slot_start_ms"])
        latest_status = ForecastStatus(row["status"])
        if latest_status in (
            ForecastStatus.SCHEDULED,
            ForecastStatus.FORECASTED,
            ForecastStatus.AWAITING_LABEL,
            ForecastStatus.CREATED,
            ForecastStatus.PENDING_LABEL,
        ):
            self._last_slot_start = latest_start
            return
        next_slot = self.scheduler.next_after(latest_start)
        self.store.schedule_slot(self.manifest.run_id, next_slot.start_ms, next_slot.end_ms)
        self._last_slot_start = next_slot.start_ms

    def _terminal_limit_reached(self) -> bool:
        limit = self.manifest.terminal_slot_limit
        if limit is None:
            return False
        counts = self.store.status(self.manifest.run_id)["forecast_counts"]
        terminal_slots = sum(
            counts.get(status.value, 0)
            for status in (
                ForecastStatus.SKIPPED,
                ForecastStatus.RESOLVED_SCOREABLE,
                ForecastStatus.RESOLVED_UNSCOREABLE,
                ForecastStatus.CANCELLED,
                ForecastStatus.RESOLVED_ELIGIBLE,
                ForecastStatus.RESOLVED_INELIGIBLE,
                ForecastStatus.EXPIRED,
                ForecastStatus.FAILED,
            )
        )
        return terminal_slots >= limit

    def _target_reached(self) -> bool:
        counts = self.store.status(self.manifest.run_id)["forecast_counts"]
        scoreable = counts.get(ForecastStatus.RESOLVED_SCOREABLE.value, 0)
        return scoreable >= self.manifest.target_eligible

    def _capture_is_settled(self, slot_end_ms: int) -> bool:
        if self.manifest.mode != "primary":
            return True
        health = self.provider.health()
        return (
            health.connected
            and health.coverage_certifiable
            and health.trade_watermark_ms is not None
            and health.trade_watermark_ms >= slot_end_ms + self.manifest.settlement_delay_ms
        )

    def _is_late_event(self, event: TradeEvent) -> bool:
        if self.manifest.mode != "primary":
            return False
        row = self.store.connection.execute(
            """
            SELECT slot_start_ms, status FROM forecast_slots
            WHERE run_id = ? AND status IN (?, ?, ?, ?)
            ORDER BY slot_start_ms DESC LIMIT 1
            """,
            (
                self.manifest.run_id,
                ForecastStatus.FORECASTED.value,
                ForecastStatus.AWAITING_LABEL.value,
                ForecastStatus.CREATED.value,
                ForecastStatus.PENDING_LABEL.value,
            ),
        ).fetchone()
        if not row:
            return False
        feature_end = int(row["slot_start_ms"]) - self.manifest.decision_lead_ms
        if event.exchange_time_ms >= feature_end:
            return False
        self.store.record_continuity_gap(
            self.manifest.provider,
            self.manifest.symbol,
            "trades",
            event.exchange_time_ms,
            feature_end,
            complete=False,
            first_sequence=event.sequence,
            last_sequence=event.sequence,
            reasons=("late_event_crossed_boundary",),
        )
        return True

    def _is_retroactive_label_trade(self, event: TradeEvent) -> bool:
        terminal_statuses = tuple(status.value for status in TERMINAL_FORECAST_STATUSES)
        placeholders = ", ".join("?" for _ in terminal_statuses)
        row = self.store.connection.execute(
            f"""
            SELECT slot_start_ms, slot_end_ms FROM forecast_slots
            WHERE run_id = ?
              AND status IN ({placeholders})
              AND slot_start_ms <= ?
              AND slot_end_ms > ?
            LIMIT 1
            """,
            (
                self.manifest.run_id,
                *terminal_statuses,
                event.exchange_time_ms,
                event.exchange_time_ms,
            ),
        ).fetchone()
        if row is None:
            return False
        self.store.record_continuity_gap(
            self.manifest.provider,
            self.manifest.symbol,
            "trades",
            event.exchange_time_ms,
            int(row["slot_end_ms"]),
            complete=False,
            first_sequence=event.sequence,
            last_sequence=event.sequence,
            reasons=("retroactive_label_trade",),
        )
        return True

    def _checkpoint_event(self, event, stream_kind: str) -> None:
        if event.sequence is None or not event.session_id:
            return
        session_key = (event.session_id, stream_kind)
        if session_key not in self._capture_sessions:
            self.store.start_capture_session(
                event.session_id + "-" + stream_kind,
                event.provider,
                event.symbol,
                stream_kind,
            )
            self._capture_sessions.add(session_key)
        self.store.checkpoint_capture(
            event.provider,
            event.symbol,
            stream_kind,
            event.sequence,
            event.exchange_time_ms,
            event.received_time_ms,
            event.session_id + "-" + stream_kind,
        )

    def stop(self) -> None:
        self._stopping.set()
        try:
            asyncio.get_running_loop().create_task(self.provider.close())
        except RuntimeError:
            pass

    async def _heartbeat_loop(self) -> None:
        while not self._stopping.is_set():
            await asyncio.sleep(self.HEARTBEAT_INTERVAL_S)
            self.store.heartbeat(self.manifest.run_id, self.owner_id)

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for signal_number in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signal_number, self.stop)
            except NotImplementedError:
                pass
