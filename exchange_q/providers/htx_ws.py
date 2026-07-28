from __future__ import annotations

import asyncio
import gzip
import json
import time
import uuid
from decimal import Decimal

import websockets

from exchange_q.domain import BookEvent, TradeEvent
from exchange_q.providers.base import ProviderHealth


class HtxWebSocketProvider:
    """HTX public stream adapter.

    The public trade stream is useful for diagnostics, but this adapter deliberately
    reports coverage_certifiable=False because the consumed messages do not provide
    a continuity token that proves no trade was missed across reconnects.
    """

    name = "htx-ws"
    endpoint = "wss://api.huobi.pro/ws"

    def __init__(self, reconnect_limit: int = 20):
        self._closed = False
        self._connected = False
        self._last_event_received_ms: int | None = None
        self._reconnects = 0
        self._sequence_gaps = 0
        self._detail = ""
        self._reconnect_limit = reconnect_limit
        self._socket = None

    async def events(self, symbol: str):
        symbol = symbol.lower()
        trade_channel = f"market.{symbol}.trade.detail"
        book_channel = f"market.{symbol}.depth.step0"
        while not self._closed:
            if self._reconnects > self._reconnect_limit:
                raise RuntimeError("HTX reconnect limit exceeded")
            session_id = uuid.uuid4().hex
            try:
                async with websockets.connect(
                    self.endpoint,
                    open_timeout=10,
                    close_timeout=5,
                    ping_interval=None,
                    max_size=4_000_000,
                ) as socket:
                    self._socket = socket
                    self._connected = True
                    await socket.send(json.dumps({"sub": trade_channel, "id": session_id + "-trades"}))
                    await socket.send(json.dumps({"sub": book_channel, "id": session_id + "-book"}))
                    async for raw_message in socket:
                        received_ms = int(time.time() * 1000)
                        message = self._decode(raw_message)
                        if "ping" in message:
                            await socket.send(json.dumps({"pong": message["ping"]}))
                            continue
                        channel = message.get("ch")
                        tick = message.get("tick")
                        if not channel or not isinstance(tick, dict):
                            continue
                        self._last_event_received_ms = received_ms
                        if channel == trade_channel:
                            for trade in tick.get("data", []):
                                event = self._parse_trade(
                                    trade, symbol, received_ms, session_id
                                )
                                if event is not None:
                                    yield event
                        elif channel == book_channel:
                            bids = tick.get("bids") or []
                            asks = tick.get("asks") or []
                            if bids and asks:
                                try:
                                    yield BookEvent(
                                        provider=self.name,
                                        symbol=symbol,
                                        exchange_time_ms=int(message.get("ts") or received_ms),
                                        received_time_ms=received_ms,
                                        best_bid=Decimal(str(bids[0][0])),
                                        best_ask=Decimal(str(asks[0][0])),
                                        bid_quantity=sum(
                                            (Decimal(str(level[1])) for level in bids),
                                            Decimal(0),
                                        ),
                                        ask_quantity=sum(
                                            (Decimal(str(level[1])) for level in asks),
                                            Decimal(0),
                                        ),
                                        session_id=session_id,
                                    )
                                except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
                                    self._sequence_gaps += 1
                                    self._detail = f"malformed book event: {exc}"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._detail = f"{type(exc).__name__}: {exc}"
                self._connected = False
                self._reconnects += 1
                if not self._closed:
                    await asyncio.sleep(min(30.0, 2.0 ** min(self._reconnects, 5)))
            finally:
                self._socket = None
        self._connected = False

    async def close(self) -> None:
        self._closed = True
        self._connected = False
        if self._socket is not None:
            await self._socket.close()

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            connected=self._connected,
            last_event_received_ms=self._last_event_received_ms,
            reconnects=self._reconnects,
            sequence_gaps=self._sequence_gaps,
            coverage_certifiable=False,
            detail=self._detail,
        )

    @staticmethod
    def _decode(raw_message):
        if isinstance(raw_message, bytes):
            raw_message = gzip.decompress(raw_message).decode()
        return json.loads(raw_message)

    def _parse_trade(self, trade, symbol, received_ms, session_id):
        trade_id = trade.get("tradeId") or trade.get("id")
        if trade_id is None:
            self._sequence_gaps += 1
            self._detail = "malformed trade event: missing trade id"
            return None
        try:
            return TradeEvent(
                provider=self.name,
                symbol=symbol,
                exchange_trade_id=str(trade_id),
                exchange_time_ms=int(trade["ts"]),
                received_time_ms=received_ms,
                aggressor_side=str(trade["direction"]).lower(),
                price=Decimal(str(trade["price"])),
                quantity=Decimal(str(trade["amount"])),
                session_id=session_id,
            )
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            self._sequence_gaps += 1
            self._detail = f"malformed trade event: {exc}"
            return None
