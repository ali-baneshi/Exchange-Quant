from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, TypeAlias

from exchange_q.domain import BookEvent, TradeEvent

ProviderEvent: TypeAlias = TradeEvent | BookEvent


@dataclass(frozen=True)
class ProviderHealth:
    connected: bool
    last_event_received_ms: int | None
    reconnects: int
    sequence_gaps: int
    coverage_certifiable: bool
    detail: str = ""
    last_trade_sequence: int | None = None
    last_book_sequence: int | None = None
    unresolved_gaps: int = 0
    trade_sequence_gaps: int = 0
    book_sequence_gaps: int = 0
    pending_events: int = 0
    clock_offset_ms: float | None = None
    clock_uncertainty_ms: float | None = None
    trade_watermark_ms: int | None = None
    book_watermark_ms: int | None = None


class MarketDataProvider(Protocol):
    name: str

    async def events(self, symbol: str) -> AsyncIterator[ProviderEvent]: ...

    async def close(self) -> None: ...

    def health(self) -> ProviderHealth: ...
