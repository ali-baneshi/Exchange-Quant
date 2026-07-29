from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ForecastSlot:
    start_ms: int
    end_ms: int


class FixedSlotScheduler:
    def __init__(self, horizon_ms: int, cadence_ms: int, anchor_ms: int = 0):
        if horizon_ms <= 0 or cadence_ms <= 0:
            raise ValueError("horizon and cadence must be positive")
        if cadence_ms < horizon_ms:
            raise ValueError("forecast slots must not overlap")
        self.horizon_ms = horizon_ms
        self.cadence_ms = cadence_ms
        self.anchor_ms = anchor_ms

    def slot_at_or_before(self, timestamp_ms: int) -> ForecastSlot:
        if timestamp_ms < self.anchor_ms:
            raise ValueError("timestamp precedes scheduler anchor")
        index = (timestamp_ms - self.anchor_ms) // self.cadence_ms
        start_ms = self.anchor_ms + index * self.cadence_ms
        return ForecastSlot(start_ms=start_ms, end_ms=start_ms + self.horizon_ms)

    def next_after(self, start_ms: int) -> ForecastSlot:
        next_start = start_ms + self.cadence_ms
        return ForecastSlot(next_start, next_start + self.horizon_ms)
