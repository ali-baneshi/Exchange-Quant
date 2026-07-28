from __future__ import annotations

import asyncio
import os
import signal
import uuid

from exchange_q.domain import BookEvent, ForecastStatus, RunManifest, TradeEvent
from exchange_q.models import ModelArtifact, NormalizedBornModel
from exchange_q.scheduler import FixedSlotScheduler
from exchange_q.store import V7Store


class LiveRunner:
    LEASE_TTL_MS = 30_000
    HEARTBEAT_INTERVAL_S = 5.0

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
        self.scheduler = FixedSlotScheduler(
            manifest.horizon_ms, manifest.cadence_ms
        )
        self.owner_id = uuid.uuid4().hex
        self._stopping = asyncio.Event()
        self._last_slot_start: int | None = None
        self._stream_start_ms: int | None = None

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
        try:
            async for event in self.provider.events(self.manifest.symbol):
                if self._stopping.is_set():
                    break
                if self._stream_start_ms is None:
                    self._stream_start_ms = event.exchange_time_ms
                if isinstance(event, TradeEvent):
                    self.store.save_trade(event)
                elif isinstance(event, BookEvent):
                    self.store.save_book(event)
                scheduling_time_ms = max(
                    event.exchange_time_ms,
                    event.received_time_ms,
                )
                await self._advance(scheduling_time_ms)
                self.store.heartbeat(self.manifest.run_id, self.owner_id)
                status = self.store.status(self.manifest.run_id)
                eligible = status["forecast_counts"].get(
                    ForecastStatus.RESOLVED_ELIGIBLE, 0
                )
                if eligible >= self.manifest.target_eligible:
                    terminal_status = "completed"
                    break
                terminal_slots = sum(
                    status["forecast_counts"].get(slot_status, 0)
                    for slot_status in (
                        ForecastStatus.SKIPPED,
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
            self.store.set_run_status(self.manifest.run_id, terminal_status, detail)
            self.store.release_lease(self.manifest.run_id, self.owner_id)
            if heartbeat_error is not None:
                raise heartbeat_error

    async def _advance(self, observed_time_ms: int) -> None:
        current_slot = self.scheduler.slot_at_or_before(observed_time_ms)
        if self._last_slot_start is None:
            next_slot = self.scheduler.next_after(current_slot.start_ms)
            self._last_slot_start = next_slot.start_ms
            self.store.schedule_slot(
                self.manifest.run_id, next_slot.start_ms, next_slot.end_ms
            )
            return

        while self._last_slot_start <= observed_time_ms:
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
                if observed_time_ms < active_start:
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
            if status in (ForecastStatus.CREATED, ForecastStatus.PENDING_LABEL):
                if observed_time_ms < active_end:
                    return
                self._resolve(active_start, active_end)
            if self._terminal_limit_reached():
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
                ForecastStatus.RESOLVED_ELIGIBLE,
                ForecastStatus.RESOLVED_INELIGIBLE,
                ForecastStatus.EXPIRED,
                ForecastStatus.FAILED,
            ):
                return
            next_slot = self.scheduler.next_after(active_start)
            self.store.schedule_slot(
                self.manifest.run_id, next_slot.start_ms, next_slot.end_ms
            )
            self._last_slot_start = next_slot.start_ms

    def _create_or_skip(self, slot_start_ms: int, slot_end_ms: int) -> None:
        feature_start = slot_start_ms - self.manifest.lookback_ms
        features = self.store.build_features(
            self.manifest.provider,
            self.manifest.symbol,
            feature_start,
            slot_start_ms,
        )
        if features is None:
            self.store.skip_slot(
                self.manifest.run_id, slot_start_ms, ["insufficient_feature_data"]
            )
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
        if not row or row["status"] != ForecastStatus.PENDING_LABEL:
            return
        health = self.provider.health()
        complete = (
            health.coverage_certifiable
            and health.sequence_gaps == 0
            and health.reconnects == 0
            and self._stream_start_ms is not None
            and self._stream_start_ms <= slot_start_ms
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
            ForecastStatus.CREATED,
            ForecastStatus.PENDING_LABEL,
        ):
            self._last_slot_start = latest_start
            return
        next_slot = self.scheduler.next_after(latest_start)
        self.store.schedule_slot(
            self.manifest.run_id, next_slot.start_ms, next_slot.end_ms
        )
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
                ForecastStatus.RESOLVED_ELIGIBLE,
                ForecastStatus.RESOLVED_INELIGIBLE,
                ForecastStatus.EXPIRED,
                ForecastStatus.FAILED,
            )
        )
        return terminal_slots >= limit

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
