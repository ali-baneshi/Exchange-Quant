from __future__ import annotations

from decimal import Decimal

from exchange_q.domain import BookEvent, TradeEvent
from exchange_q.providers.replay import ReplayProvider


def replay_certification_events() -> list[TradeEvent | BookEvent]:
    return [
        BookEvent(
            provider="replay",
            symbol="btcusdt",
            exchange_time_ms=100,
            received_time_ms=101,
            best_bid=Decimal(99),
            best_ask=Decimal(101),
            bid_quantity=Decimal(6),
            ask_quantity=Decimal(4),
            sequence=1,
            session_id="cert-replay",
        ),
        TradeEvent(
            provider="replay",
            symbol="btcusdt",
            exchange_trade_id="1",
            exchange_time_ms=200,
            received_time_ms=201,
            aggressor_side="buy",
            price=Decimal(100),
            quantity=Decimal(1),
            sequence=1,
            session_id="cert-replay",
        ),
        TradeEvent(
            provider="replay",
            symbol="btcusdt",
            exchange_trade_id="2",
            exchange_time_ms=300,
            received_time_ms=301,
            aggressor_side="sell",
            price=Decimal(100),
            quantity=Decimal(1),
            sequence=2,
            session_id="cert-replay",
        ),
    ]


async def run_replay_certification() -> dict:
    provider = ReplayProvider(replay_certification_events())
    counts = {"trades": 0, "books": 0}
    async for event in provider.events("btcusdt"):
        if isinstance(event, TradeEvent):
            counts["trades"] += 1
        else:
            counts["books"] += 1
    await provider.close()
    health = provider.health()
    return {
        "passed": counts["trades"] >= 2 and counts["books"] >= 1 and health.coverage_certifiable,
        "counts": counts,
        "health": health.__dict__,
    }


async def run_fault_certification() -> dict:
    events = replay_certification_events()
    duplicate = events[-1]
    provider = ReplayProvider([*events, duplicate])
    observed = 0
    duplicate_observed = 0
    last_trade_id = None
    async for event in provider.events("btcusdt"):
        observed += 1
        if isinstance(event, TradeEvent):
            if event.exchange_trade_id == last_trade_id:
                duplicate_observed += 1
            last_trade_id = event.exchange_trade_id
    await provider.close()
    return {
        "passed": observed == len(events) + 1 and duplicate_observed >= 1,
        "observed_events": observed,
        "expected_events": len(events) + 1,
        "duplicate_observed": duplicate_observed,
        "detail": "duplicate provider event observed for fault injection",
    }
