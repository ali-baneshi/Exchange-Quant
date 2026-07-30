from __future__ import annotations

import asyncio
import json
import time
import urllib.parse
import urllib.request
import uuid
from decimal import Decimal
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from exchange_q.capture import CaptureHooks
from exchange_q.domain import BookEvent, TradeEvent
from exchange_q.providers.base import ProviderHealth


class BinanceSequencedProvider:
    name = "binance-sequenced"
    adapter_revision = "binance-spot-sequenced-v1"
    stream_endpoint = "wss://stream.binance.com:9443/stream"
    rest_endpoint = "https://api.binance.com"
    book_depth_levels = 1000

    def __init__(
        self,
        *,
        reconnect_limit: int = 20,
        max_clock_uncertainty_ms: float = 500.0,
        depth_resync_limit: int = 3,
        rest_get=None,
        capture_hooks: CaptureHooks | None = None,
    ):
        self._closed = False
        self._connected = False
        self._socket = None
        self._queue: asyncio.Queue | None = None
        self._last_event_received_ms: int | None = None
        self._reconnects = 0
        self._sequence_gaps = 0
        self._trade_sequence_gaps = 0
        self._book_sequence_gaps = 0
        self._unresolved_gaps = 0
        self._detail = ""
        self._reconnect_limit = reconnect_limit
        self._max_clock_uncertainty_ms = max_clock_uncertainty_ms
        self._depth_resync_limit = depth_resync_limit
        self._rest_get = rest_get or self._http_get_json
        self._custom_rest_get = rest_get is not None
        self._capture_hooks = capture_hooks or CaptureHooks()
        self._last_trade_id: int | None = None
        self._last_depth_id: int | None = None
        self._trade_watermark_ms: int | None = None
        self._book_watermark_ms: int | None = None
        self._clock_offset_ms: float | None = None
        self._clock_uncertainty_ms: float | None = None
        self._depth = BinanceDepthBook()
        self._symbol = ""

    def set_capture_hooks(self, hooks: CaptureHooks) -> None:
        self._capture_hooks = hooks

    async def _get(self, path: str, parameters: dict[str, Any]):
        if self._custom_rest_get:
            return self._rest_get(path, parameters)
        return await asyncio.to_thread(self._rest_get, path, parameters)

    async def events(self, symbol: str):
        symbol = symbol.lower()
        self._symbol = symbol
        streams = f"{symbol}@trade/{symbol}@depth@100ms"
        endpoint = f"{self.stream_endpoint}?streams={streams}"
        while not self._closed:
            if self._reconnects > self._reconnect_limit:
                raise RuntimeError("Binance reconnect limit exceeded")
            session_id = uuid.uuid4().hex
            try:
                async with websockets.connect(
                    endpoint,
                    open_timeout=10,
                    close_timeout=5,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=4_000_000,
                ) as socket:
                    self._socket = socket
                    self._connected = True
                    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
                    self._queue = queue
                    pump = asyncio.create_task(self._pump(socket, queue))
                    try:
                        await self._sample_clock()
                        await self._load_depth_snapshot(symbol)
                        while not self._closed:
                            message = await queue.get()
                            received_ms = int(time.time() * 1000)
                            self._last_event_received_ms = received_ms
                            payload = message.get("data", message)
                            event_type = payload.get("e")
                            if event_type == "trade":
                                for event in await self._trade_events(
                                    payload,
                                    symbol,
                                    received_ms,
                                    session_id,
                                ):
                                    yield event
                            elif event_type == "depthUpdate":
                                event = await self._depth_event(
                                    payload,
                                    symbol,
                                    received_ms,
                                    session_id,
                                )
                                if event is not None:
                                    yield event
                    finally:
                        pump.cancel()
                        try:
                            await pump
                        except (asyncio.CancelledError, ConnectionClosed):
                            pass
            except asyncio.CancelledError:
                raise
            except (
                ConnectionClosed,
                OSError,
                TimeoutError,
                asyncio.TimeoutError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                self._detail = f"{type(exc).__name__}: {exc}"
                self._connected = False
                self._reconnects += 1
                if not self._closed:
                    await asyncio.sleep(min(30.0, 2.0 ** min(self._reconnects, 5)))
            finally:
                self._socket = None
        self._queue = None
        self._connected = False

    async def close(self) -> None:
        self._closed = True
        self._connected = False
        if self._socket is not None:
            await self._socket.close()

    def health(self) -> ProviderHealth:
        depth_ready = self._depth.synchronized
        clock_ready = (
            self._clock_uncertainty_ms is not None
            and self._clock_uncertainty_ms <= self._max_clock_uncertainty_ms
        )
        return ProviderHealth(
            connected=self._connected,
            last_event_received_ms=self._last_event_received_ms,
            reconnects=self._reconnects,
            sequence_gaps=self._sequence_gaps,
            coverage_certifiable=(self._connected and depth_ready and clock_ready),
            detail=self._detail,
            last_trade_sequence=self._last_trade_id,
            last_book_sequence=self._last_depth_id,
            unresolved_gaps=self._unresolved_gaps,
            trade_sequence_gaps=self._trade_sequence_gaps,
            book_sequence_gaps=self._book_sequence_gaps,
            pending_events=self._queue.qsize() if self._queue is not None else 0,
            clock_offset_ms=self._clock_offset_ms,
            clock_uncertainty_ms=self._clock_uncertainty_ms,
            trade_watermark_ms=self._trade_watermark_ms,
            book_watermark_ms=self._book_watermark_ms,
        )

    async def _pump(self, socket, queue: asyncio.Queue) -> None:
        try:
            async for raw_message in socket:
                if isinstance(raw_message, bytes):
                    raw_message = raw_message.decode()
                await queue.put(json.loads(raw_message))
        except ConnectionClosed:
            return

    async def _load_depth_snapshot(self, symbol: str) -> None:
        snapshot = await self._get(
            "/api/v3/depth",
            {"symbol": symbol.upper(), "limit": self.book_depth_levels},
        )
        self._depth.load_snapshot(snapshot)

    async def _trade_events(
        self,
        payload: dict[str, Any],
        symbol: str,
        received_ms: int,
        session_id: str,
    ) -> list[TradeEvent]:
        # Raw-trade IDs cannot be recovered without the authenticated
        # historicalTrades endpoint, so a gap is always unrecovered: flag the
        # affected interval fail-closed and continue the stream after it.
        trade_id = int(payload["t"])
        if self._last_trade_id is not None and trade_id <= self._last_trade_id:
            return []
        event = self._parse_trade(payload, symbol, received_ms, session_id)
        if self._last_trade_id is not None and trade_id > self._last_trade_id + 1:
            self._sequence_gaps += 1
            self._trade_sequence_gaps += 1
            missing_from = self._last_trade_id + 1
            missing_to = trade_id - 1
            self._unresolved_gaps += 1
            self._detail = f"unrecovered Binance trade IDs {missing_from}-{missing_to}"
            self._record_gap(
                symbol,
                "trades",
                (
                    self._trade_watermark_ms
                    if self._trade_watermark_ms is not None
                    else event.exchange_time_ms
                ),
                event.exchange_time_ms,
                complete=False,
                first_sequence=missing_from,
                last_sequence=missing_to,
                reasons=("unrecovered_trade_gap",),
            )
            if self._capture_hooks.record_recovery:
                self._capture_hooks.record_recovery(
                    "trades",
                    missing_from,
                    missing_to,
                    "failed",
                    0,
                    "trade recovery unsupported: raw-trade IDs require the "
                    "authenticated historicalTrades endpoint",
                )
        self._last_trade_id = trade_id
        self._trade_watermark_ms = event.exchange_time_ms
        return [event]

    def _parse_trade(
        self,
        payload: dict[str, Any],
        symbol: str,
        received_ms: int,
        session_id: str,
    ) -> TradeEvent:
        trade_id = int(payload["t"])
        return TradeEvent(
            provider=self.name,
            symbol=symbol,
            exchange_trade_id=str(trade_id),
            exchange_time_ms=int(payload["T"]),
            received_time_ms=received_ms,
            aggressor_side="sell" if payload["m"] else "buy",
            price=Decimal(str(payload["p"])),
            quantity=Decimal(str(payload["q"])),
            sequence=trade_id,
            session_id=session_id,
        )

    async def _depth_event(
        self,
        payload: dict[str, Any],
        symbol: str,
        received_ms: int,
        session_id: str,
    ) -> BookEvent | None:
        try:
            applied = self._depth.apply(payload)
        except ValueError as exc:
            self._sequence_gaps += 1
            self._book_sequence_gaps += 1
            resynced = await self._resync_depth(symbol, str(exc))
            if not resynced:
                self._unresolved_gaps += 1
                self._detail = str(exc)
                event_time_ms = int(payload.get("E", received_ms))
                self._record_gap(
                    symbol,
                    "books",
                    (
                        self._book_watermark_ms
                        if self._book_watermark_ms is not None
                        else event_time_ms
                    ),
                    event_time_ms,
                    complete=False,
                    first_sequence=int(payload.get("U", 0)),
                    last_sequence=int(payload.get("u", 0)),
                    reasons=("depth_sequence_gap",),
                )
            return None
        if not applied:
            return None
        self._last_depth_id = int(payload["u"])
        self._book_watermark_ms = int(payload["E"])
        best = self._depth.best()
        if best is None:
            return None
        best_bid, bid_quantity, best_ask, ask_quantity = best
        return BookEvent(
            provider=self.name,
            symbol=symbol,
            exchange_time_ms=int(payload["E"]),
            received_time_ms=received_ms,
            best_bid=best_bid,
            best_ask=best_ask,
            bid_quantity=bid_quantity,
            ask_quantity=ask_quantity,
            sequence=self._last_depth_id,
            session_id=session_id,
        )

    async def _resync_depth(self, symbol: str, detail: str) -> bool:
        for attempt in range(self._depth_resync_limit):
            try:
                await self._load_depth_snapshot(symbol)
                if self._capture_hooks.record_recovery:
                    self._capture_hooks.record_recovery(
                        "books",
                        0,
                        0,
                        "success",
                        0,
                        f"depth_resync attempt {attempt + 1}: {detail}",
                    )
                return True
            except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
                await asyncio.sleep(0.5 * (attempt + 1))
        if self._capture_hooks.record_recovery:
            self._capture_hooks.record_recovery(
                "books",
                0,
                0,
                "failed",
                0,
                detail,
            )
        return False

    async def _sample_clock(self) -> None:
        sent = int(time.time() * 1000)
        payload = await self._get("/api/v3/time", {})
        received = int(time.time() * 1000)
        exchange = int(payload["serverTime"])
        midpoint = (sent + received) / 2
        self._clock_offset_ms = exchange - midpoint
        self._clock_uncertainty_ms = (received - sent) / 2
        if self._capture_hooks.record_clock_sample:
            self._capture_hooks.record_clock_sample(sent, received, exchange)

    def _record_gap(
        self,
        symbol: str,
        stream_kind: str,
        start_ms: int,
        end_ms: int,
        *,
        complete: bool,
        first_sequence: int | None = None,
        last_sequence: int | None = None,
        reasons: tuple[str, ...],
    ) -> None:
        if self._capture_hooks.record_continuity_gap:
            self._capture_hooks.record_continuity_gap(
                stream_kind,
                start_ms,
                end_ms,
                complete=complete,
                first_sequence=first_sequence,
                last_sequence=last_sequence,
                reasons=reasons,
            )

    def _http_get_json(self, path: str, parameters: dict[str, Any]):
        query = urllib.parse.urlencode(parameters)
        url = f"{self.rest_endpoint}{path}"
        if query:
            url += f"?{query}"
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.load(response)


class BinanceDepthBook:
    def __init__(self):
        self.bids: dict[Decimal, Decimal] = {}
        self.asks: dict[Decimal, Decimal] = {}
        self.last_update_id: int | None = None
        self.synchronized = False

    def load_snapshot(self, payload: dict[str, Any]) -> None:
        self.last_update_id = int(payload["lastUpdateId"])
        self.bids = {
            Decimal(str(price)): Decimal(str(quantity))
            for price, quantity in payload.get("bids", [])
            if Decimal(str(quantity)) > 0
        }
        self.asks = {
            Decimal(str(price)): Decimal(str(quantity))
            for price, quantity in payload.get("asks", [])
            if Decimal(str(quantity)) > 0
        }
        self.synchronized = False

    def apply(self, payload: dict[str, Any]) -> bool:
        if self.last_update_id is None:
            return False
        first_update = int(payload["U"])
        final_update = int(payload["u"])
        if final_update <= self.last_update_id:
            return False
        expected = self.last_update_id + 1
        if not (first_update <= expected <= final_update):
            self.synchronized = False
            raise ValueError(
                f"depth sequence gap: expected {expected}, received {first_update}-{final_update}"
            )
        self._apply_side(self.bids, payload.get("b", []))
        self._apply_side(self.asks, payload.get("a", []))
        self.last_update_id = final_update
        self.synchronized = True
        return True

    def best(self) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
        if not self.bids or not self.asks:
            return None
        best_bid = max(self.bids)
        best_ask = min(self.asks)
        return best_bid, self.bids[best_bid], best_ask, self.asks[best_ask]

    @staticmethod
    def _apply_side(
        side: dict[Decimal, Decimal],
        updates: list[list[str]],
    ) -> None:
        for raw_price, raw_quantity in updates:
            price = Decimal(str(raw_price))
            quantity = Decimal(str(raw_quantity))
            if quantity == 0:
                side.pop(price, None)
            else:
                side[price] = quantity
