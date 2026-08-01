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
        rest_get=lambda path, params: (
            [
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
    )
    recovered = asyncio.run(provider._recover_trades("btcusdt", 3, 3, 100, "sess"))
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


def test_sparse_trade_sequence_jump_is_not_a_dense_gap():
    # KuCoin match sequences are snowflake IDs; large jumps are normal.
    provider = KucoinSequencedProvider(rest_get=lambda *_args, **_kwargs: [])
    provider._last_trade_sequence = 23753813018034176
    events = asyncio.run(
        provider._trade_events(
            {
                "sequence": "23753813049491456",
                "tradeId": "23753813049491456",
                "side": "buy",
                "price": "100",
                "size": "1",
                "time": 200,
            },
            "btcusdt",
            201,
            "sess",
        )
    )
    assert len(events) == 1
    assert events[0].sequence == 23753813049491456
    assert provider._unresolved_gaps == 0
    assert provider._trade_sequence_gaps == 0
    assert provider._last_trade_sequence == 23753813049491456


def test_trade_sequence_gap_requires_complete_recovery():
    # Dense +1 recovery is no longer used for KuCoin match sequences; a jump
    # from 5 to 8 is accepted as a normal sparse ID advance.
    provider = KucoinSequencedProvider(rest_get=lambda *_args, **_kwargs: [])
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
    assert [event.sequence for event in events] == [8]
    assert provider._unresolved_gaps == 0


def test_trade_sequence_gap_fails_closed_when_recovery_is_incomplete():
    # Retained name for compatibility with older audit notes: incomplete dense
    # recovery is obsolete; sparse jumps must not poison continuity.
    provider = KucoinSequencedProvider(rest_get=lambda *_args, **_kwargs: [])
    provider._last_trade_sequence = 5
    provider._trade_watermark_ms = 105
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
    assert [event.sequence for event in events] == [8]
    assert provider._last_trade_sequence == 8
    assert provider._unresolved_gaps == 0
    assert provider.health().trade_sequence_gaps == 0


def test_kucoin_timestamp_units():
    from exchange_q.providers.kucoin_ws import _kucoin_timestamp_ms

    assert _kucoin_timestamp_ms(1_780_000_000_000_123_456, 0) == 1_780_000_000_000
    assert _kucoin_timestamp_ms(1_780_000_000_000, 0) == 1_780_000_000_000
    assert _kucoin_timestamp_ms(108, 0) == 108
    assert _kucoin_timestamp_ms(None, 555) == 555


def test_normalize_symbol():
    assert KucoinSequencedProvider.normalize_symbol("btcusdt") == "BTC-USDT"


class _ClosingSocket:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise ConnectionClosed(None, None)


def test_pump_handles_connection_closed():
    provider = KucoinSequencedProvider()
    provider._trade_queue = asyncio.Queue()
    provider._wake = asyncio.Event()
    asyncio.run(provider._pump(_ClosingSocket()))
    assert provider._trade_queue.get_nowait() == {"type": "provider_stream_end"}
    assert provider._trade_queue.empty()


def test_books_coalesce_instead_of_blocking_trades():
    provider = KucoinSequencedProvider()
    provider._trade_queue = asyncio.Queue(maxsize=1)
    provider._wake = asyncio.Event()
    provider._symbol = "btcusdt"
    first = {"type": "book_ready", "event": object(), "received_ms": 1}
    second = {"type": "book_ready", "event": object(), "received_ms": 2}
    provider._offer_book(first)
    provider._offer_book(second)
    assert provider._queue_dropped_books == 1
    assert provider._book_slot is second
    provider._offer_trade_message(
        {
            "type": "message",
            "topic": "/market/match:BTC-USDT",
            "data": {"sequence": "1", "time": 100},
        }
    )
    assert provider._queue_dropped_trades == 0
    assert provider._trade_queue.qsize() == 1


def test_trade_queue_drop_records_pending_gap():
    provider = KucoinSequencedProvider()
    provider._trade_queue = asyncio.Queue(maxsize=1)
    provider._wake = asyncio.Event()
    provider._symbol = "btcusdt"
    provider._trade_watermark_ms = 50
    provider._offer_trade_message(
        {
            "type": "message",
            "topic": "/market/match:BTC-USDT",
            "data": {"sequence": "1", "time": 100},
        }
    )
    provider._offer_trade_message(
        {
            "type": "message",
            "topic": "/market/match:BTC-USDT",
            "data": {"sequence": "2", "time": 110},
        }
    )
    assert provider._queue_dropped_trades == 1
    assert provider._unresolved_gaps == 1
    assert len(provider._pending_trade_gaps) == 1
    gaps: list[tuple] = []

    def _record(stream_kind, start_ms, end_ms, *, complete, first_sequence, last_sequence, reasons):
        gaps.append((stream_kind, start_ms, end_ms, complete, reasons))

    from exchange_q.capture import CaptureHooks

    provider.set_capture_hooks(CaptureHooks(record_continuity_gap=_record))
    provider._flush_pending_trade_gaps()
    assert gaps == [("trades", 50, gaps[0][2], False, ("queue_drop_trade",))]
    assert provider._pending_trade_gaps == []


def test_depth_bootstrap_applies_buffered_updates_without_startup_gap():
    provider = KucoinSequencedProvider()
    provider._symbol = "btcusdt"
    provider._wake = asyncio.Event()
    provider._depth_ready = False
    provider._depth_bootstrap_buffer = [
        {
            "data": {
                "sequenceStart": 101,
                "sequenceEnd": 102,
                "time": 1000,
                "changes": {"bids": [["99", "2", "102"]], "asks": []},
            },
            "received_ms": 1000,
        }
    ]
    provider._depth.load_snapshot(
        {"sequence": 100, "bids": [["99", "1"]], "asks": [["101", "1"]]}
    )
    asyncio.run(provider._finish_depth_bootstrap("sess"))
    assert provider._depth_ready is True
    assert provider._sequence_gaps == 0
    assert provider._unresolved_gaps == 0
    assert provider._depth.last_sequence == 102
    assert provider._book_slot["type"] == "book_ready"


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
