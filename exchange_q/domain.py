from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from enum import Enum
import math
from typing import Any, Literal


class ForecastStatus(str, Enum):
    SCHEDULED = "scheduled"
    CREATED = "created"
    SKIPPED = "skipped"
    PENDING_LABEL = "pending_label"
    RESOLVED_ELIGIBLE = "resolved_eligible"
    RESOLVED_INELIGIBLE = "resolved_ineligible"
    EXPIRED = "expired"
    FAILED = "failed"


TERMINAL_FORECAST_STATUSES = frozenset(
    {
        ForecastStatus.SKIPPED,
        ForecastStatus.RESOLVED_ELIGIBLE,
        ForecastStatus.RESOLVED_INELIGIBLE,
        ForecastStatus.EXPIRED,
        ForecastStatus.FAILED,
    }
)


@dataclass(frozen=True)
class TradeEvent:
    provider: str
    symbol: str
    exchange_trade_id: str
    exchange_time_ms: int
    received_time_ms: int
    aggressor_side: Literal["buy", "sell"]
    price: Decimal
    quantity: Decimal
    sequence: int | None = None
    session_id: str | None = None

    def __post_init__(self) -> None:
        if not self.provider or not self.symbol or not self.exchange_trade_id:
            raise ValueError("provider, symbol, and exchange_trade_id are required")
        if self.exchange_time_ms <= 0 or self.received_time_ms <= 0:
            raise ValueError("timestamps must be positive")
        if self.aggressor_side not in ("buy", "sell"):
            raise ValueError("aggressor_side must be buy or sell")
        if not self.price.is_finite() or self.price <= 0:
            raise ValueError("price must be finite and positive")
        if not self.quantity.is_finite() or self.quantity <= 0:
            raise ValueError("quantity must be finite and positive")

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["price"] = str(self.price)
        record["quantity"] = str(self.quantity)
        return record


@dataclass(frozen=True)
class BookEvent:
    provider: str
    symbol: str
    exchange_time_ms: int
    received_time_ms: int
    best_bid: Decimal
    best_ask: Decimal
    bid_quantity: Decimal
    ask_quantity: Decimal
    sequence: int | None = None
    session_id: str | None = None

    def __post_init__(self) -> None:
        values = (self.best_bid, self.best_ask, self.bid_quantity, self.ask_quantity)
        if any(not value.is_finite() for value in values):
            raise ValueError("book values must be finite")
        if self.best_bid <= 0 or self.best_ask <= 0:
            raise ValueError("book prices must be positive")
        if self.best_ask < self.best_bid:
            raise ValueError("crossed book")
        if self.bid_quantity < 0 or self.ask_quantity < 0:
            raise ValueError("book quantities must be non-negative")

    @property
    def signed_imbalance(self) -> float:
        total = self.bid_quantity + self.ask_quantity
        if total == 0:
            return 0.0
        return float((self.bid_quantity - self.ask_quantity) / total)

    @property
    def spread(self) -> float:
        midpoint = (self.best_bid + self.best_ask) / 2
        return float((self.best_ask - self.best_bid) / midpoint)

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        for key in ("best_bid", "best_ask", "bid_quantity", "ask_quantity"):
            record[key] = str(record[key])
        return record


@dataclass(frozen=True)
class CoverageInterval:
    start_ms: int
    end_ms: int
    complete: bool
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.start_ms >= self.end_ms:
            raise ValueError("coverage interval must be non-empty")
        if self.complete and self.reasons:
            raise ValueError("complete coverage cannot have failure reasons")


@dataclass(frozen=True)
class FeatureWindow:
    start_ms: int
    end_ms: int
    trade_count: int
    buy_count: int
    sell_count: int
    buy_ratio: float
    signed_imbalance: float
    spread: float
    volatility: float

    def __post_init__(self) -> None:
        if self.start_ms >= self.end_ms:
            raise ValueError("feature window must be non-empty")
        if self.trade_count != self.buy_count + self.sell_count:
            raise ValueError("trade counts do not add up")
        if self.trade_count <= 0:
            raise ValueError("feature windows require at least one trade")
        if not 0.0 <= self.buy_ratio <= 1.0:
            raise ValueError("buy_ratio must be in [0, 1]")
        if not math.isclose(
            self.buy_ratio,
            self.buy_count / self.trade_count,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("buy_ratio does not match trade counts")
        if not -1.0 <= self.signed_imbalance <= 1.0:
            raise ValueError("signed_imbalance must be in [-1, 1]")
        if (
            not math.isfinite(self.spread)
            or not math.isfinite(self.volatility)
            or self.spread < 0
            or self.volatility < 0
        ):
            raise ValueError("spread and volatility must be finite and non-negative")

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Forecast:
    model_id: str
    probability_buy: float
    raw_probability_buy: float
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for value in (self.probability_buy, self.raw_probability_buy):
            if not 0.0 <= value <= 1.0:
                raise ValueError("forecast probabilities must be in [0, 1]")


@dataclass(frozen=True)
class Label:
    start_ms: int
    end_ms: int
    buy_count: int
    sell_count: int
    buy_quantity: Decimal
    sell_quantity: Decimal
    coverage_complete: bool
    exclusion_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.start_ms >= self.end_ms:
            raise ValueError("label window must be non-empty")
        if self.buy_count < 0 or self.sell_count < 0:
            raise ValueError("label counts must be non-negative")
        if (
            not self.buy_quantity.is_finite()
            or not self.sell_quantity.is_finite()
            or self.buy_quantity < 0
            or self.sell_quantity < 0
        ):
            raise ValueError("label quantities must be finite and non-negative")
        if self.coverage_complete and self.exclusion_reasons:
            raise ValueError("complete labels cannot carry coverage exclusions")

    @property
    def trade_count(self) -> int:
        return self.buy_count + self.sell_count

    @property
    def buy_ratio(self) -> float | None:
        if self.trade_count == 0:
            return None
        return self.buy_count / self.trade_count

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["buy_quantity"] = str(self.buy_quantity)
        record["sell_quantity"] = str(self.sell_quantity)
        record["trade_count"] = self.trade_count
        record["buy_ratio"] = self.buy_ratio
        return record


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    symbol: str
    provider: str
    model_artifact_hash: str
    feature_policy: str
    label_policy: str
    primary_metric: str
    horizon_ms: int
    lookback_ms: int
    cadence_ms: int
    minimum_label_trades: int
    target_eligible: int
    terminal_slot_limit: int | None = None
    schema_version: int = 7
    implementation_revision: str = "v7r2"

    def __post_init__(self) -> None:
        if not self.run_id or not self.symbol or not self.provider:
            raise ValueError("run, symbol, and provider identities are required")
        if (
            not self.model_artifact_hash
            or not self.feature_policy
            or not self.label_policy
            or not self.primary_metric
        ):
            raise ValueError("manifest policy and artifact identities are required")
        if self.horizon_ms <= 0 or self.lookback_ms <= 0 or self.cadence_ms <= 0:
            raise ValueError("timing values must be positive")
        if self.cadence_ms < self.horizon_ms:
            raise ValueError("canonical forecasts must not overlap")
        if self.minimum_label_trades <= 0 or self.target_eligible <= 0:
            raise ValueError("sample requirements must be positive")
        if self.terminal_slot_limit is not None and self.terminal_slot_limit <= 0:
            raise ValueError("terminal_slot_limit must be positive when set")

    def to_record(self) -> dict[str, Any]:
        return asdict(self)
