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


def test_agg_trades_recovery_uses_rest():
    provider = BinanceSequencedProvider(
        rest_get=lambda path, params: (
            [
                {
                    "a": 2,
                    "T": 200,
                    "m": False,
                    "p": "100",
                    "q": "1",
                }
            ]
            if path == "/api/v3/aggTrades"
            else {"serverTime": 1}
        )
    )
    recovered = asyncio.run(provider._recover_trades("btcusdt", 2, 2, 100, "sess"))
    assert len(recovered) == 1
    assert recovered[0].exchange_trade_id == "2"


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
