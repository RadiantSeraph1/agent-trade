"""Validated configuration. Risk defaults are EXPERIMENTAL and conservative;
they are not a claim that any setting is safe or profitable."""

from __future__ import annotations

import hashlib
import json
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AIMode(str, Enum):
    OFF = "off"
    MOCK = "mock"
    VERTEX = "vertex"


class RiskConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    initial_balance: float = Field(10_000.0, gt=0)
    account_currency: str = "USD"
    max_risk_per_trade_pct: float = Field(0.5, gt=0, le=5)
    max_daily_loss_pct: float = Field(2.0, gt=0, le=20)
    max_drawdown_pct: float = Field(10.0, gt=0, le=50)
    max_concurrent_positions: int = Field(3, ge=1, le=20)
    max_exposure_per_pair_units: float = Field(100_000.0, gt=0)
    max_position_units: float = Field(50_000.0, gt=0)
    min_reward_to_risk: float = Field(1.5, gt=0)
    max_spread_pips: float = Field(2.0, ge=0)
    max_data_age_seconds: int = Field(120, gt=0)
    news_blackout_minutes: int = Field(30, ge=0)
    min_stop_pips: float = Field(3.0, gt=0)
    min_position_units: float = Field(1_000.0, gt=0)
    max_net_currency_exposure_usd: float = Field(100_000.0, gt=0)
    allowed_sessions_utc: tuple[tuple[int, int], ...] = ((7, 20),)  # (start_h, end_h)

    @model_validator(mode="after")
    def _limits_coherent(self) -> "RiskConfig":
        if self.max_position_units > self.max_exposure_per_pair_units:
            raise ValueError("max_position_units exceeds per-pair exposure limit")
        if self.max_risk_per_trade_pct > self.max_daily_loss_pct:
            raise ValueError("per-trade risk exceeds daily loss limit")
        return self

    def version(self) -> str:
        blob = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:12]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FXLAB_", env_file=".env", extra="ignore")

    db_url: str = "sqlite:///data/fxlab.db"
    ai_mode: AIMode = AIMode.OFF
    ai_daily_budget_usd: float = Field(1.0, ge=0)
    ai_monthly_budget_usd: float = Field(15.0, ge=0)
    ai_kill_switch: bool = False
    ai_model: str = ""  # must be verified against the provider before use
    risk: RiskConfig = RiskConfig()
    # Cloud / PWA. Empty allowlist means nobody can sign in (fail closed).
    allowed_emails: list[str] = []
    iap_audience: str = ""  # expected `aud` of the IAP-signed header

    @model_validator(mode="after")
    def _budgets(self) -> "Settings":
        if self.ai_daily_budget_usd > self.ai_monthly_budget_usd:
            raise ValueError("daily AI budget exceeds monthly budget")
        return self
