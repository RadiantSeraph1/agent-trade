"""Core validated data contracts shared across modules.

These are the only structures agents and engines exchange. No free-text
channel may carry an executable trading decision.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DataSource(str, Enum):
    LIVE = "live"
    REPLAY = "replay"
    SYNTHETIC = "synthetic"  # tests/demos only; must never be shown as live


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class DecisionType(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    NO_TRADE = "NO_TRADE"


class Regime(str, Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    UNKNOWN = "unknown"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _require_utc(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return v.astimezone(timezone.utc)


class Candle(_Frozen):
    """One OHLC bar, timestamped at bar OPEN, UTC. Optional bid/ask spread."""

    symbol: str
    timeframe: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    spread: float | None = None  # in price units, if known
    source: DataSource

    _utc = field_validator("ts")(_require_utc)

    @model_validator(mode="after")
    def _sane(self) -> "Candle":
        prices = (self.open, self.high, self.low, self.close)
        if any(p <= 0 or p != p for p in prices):  # non-positive or NaN
            raise ValueError("prices must be positive and finite")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high below open/close/low")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low above open/close/high")
        if self.volume < 0 or (self.spread is not None and self.spread < 0):
            raise ValueError("volume/spread must be non-negative")
        return self


class TradeProposal(_Frozen):
    """Candidate trade from the strategy. Not an order."""

    symbol: str
    direction: Direction
    timeframe: str
    signal_ts: datetime  # close time of the bar the signal was computed on
    entry_reference: float
    stop_loss: float | None
    take_profit: float | None
    strategy_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: list[str] = Field(default_factory=list)

    _utc = field_validator("signal_ts")(_require_utc)

    @property
    def dedupe_key(self) -> str:
        return f"{self.strategy_id}|{self.symbol}|{self.timeframe}|{self.direction.value}|{self.signal_ts.isoformat()}"


class RiskAssessment(_Frozen):
    approved: bool
    reason: str
    risk_amount: float | None = None
    risk_percentage: float | None = None
    position_size_units: float | None = None
    checks_passed: list[str] = Field(default_factory=list)
    checks_failed: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> "RiskAssessment":
        if self.approved and self.checks_failed:
            raise ValueError("cannot be approved with failed checks")
        return self


class Decision(_Frozen):
    decision_id: str
    decision: DecisionType
    data_ts: datetime
    symbol: str
    timeframe: str
    strategy_id: str | None
    data_source: DataSource
    reason: str
    config_version: str
    evidence: dict[str, object] = Field(default_factory=dict)
    risk: RiskAssessment | None = None
    ai_model: str | None = None
    prompt_version: str | None = None

    _utc = field_validator("data_ts")(_require_utc)

    @model_validator(mode="after")
    def _veto(self) -> "Decision":
        # Structural enforcement of the risk veto.
        if self.decision is DecisionType.APPROVE and (self.risk is None or not self.risk.approved):
            raise ValueError("APPROVE requires an approving risk assessment")
        return self
