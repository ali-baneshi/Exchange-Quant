import asyncio

import pytest
import websockets
from websockets.exceptions import ConnectionClosed

from exchange_q.providers.kucoin_ws import KucoinDepthBook, KucoinSequencedProvider


def test_depth_book_resync_after_gap():
    book = KucoinDepthBook()
    book.load_snapshot({"sequence": 100, "bids": [["99", "1"]], "asks": [["101", "1"]]})
    first = {
        "sequenceStart": 101,
        "sequenceEnd": 102,
        "time": 1000,
        "changes": {"bids": [["99", "2", "102"]], "asks": []},
    }
    assert book.apply(first) is True
    with pytest.raises(ValueError, match="depth sequence gap"):
        book.apply(
            {
                "sequenceStart": 200,
                "sequenceEnd": 201,
                "time": 1001,
                "changes": {"bids": [], "asks": []},
            }
        )


def test_trade_recovery_uses_rest():
    provider = KucoinSequencedProvider(
        rest_get=lambda path, params: [
            {
                "sequence": "3",
                "side": "buy",
                "price": "100",
                "size": "1",
                "time": 200,
            }
        ]
        if path == "/api/v1/market/histories"
        else 1
    )
    recovered = asyncio.run(
        provider._recover_trades("btcusdt", 3, 3, 100, "sess")
    )
    assert len(recovered) == 1
    assert recovered[0].sequence == 3


def test_duplicate_trade_sequence_is_ignored():
    provider = KucoinSequencedProvider(rest_get=lambda *_args, **_kwargs: 1)
    provider._last_trade_sequence = 5
    events = asyncio.run(
        provider._trade_events(
            {
                "sequence": "5",
                "tradeId": "5",
                "side": "buy",
                "price": "100",
                "size": "1",
                "time": 100,
            },
            "btcusdt",
            101,
            "sess",
        )
    )
    assert events == []


def test_monotonic_trade_sequence_is_accepted_without_gap_recovery():
    provider = KucoinSequencedProvider(rest_get=lambda *_args, **_kwargs: 1)
    provider._last_trade_sequence = 5
    events = asyncio.run(
        provider._trade_events(
            {
                "sequence": "6",
                "tradeId": "100",
                "side": "buy",
                "price": "100",
                "size": "1",
                "time": 100,
            },
            "btcusdt",
            101,
            "sess",
        )
    )
    assert len(events) == 1
    assert provider._unresolved_gaps == 0


def test_trade_sequence_gap_requires_complete_recovery():
    provider = KucoinSequencedProvider(
        rest_get=lambda path, params: (
            [
                {
                    "sequence": str(sequence),
                    "tradeId": str(sequence),
                    "side": "buy",
                    "price": "100",
                    "size": "1",
                    "time": 100 + sequence,
                }
                for sequence in (6, 7)
            ]
            if path == "/api/v1/market/histories"
            else 1
        )
    )
    provider._last_trade_sequence = 5
    events = asyncio.run(
        provider._trade_events(
            {
                "sequence": "8",
                "tradeId": "8",
                "side": "sell",
                "price": "100",
                "size": "1",
                "time": 108,
            },
            "btcusdt",
            109,
            "sess",
        )
    )
    assert [event.sequence for event in events] == [6, 7, 8]
    assert provider._unresolved_gaps == 0


def test_trade_sequence_gap_fails_closed_when_recovery_is_incomplete():
    provider = KucoinSequencedProvider(
        rest_get=lambda path, params: (
            [
                {
                    "sequence": "6",
                    "tradeId": "6",
                    "side": "buy",
                    "price": "100",
                    "size": "1",
                    "time": 106,
                }
            ]
            if path == "/api/v1/market/histories"
            else 1
        )
    )
    provider._last_trade_sequence = 5
    events = asyncio.run(
        provider._trade_events(
            {
                "sequence": "8",
                "tradeId": "8",
                "side": "sell",
                "price": "100",
                "size": "1",
                "time": 108,
            },
            "btcusdt",
            109,
            "sess",
        )
    )
    assert events == []
    assert provider._unresolved_gaps == 1


def test_normalize_symbol():
    assert KucoinSequencedProvider.normalize_symbol("btcusdt") == "BTC-USDT"


class _ClosingSocket:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise ConnectionClosed(None, None)


def test_pump_handles_connection_closed():
    provider = KucoinSequencedProvider()
    queue = asyncio.Queue()
    asyncio.run(provider._pump(_ClosingSocket(), queue))
    assert queue.empty()


def test_events_reconnects_after_connection_closed(monkeypatch):
    attempts = {"count": 0}

    class _FailingConnection:
        async def __aenter__(self):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise OSError("connection reset")
            provider._closed = True
            raise RuntimeError("stop after reconnect attempt")

        async def __aexit__(self, *_args):
            return None

    provider = KucoinSequencedProvider(
        reconnect_backoff_cap_s=0,
        rest_post=lambda *_args, **_kwargs: {
            "token": "token",
            "instanceServers": [{"endpoint": "wss://example.test", "pingInterval": 18000}],
        },
        rest_get=lambda *_args, **_kwargs: 1,
    )

    def _connect(*_args, **_kwargs):
        return _FailingConnection()

    monkeypatch.setattr(websockets, "connect", _connect)

    with pytest.raises(RuntimeError, match="stop after reconnect"):
        asyncio.run(_collect_one(provider))

    assert attempts["count"] == 2
    assert provider.health().reconnects == 1


async def _collect_one(provider):
    async for _event in provider.events("btcusdt"):
        return
