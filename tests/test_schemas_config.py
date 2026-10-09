from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from fxlab.config import RiskConfig, Settings
from fxlab.schemas import (
    Candle, DataSource, Decision, DecisionType, Direction, RiskAssessment, TradeProposal,
)

T = datetime(2024, 1, 2, 9, 0, tzinfo=timezone.utc)


def candle(**kw):
    base = dict(symbol="EURUSD", timeframe="15m", ts=T, open=1.10, high=1.11,
                low=1.09, close=1.105, source=DataSource.SYNTHETIC)
    base.update(kw)
    return Candle(**base)


def test_valid_candle():
    assert candle().close == 1.105


@pytest.mark.parametrize("kw", [
    dict(high=1.0), dict(low=1.2), dict(open=-1.0), dict(close=float("nan")),
    dict(ts=datetime(2024, 1, 2, 9, 0)), dict(volume=-1),
])
def test_invalid_candle_rejected(kw):
    with pytest.raises(ValidationError):
        candle(**kw)


def proposal(**kw):
    base = dict(symbol="EURUSD", direction=Direction.BUY, timeframe="15m", signal_ts=T,
                entry_reference=1.1, stop_loss=1.09, take_profit=1.12,
                strategy_id="t", confidence=0.5)
    base.update(kw)
    return TradeProposal(**base)


def test_dedupe_key_stable():
    assert proposal().dedupe_key == proposal().dedupe_key
    assert proposal().dedupe_key != proposal(direction=Direction.SELL).dedupe_key


def decision(dec, risk):
    return Decision(decision_id="d1", decision=dec, data_ts=T, symbol="EURUSD",
                    timeframe="15m", strategy_id="t", data_source=DataSource.SYNTHETIC,
                    reason="r", config_version="v", risk=risk)


def test_approve_requires_risk_approval():
    rejected = RiskAssessment(approved=False, reason="x", checks_failed=["rr"])
    with pytest.raises(ValidationError):
        decision(DecisionType.APPROVE, rejected)
    with pytest.raises(ValidationError):
        decision(DecisionType.APPROVE, None)
    ok = RiskAssessment(approved=True, reason="ok", checks_passed=["rr"])
    assert decision(DecisionType.APPROVE, ok).decision is DecisionType.APPROVE
    assert decision(DecisionType.REJECT, rejected).decision is DecisionType.REJECT


def test_risk_assessment_cannot_approve_with_failures():
    with pytest.raises(ValidationError):
        RiskAssessment(approved=True, reason="x", checks_failed=["a"])


def test_risk_config_coherence_and_version():
    with pytest.raises(ValidationError):
        RiskConfig(max_position_units=200_000.0)
    assert RiskConfig().version() == RiskConfig().version()
    assert RiskConfig().version() != RiskConfig(max_risk_per_trade_pct=1.0).version()


def test_settings_default_no_ai_and_budget_check():
    s = Settings(_env_file=None)
    assert s.ai_mode.value == "off"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ai_daily_budget_usd=50, ai_monthly_budget_usd=10)
