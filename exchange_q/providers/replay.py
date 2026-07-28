from __future__ import annotations

import asyncio
from collections.abc import Iterable

from exchange_q.domain import TradeEvent
from exchange_q.providers.base import ProviderEvent, ProviderHealth


class ReplayProvider:
    name = "replay"

    def __init__(self, events: Iterable[ProviderEvent], delay_s: float = 0.0):
        self._events = list(events)
        self._delay_s = delay_s
        self._closed = False
        self._last_received_ms: int | None = None
        self._trade_watermark_ms: int | None = None
        self._book_watermark_ms: int | None = None

    async def events(self, symbol: str):
        for event in self._events:
            if self._closed:
                return
            if event.symbol != symbol:
                continue
            if self._delay_s:
                await asyncio.sleep(self._delay_s)
            self._last_received_ms = event.received_time_ms
            if isinstance(event, TradeEvent):
                self._trade_watermark_ms = event.exchange_time_ms
            else:
                self._book_watermark_ms = event.exchange_time_ms
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
            trade_watermark_ms=self._trade_watermark_ms,
            book_watermark_ms=self._book_watermark_ms,
        )
