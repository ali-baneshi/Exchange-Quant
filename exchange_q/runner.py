from __future__ import annotations

import asyncio
import os
import signal
import time
import uuid

from exchange_q.capture import CaptureHooks
from exchange_q.domain import (
    SCOREABLE_STATUSES,
    UNSCOREABLE_RESOLVED_STATUSES,
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
    STALL_TIMEOUT_MS = 120_000
    BACKPRESSURE_TIMEOUT_MS = 120_000
    EVENT_POLL_TIMEOUT_S = 5.0
    STATUS_CHECK_EVENT_INTERVAL = 200
    BOOK_CHECKPOINT_INTERVAL = 100
    WRITE_BATCH_MAX_EVENTS = 64
    WRITE_BATCH_MAX_MS = 50.0

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
        self._events_since_status_check = 0
        self._work_since_status_check = False
        self._books_since_checkpoint = 0
        self._write_batch: list[TradeEvent | BookEvent] = []
        self._write_batch_started_mono: float | None = None
        self._last_consumer_progress_ms: int | None = None
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
        self.store.set_live_capture_durability(True)
        self._restore_progress()
        self._install_signal_handlers()
        terminal_status = "stopped"
        detail = ""
        stream_exhausted = False
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        run_started_ms = int(time.time() * 1000)
        self._last_consumer_progress_ms = run_started_ms
        next_event: asyncio.Task | None = None
        try:
            events = self.provider.events(self.manifest.symbol)
            next_event = asyncio.create_task(events.__anext__())
            while not self._stopping.is_set():
                try:
                    event = await asyncio.wait_for(
                        asyncio.shield(next_event),
                        timeout=self.EVENT_POLL_TIMEOUT_S,
                    )
                except StopAsyncIteration:
                    if not self._stopping.is_set():
                        stream_exhausted = True
                    next_event = None
                    break
                except asyncio.TimeoutError:
                    if self._write_batch:
                        await self._flush_write_batch()
                    self._check_stream_watchdog(run_started_ms)
                    continue
                next_event = asyncio.create_task(events.__anext__())
                self._last_consumer_progress_ms = int(time.time() * 1000)
                if self._stream_start_ms is None:
                    self._stream_start_ms = event.exchange_time_ms
                self._write_batch.append(event)
                if self._write_batch_started_mono is None:
                    self._write_batch_started_mono = time.monotonic()
                should_flush = (
                    len(self._write_batch) >= self.WRITE_BATCH_MAX_EVENTS
                    or (
                        time.monotonic() - self._write_batch_started_mono
                        >= self.WRITE_BATCH_MAX_MS / 1000.0
                    )
                )
                if should_flush:
                    await self._flush_write_batch()
                self._events_since_status_check += 1
                if (
                    self._work_since_status_check
                    or self._events_since_status_check >= self.STATUS_CHECK_EVENT_INTERVAL
                ):
                    if self._write_batch:
                        await self._flush_write_batch()
                    self._work_since_status_check = False
                    self._events_since_status_check = 0
                    self.store.heartbeat(self.manifest.run_id, self.owner_id)
                    status = self.store.status(self.manifest.run_id)
                    eligible = status["forecast_counts"].get(
                        ForecastStatus.RESOLVED_SCOREABLE.value, 0
                    )
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
            if self._write_batch:
                await self._flush_write_batch()
            if terminal_status == "stopped":
                status = self.store.status(self.manifest.run_id)
                eligible = status["forecast_counts"].get(
                    ForecastStatus.RESOLVED_SCOREABLE.value, 0
                )
                if eligible >= self.manifest.target_eligible:
                    terminal_status = "completed"
                    stream_exhausted = False
                elif self.manifest.terminal_slot_limit is not None:
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
                    if terminal_slots >= self.manifest.terminal_slot_limit:
                        terminal_status = "diagnostic_limit"
                        stream_exhausted = False
        except Exception as exc:
            terminal_status = "failed"
            detail = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            if next_event is not None and not next_event.done():
                next_event.cancel()
                try:
                    await next_event
                except (asyncio.CancelledError, StopAsyncIteration):
                    pass
            self._stopping.set()
            try:
                if self._write_batch:
                    await self._flush_write_batch()
            except Exception:  # noqa: BLE001
                pass
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
            session_status = "ended" if terminal_status != "failed" else "failed"
            self.store.end_open_capture_sessions(session_status)
            self.store.set_live_capture_durability(False)
            if terminal_status in {"stopped", "failed", "completed", "diagnostic_limit"}:
                reason = {
                    "stopped": "operator_stop_before_slot_completion",
                    "failed": "runner_failed_before_slot_completion",
                    "completed": "target_reached_before_slot_completion",
                    "diagnostic_limit": "diagnostic_limit_before_slot_completion",
                }[terminal_status]
                if terminal_status == "stopped" and stream_exhausted:
                    reason = "provider_stream_exhausted_before_slot_completion"
                self.store.cancel_open_slots(self.manifest.run_id, reason)
            self.store.set_run_status(self.manifest.run_id, terminal_status, detail)
            self.store.release_lease(self.manifest.run_id, self.owner_id)
            if heartbeat_error is not None:
                raise heartbeat_error

    def _check_stream_watchdog(self, run_started_ms: int) -> None:
        now_ms = int(time.time() * 1000)
        health = self.provider.health()
        if self._stream_start_ms is None:
            elapsed_ms = now_ms - run_started_ms
            if elapsed_ms >= self.FIRST_EVENT_TIMEOUT_MS:
                if health.last_event_received_ms is None or not health.connected:
                    raise RuntimeError(
                        "provider_no_events_timeout: no market events "
                        f"after {elapsed_ms}ms; "
                        f"detail={health.detail or 'none'}"
                    )
            return
        pending = int(health.pending_events or 0)
        dropped_trades = int(getattr(health, "queue_dropped_trades", 0) or 0)
        last_ws_ms = getattr(health, "last_ws_received_ms", None)
        last_consumer_ms = health.last_event_received_ms or self._last_consumer_progress_ms
        if pending > 0 or dropped_trades > 0:
            progress_ms = self._last_consumer_progress_ms or run_started_ms
            if now_ms - progress_ms >= self.BACKPRESSURE_TIMEOUT_MS:
                raise RuntimeError(
                    "consumer_backpressure: consumer idle for "
                    f"{now_ms - progress_ms}ms with pending={pending} "
                    f"dropped_trades={dropped_trades}; "
                    f"detail={health.detail or 'none'}"
                )
            return
        reference_ms = last_ws_ms if last_ws_ms is not None else last_consumer_ms
        if reference_ms is not None and now_ms - reference_ms >= self.STALL_TIMEOUT_MS:
            raise RuntimeError(
                "provider_stalled: no market events for "
                f"{now_ms - reference_ms}ms after stream start; "
                f"detail={health.detail or 'none'}"
            )

    async def _flush_write_batch(self) -> None:
        batch = self._write_batch
        if not batch:
            return
        self._write_batch = []
        self._write_batch_started_mono = None
        book_group: list[BookEvent] = []

        async def flush_books() -> None:
            nonlocal book_group
            if not book_group:
                return
            with self.store.transaction():
                for book in book_group:
                    self.store.save_book(book)
                    self._books_since_checkpoint += 1
                    if self._books_since_checkpoint >= self.BOOK_CHECKPOINT_INTERVAL:
                        self._checkpoint_event(book, "books")
                        self._books_since_checkpoint = 0
            for book in book_group:
                await self._advance(book.exchange_time_ms)
            book_group = []

        for event in batch:
            if isinstance(event, BookEvent):
                book_group.append(event)
                if len(book_group) >= self.WRITE_BATCH_MAX_EVENTS:
                    await flush_books()
                continue
            await flush_books()
            if isinstance(event, TradeEvent):
                with self.store.transaction():
                    self.store.save_trade(event)
                    self._checkpoint_event(event, "trades")
                self._record_boundary_violations(event)
                await self._advance(event.exchange_time_ms)
        await flush_books()

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
                self._create_or_skip(active_start, active_end, observed_time_ms)
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
                self._resolve(active_start, active_end, observed_time_ms)
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

    def _create_or_skip(self, slot_start_ms: int, slot_end_ms: int, observed_time_ms: int) -> None:
        feature_end = slot_start_ms - self.manifest.decision_lead_ms
        feature_start = feature_end - self.manifest.lookback_ms
        book_time = self.store.latest_book_time(
            self.manifest.provider,
            self.manifest.symbol,
            feature_end,
        )
        if book_time is not None and feature_end - book_time > self.manifest.lookback_ms:
            # The book snapshot feeding signed_imbalance/spread is older than
            # the entire trade feature window; score it as disconnected rather
            # than silently forecasting from arbitrarily stale market state.
            self.store.skip_slot(self.manifest.run_id, slot_start_ms, ["stale_book"])
            self._work_since_status_check = True
            return
        features = self.store.build_features(
            self.manifest.provider,
            self.manifest.symbol,
            feature_start,
            feature_end,
        )
        if features is None:
            self.store.skip_slot(self.manifest.run_id, slot_start_ms, ["insufficient_feature_data"])
            self._work_since_status_check = True
            return
        forecast = self.model.predict(features, self.artifact)
        self.store.create_forecast(
            self.manifest.run_id,
            slot_start_ms,
            features,
            forecast,
            self.artifact.artifact_hash,
            observed_decision_ms=observed_time_ms,
        )
        self._work_since_status_check = True

    def _resolve(self, slot_start_ms: int, slot_end_ms: int, observed_time_ms: int) -> None:
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
        # Gating is interval-scoped to the trade stream: lifetime counters and
        # recovered book resyncs must not poison label resolution, while any
        # unrecovered trade gap overlapping the feature or label window does.
        feature_start_ms = slot_start_ms - self.manifest.decision_lead_ms - self.manifest.lookback_ms
        complete = (
            health.coverage_certifiable
            and self._stream_start_ms is not None
            and self._stream_start_ms <= slot_start_ms
            and not self.store.interval_has_unresolved_gap(
                self.manifest.provider,
                self.manifest.symbol,
                feature_start_ms,
                slot_end_ms,
                stream_kind="trades",
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
            observed_decision_ms=observed_time_ms,
        )
        self._work_since_status_check = True

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
        health = self.provider.health()
        if self.manifest.mode != "primary":
            # Diagnostic runs settle on drain: resolve only once the provider
            # has no queued events, so labels see every delivered trade.
            return health.pending_events == 0
        return (
            health.connected
            and health.coverage_certifiable
            and health.trade_watermark_ms is not None
            and health.trade_watermark_ms >= slot_end_ms + self.manifest.settlement_delay_ms
        )

    def _record_boundary_violations(self, event: TradeEvent) -> None:
        if self._is_late_event(event):
            return
        self._is_retroactive_label_trade(event)

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
        # Only slots with a computed label can suffer label mutation. Trades
        # landing in cancelled/skipped windows (e.g. live deliveries after a
        # resume seam) are persisted without poisoning continuity, because no
        # label was ever computed for those slots.
        resolved_statuses = tuple(
            status.value
            for status in SCOREABLE_STATUSES | UNSCOREABLE_RESOLVED_STATUSES
        )
        placeholders = ", ".join("?" for _ in resolved_statuses)
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
                *resolved_statuses,
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
