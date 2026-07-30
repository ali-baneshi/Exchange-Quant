import asyncio

import pytest

from exchange_q.providers.binance_ws import BinanceDepthBook, BinanceSequencedProvider


def test_depth_book_resync_after_gap():
    book = BinanceDepthBook()
    book.load_snapshot({"lastUpdateId": 100, "bids": [["99", "1"]], "asks": [["101", "1"]]})
    first = {
        "U": 101,
        "u": 102,
        "E": 1000,
        "b": [["99", "2"]],
        "a": [],
    }
    assert book.apply(first) is True
    with pytest.raises(ValueError, match="depth sequence gap"):
        book.apply({"U": 200, "u": 201, "E": 1001, "b": [], "a": []})


def test_trade_gap_is_unrecovered_and_flagged_fail_closed():
    from exchange_q.capture import CaptureHooks

    recorded_gaps = []
    rest_calls = []

    def _rest_get(path, params):
        rest_calls.append(path)
        return {"serverTime": 1}

    provider = BinanceSequencedProvider(
        rest_get=_rest_get,
        capture_hooks=CaptureHooks(
            record_continuity_gap=lambda *args, **kwargs: recorded_gaps.append((args, kwargs))
        ),
    )
    provider._last_trade_id = 5
    provider._trade_watermark_ms = 105
    events = asyncio.run(
        provider._trade_events(
            {"t": 8, "T": 108, "m": True, "p": "100", "q": "1"},
            "btcusdt",
            109,
            "sess",
        )
    )
    assert [event.sequence for event in events] == [8]
    assert provider._last_trade_id == 8
    assert provider._unresolved_gaps == 1
    assert provider.health().trade_sequence_gaps == 1
    assert rest_calls == []
    assert len(recorded_gaps) == 1
    args, kwargs = recorded_gaps[0]
    assert args == ("trades", 105, 108)
    assert kwargs["complete"] is False
    assert kwargs["first_sequence"] == 6
    assert kwargs["last_sequence"] == 7
    assert kwargs["reasons"] == ("unrecovered_trade_gap",)


def test_duplicate_trade_id_is_ignored():
    provider = BinanceSequencedProvider(rest_get=lambda *_args, **_kwargs: {"serverTime": 1})
    provider._last_trade_id = 5
    events = asyncio.run(
        provider._trade_events(
            {"t": 5, "T": 100, "m": False, "p": "100", "q": "1"},
            "btcusdt",
            101,
            "sess",
        )
    )
    assert events == []
