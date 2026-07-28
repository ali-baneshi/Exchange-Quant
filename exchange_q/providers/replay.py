from __future__ import annotations

import asyncio
from collections.abc import Iterable

from exchange_q.providers.base import ProviderEvent, ProviderHealth


class ReplayProvider:
    name = "replay"

    def __init__(self, events: Iterable[ProviderEvent], delay_s: float = 0.0):
        self._events = list(events)
        self._delay_s = delay_s
        self._closed = False
        self._last_received_ms: int | None = None

    async def events(self, symbol: str):
        for event in self._events:
            if self._closed:
                return
            if event.symbol != symbol:
                continue
            if self._delay_s:
                await asyncio.sleep(self._delay_s)
            self._last_received_ms = event.received_time_ms
            yield event

    async def close(self) -> None:
        self._closed = True

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            connected=not self._closed,
            last_event_received_ms=self._last_received_ms,
            reconnects=0,
            sequence_gaps=0,
            coverage_certifiable=True,
        )
