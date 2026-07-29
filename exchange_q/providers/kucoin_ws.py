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


class KucoinSequencedProvider:
    name = "kucoin-sequenced"
    adapter_revision = "kucoin-spot-sequenced-v1"
    rest_endpoint = "https://api.kucoin.com"

    def __init__(
        self,
        *,
        reconnect_limit: int = 20,
        reconnect_backoff_cap_s: float = 30.0,
        max_clock_uncertainty_ms: float = 500.0,
        depth_resync_limit: int = 3,
        rest_get=None,
        rest_post=None,
        capture_hooks: CaptureHooks | None = None,
    ):
        self._closed = False
        self._connected = False
        self._socket = None
        self._last_event_received_ms: int | None = None
        self._reconnects = 0
        self._sequence_gaps = 0
        self._unresolved_gaps = 0
        self._detail = ""
        self._reconnect_limit = reconnect_limit
        self._reconnect_backoff_cap_s = reconnect_backoff_cap_s
        self._max_clock_uncertainty_ms = max_clock_uncertainty_ms
        self._depth_resync_limit = depth_resync_limit
        self._rest_get = rest_get or self._http_get_json
        self._rest_post = rest_post or self._http_post_json
        self._custom_rest_get = rest_get is not None
        self._custom_rest_post = rest_post is not None
        self._capture_hooks = capture_hooks or CaptureHooks()
        self._last_trade_sequence: int | None = None
        self._last_depth_sequence: int | None = None
        self._trade_watermark_ms: int | None = None
        self._book_watermark_ms: int | None = None
        self._clock_offset_ms: float | None = None
        self._clock_uncertainty_ms: float | None = None
        self._depth = KucoinDepthBook()
        self._symbol = ""

    def set_capture_hooks(self, hooks: CaptureHooks) -> None:
        self._capture_hooks = hooks

    async def _get(self, path: str, parameters: dict[str, Any]):
        if self._custom_rest_get:
            return self._rest_get(path, parameters)
        return await asyncio.to_thread(self._rest_get, path, parameters)

    async def _post(self, path: str, body: dict[str, Any] | None = None):
        if self._custom_rest_post:
            return self._rest_post(path, body or {})
        return await asyncio.to_thread(self._rest_post, path, body or {})

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        symbol = symbol.upper().replace("-", "")
        if symbol.endswith("USDT") and len(symbol) > 4:
            base = symbol[:-4]
            return f"{base}-USDT"
        return symbol

    async def events(self, symbol: str):
        symbol = symbol.lower()
        self._symbol = symbol
        market_symbol = self.normalize_symbol(symbol)
        while not self._closed:
            if self._reconnects > self._reconnect_limit:
                raise RuntimeError("KuCoin reconnect limit exceeded")
            session_id = uuid.uuid4().hex
            try:
                endpoint, ping_interval_s = await self._bullet_endpoint()
                async with websockets.connect(
                    endpoint,
                    open_timeout=10,
                    close_timeout=5,
                    ping_interval=None,
                    max_size=4_000_000,
                ) as socket:
                    self._socket = socket
                    self._connected = True
                    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
                    pump = asyncio.create_task(self._pump(socket, queue))
                    ping = asyncio.create_task(
                        self._ping_loop(socket, ping_interval_s)
                    )
                    try:
                        await self._wait_for_welcome(queue)
                        await self._subscribe(
                            socket,
                            (
                                f"/market/match:{market_symbol}",
                                f"/market/level2:{market_symbol}",
                            ),
                        )
                        await self._sample_clock()
                        await self._load_depth_snapshot(market_symbol)
                        while not self._closed:
                            message = await queue.get()
                            received_ms = int(time.time() * 1000)
                            if message.get("type") == "message":
                                self._last_event_received_ms = received_ms
                                topic = message.get("topic", "")
                                data = message.get("data") or {}
                                if topic.startswith("/market/match:"):
                                    for event in await self._trade_events(
                                        data,
                                        symbol,
                                        received_ms,
                                        session_id,
                                    ):
                                        yield event
                                elif topic.startswith("/market/level2:"):
                                    event = await self._depth_event(
                                        data,
                                        symbol,
                                        received_ms,
                                        session_id,
                                    )
                                    if event is not None:
                                        yield event
                    finally:
                        ping.cancel()
                        pump.cancel()
                        await self._drain_background_tasks(ping, pump)
            except asyncio.CancelledError:
                raise
            except (
                ConnectionClosed,
                OSError,
                TimeoutError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                self._detail = f"{type(exc).__name__}: {exc}"
                self._connected = False
                self._reconnects += 1
                if not self._closed:
                    await asyncio.sleep(
                        min(self._reconnect_backoff_cap_s, 2.0 ** min(self._reconnects, 5))
                    )
            finally:
                self._socket = None
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
            coverage_certifiable=(
                self._connected
                and self._unresolved_gaps == 0
                and depth_ready
                and clock_ready
            ),
            detail=self._detail,
            last_trade_sequence=self._last_trade_sequence,
            last_book_sequence=self._last_depth_sequence,
            unresolved_gaps=self._unresolved_gaps,
            clock_offset_ms=self._clock_offset_ms,
            clock_uncertainty_ms=self._clock_uncertainty_ms,
            trade_watermark_ms=self._trade_watermark_ms,
            book_watermark_ms=self._book_watermark_ms,
        )

    async def _bullet_endpoint(self) -> tuple[str, float]:
        payload = await self._post("/api/v1/bullet-public", {})
        token = payload["token"]
        server = payload["instanceServers"][0]
        endpoint = server["endpoint"].rstrip("/")
        ping_interval_s = float(server.get("pingInterval", 18_000)) / 1000.0
        connect_id = uuid.uuid4().hex
        return f"{endpoint}?token={token}&connectId={connect_id}", ping_interval_s

    async def _wait_for_welcome(self, queue: asyncio.Queue) -> None:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            message = await asyncio.wait_for(queue.get(), timeout=remaining)
            if message.get("type") == "welcome":
                return
        raise TimeoutError("KuCoin websocket welcome timeout")

    async def _drain_background_tasks(self, *tasks: asyncio.Task) -> None:
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except ConnectionClosed:
                pass

    async def _subscribe(self, socket, topics: tuple[str, ...]) -> None:
        for topic in topics:
            message = {
                "id": uuid.uuid4().hex,
                "type": "subscribe",
                "topic": topic,
                "privateChannel": False,
                "response": True,
            }
            await socket.send(json.dumps(message))

    async def _pump(self, socket, queue: asyncio.Queue) -> None:
        try:
            async for raw_message in socket:
                if isinstance(raw_message, bytes):
                    raw_message = raw_message.decode()
                message = json.loads(raw_message)
                if message.get("type") == "ping":
                    try:
                        await socket.send(
                            json.dumps({"id": message.get("id"), "type": "pong"})
                        )
                    except (ConnectionClosed, OSError):
                        return
                    continue
                await queue.put(message)
        except ConnectionClosed:
            return

    async def _ping_loop(self, socket, interval_s: float) -> None:
        while True:
            await asyncio.sleep(max(1.0, interval_s * 0.8))
            try:
                await socket.send(
                    json.dumps({"id": uuid.uuid4().hex, "type": "ping"})
                )
            except (ConnectionClosed, OSError):
                return

    async def _load_depth_snapshot(self, market_symbol: str) -> None:
        snapshot = await self._get(
            "/api/v1/market/orderbook/level2_100",
            {"symbol": market_symbol},
        )
        self._depth.load_snapshot(snapshot)

    async def _trade_events(
        self,
        payload: dict[str, Any],
        symbol: str,
        received_ms: int,
        session_id: str,
    ) -> list[TradeEvent]:
        sequence = int(payload["sequence"])
        events: list[TradeEvent] = []
        if self._last_trade_sequence is not None and sequence <= self._last_trade_sequence:
            return []
        if self._last_trade_sequence is not None and sequence > self._last_trade_sequence + 1:
            self._sequence_gaps += 1
            missing_from = self._last_trade_sequence + 1
            missing_to = sequence - 1
            recovered = await self._recover_trades(
                symbol, missing_from, missing_to, received_ms, session_id
            )
            recovered_sequences = [int(event.sequence or -1) for event in recovered]
            expected_sequences = list(range(missing_from, missing_to + 1))
            if recovered_sequences != expected_sequences:
                self._unresolved_gaps += 1
                self._detail = (
                    f"unrecovered KuCoin trade sequence "
                    f"{missing_from}-{missing_to}"
                )
                self._record_gap(
                    symbol,
                    "trades",
                    missing_from,
                    missing_to,
                    complete=False,
                    reasons=("unrecovered_trade_gap",),
                )
                if self._capture_hooks.record_recovery:
                    self._capture_hooks.record_recovery(
                        "trades",
                        missing_from,
                        missing_to,
                        "failed",
                        len(recovered),
                        self._detail,
                    )
                return []
            events.extend(recovered)
            if self._capture_hooks.record_recovery:
                self._capture_hooks.record_recovery(
                    "trades",
                    missing_from,
                    missing_to,
                    "success",
                    len(recovered),
                    "",
                )
        event = self._parse_trade(payload, symbol, received_ms, session_id)
        events.append(event)
        self._last_trade_sequence = sequence
        self._trade_watermark_ms = event.exchange_time_ms
        return events

    async def _recover_trades(
        self,
        symbol: str,
        missing_from: int,
        missing_to: int,
        received_ms: int,
        session_id: str,
    ) -> list[TradeEvent]:
        market_symbol = self.normalize_symbol(symbol)
        rows = await self._get(
            "/api/v1/market/histories",
            {"symbol": market_symbol},
        )
        recovered: list[TradeEvent] = []
        for row in rows or []:
            sequence = int(row["sequence"])
            if sequence < missing_from:
                continue
            if sequence > missing_to:
                break
            exchange_time_ms = int(row["time"])
            if exchange_time_ms > 1_000_000_000_000:
                exchange_time_ms //= 1_000_000
            recovered.append(
                TradeEvent(
                    provider=self.name,
                    symbol=symbol,
                    exchange_trade_id=str(row.get("tradeId", sequence)),
                    exchange_time_ms=exchange_time_ms,
                    received_time_ms=received_ms,
                    aggressor_side=str(row["side"]).lower(),
                    price=Decimal(str(row["price"])),
                    quantity=Decimal(str(row["size"])),
                    sequence=sequence,
                    session_id=session_id,
                )
            )
            if sequence >= missing_to:
                break
        recovered.sort(key=lambda event: int(event.sequence or 0))
        return recovered

    def _parse_trade(
        self,
        payload: dict[str, Any],
        symbol: str,
        received_ms: int,
        session_id: str,
    ) -> TradeEvent:
        sequence = int(payload["sequence"])
        exchange_time_ms = int(payload.get("time", received_ms))
        if exchange_time_ms > 1_000_000_000_000:
            exchange_time_ms //= 1_000_000
        return TradeEvent(
            provider=self.name,
            symbol=symbol,
            exchange_trade_id=str(payload.get("tradeId", sequence)),
            exchange_time_ms=exchange_time_ms,
            received_time_ms=received_ms,
            aggressor_side=str(payload["side"]).lower(),
            price=Decimal(str(payload["price"])),
            quantity=Decimal(str(payload["size"])),
            sequence=sequence,
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
            market_symbol = self.normalize_symbol(symbol)
            resynced = await self._resync_depth(market_symbol, str(exc))
            if not resynced:
                self._unresolved_gaps += 1
                self._detail = str(exc)
                self._record_gap(
                    symbol,
                    "books",
                    int(payload.get("sequenceStart", 0)),
                    int(payload.get("sequenceEnd", 0)),
                    complete=False,
                    reasons=("depth_sequence_gap",),
                )
            return None
        if not applied:
            return None
        self._last_depth_sequence = int(payload["sequenceEnd"])
        exchange_time_ms = int(payload.get("time", received_ms))
        self._book_watermark_ms = exchange_time_ms
        best = self._depth.best()
        if best is None:
            return None
        best_bid, bid_quantity, best_ask, ask_quantity = best
        return BookEvent(
            provider=self.name,
            symbol=symbol,
            exchange_time_ms=exchange_time_ms,
            received_time_ms=received_ms,
            best_bid=best_bid,
            best_ask=best_ask,
            bid_quantity=bid_quantity,
            ask_quantity=ask_quantity,
            sequence=self._last_depth_sequence,
            session_id=session_id,
        )

    async def _resync_depth(self, market_symbol: str, detail: str) -> bool:
        for attempt in range(self._depth_resync_limit):
            try:
                await self._load_depth_snapshot(market_symbol)
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
        exchange = int(await self._get("/api/v1/timestamp", {}))
        received = int(time.time() * 1000)
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
        reasons: tuple[str, ...],
    ) -> None:
        if self._capture_hooks.record_continuity_gap:
            self._capture_hooks.record_continuity_gap(
                stream_kind,
                start_ms,
                end_ms,
                complete=complete,
                first_sequence=start_ms,
                last_sequence=end_ms,
                reasons=reasons,
            )

    def _http_get_json(self, path: str, parameters: dict[str, Any]):
        query = urllib.parse.urlencode(parameters)
        url = f"{self.rest_endpoint}{path}"
        if query:
            url += f"?{query}"
        with urllib.request.urlopen(url, timeout=10) as response:
            payload = json.load(response)
        if payload.get("code") != "200000":
            raise ValueError(f"KuCoin API error: {payload}")
        return payload["data"]

    def _http_post_json(self, path: str, body: dict[str, Any] | None = None):
        request = urllib.request.Request(
            f"{self.rest_endpoint}{path}",
            data=json.dumps(body or {}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)
        if payload.get("code") != "200000":
            raise ValueError(f"KuCoin API error: {payload}")
        return payload["data"]


class KucoinDepthBook:
    def __init__(self):
        self.bids: dict[Decimal, Decimal] = {}
        self.asks: dict[Decimal, Decimal] = {}
        self.last_sequence: int | None = None
        self.synchronized = False

    def load_snapshot(self, payload: dict[str, Any]) -> None:
        self.last_sequence = int(payload["sequence"])
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
        if self.last_sequence is None:
            return False
        sequence_start = int(payload["sequenceStart"])
        sequence_end = int(payload["sequenceEnd"])
        if sequence_end <= self.last_sequence:
            return False
        expected = self.last_sequence + 1
        if not (sequence_start <= expected <= sequence_end):
            self.synchronized = False
            raise ValueError(
                f"depth sequence gap: expected {expected}, "
                f"received {sequence_start}-{sequence_end}"
            )
        changes = payload.get("changes") or {}
        self._apply_side(self.bids, changes.get("bids") or [])
        self._apply_side(self.asks, changes.get("asks") or [])
        self.last_sequence = sequence_end
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
        for raw_price, raw_quantity, *_rest in updates:
            price = Decimal(str(raw_price))
            quantity = Decimal(str(raw_quantity))
            if quantity == 0:
                side.pop(price, None)
            else:
                side[price] = quantity
