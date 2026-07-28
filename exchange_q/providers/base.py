from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol, TypeAlias

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


class MarketDataProvider(Protocol):
    name: str

    async def events(self, symbol: str) -> AsyncIterator[ProviderEvent]: ...

    async def close(self) -> None: ...

    def health(self) -> ProviderHealth: ...
