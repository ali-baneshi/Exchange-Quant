from exchange_q.providers.htx_ws import HtxWebSocketProvider


def test_missing_trade_id_is_rejected_and_marks_continuity_failure():
    provider = HtxWebSocketProvider()
    event = provider._parse_trade(
        {
            "ts": 1000,
            "direction": "buy",
            "price": 100,
            "amount": 1,
        },
        "btcusdt",
        1001,
        "session",
    )
    assert event is None
    assert provider.health().sequence_gaps == 1
    assert not provider.health().coverage_certifiable


def test_valid_trade_is_normalized():
    provider = HtxWebSocketProvider()
    event = provider._parse_trade(
        {
            "tradeId": 42,
            "ts": 1000,
            "direction": "sell",
            "price": "100.5",
            "amount": "0.25",
        },
        "btcusdt",
        1001,
        "session",
    )
    assert event.exchange_trade_id == "42"
    assert event.aggressor_side == "sell"
