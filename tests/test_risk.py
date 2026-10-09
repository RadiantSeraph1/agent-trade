import pandas as pd
import pytest

from fxlab.config import RiskConfig
from fxlab.fx import UnsupportedPair, pip_size, quote_to_account
from fxlab.risk.engine import OpenPosition, RiskContext, RiskEngine
from fxlab.schemas import Direction, TradeProposal

NOW = pd.Timestamp("2024-01-02 10:00", tz="UTC")


def prop(**kw):
    base = dict(symbol="EURUSD", direction=Direction.BUY, timeframe="15m", signal_ts=NOW,
                entry_reference=1.1000, stop_loss=1.0950, take_profit=1.1100,
                strategy_id="t", confidence=0.5)
    base.update(kw)
    return TradeProposal(**base)


def ctx(**kw):
    base = dict(now=NOW, data_age_seconds=10.0, spread=0.0001, equity=10_000.0,
                day_start_equity=10_000.0, peak_equity=10_000.0)
    base.update(kw)
    return RiskContext(**base)


def engine(**kw):
    return RiskEngine(RiskConfig(**kw))


def test_fx_helpers():
    assert pip_size("EURUSD") == 0.0001 and pip_size("USDJPY") == 0.01
    assert quote_to_account("EURUSD", 1.1) == 1.0
    assert quote_to_account("USDJPY", 150.0) == pytest.approx(1 / 150)
    with pytest.raises(UnsupportedPair):
        quote_to_account("EURGBP", 0.85)


def test_valid_trade_approved_with_exact_sizing():
    a = engine().assess(prop(), ctx())
    assert a.approved, a.reason
    # entry = ask 1.1001; risk dist 0.0051; budget 0.5% of 10k = 50 -> 9803 -> floor 9000
    assert a.position_size_units == 9000
    assert a.risk_amount == pytest.approx(9000 * 0.0051)
    assert a.risk_percentage == pytest.approx(9000 * 0.0051 / 10_000 * 100)
    assert a.risk_percentage <= 0.5
    assert "minimum_reward_to_risk" in a.checks_passed


def test_sell_uses_bid_entry():
    a = engine().assess(prop(direction=Direction.SELL, stop_loss=1.1050, take_profit=1.0900), ctx())
    assert a.approved, a.reason
    assert a.position_size_units == 10_000   # risk 0.0050 -> 10000 units


def test_rejects_poor_reward_to_risk():
    a = engine().assess(prop(take_profit=1.1030), ctx())
    assert not a.approved and "minimum_reward_to_risk" in a.checks_failed
    assert "reward:risk" in a.reason


def test_missing_stop_loss_and_take_profit():
    a = engine().assess(prop(stop_loss=None), ctx())
    assert not a.approved and "stop_loss_missing" in a.checks_failed
    a = engine().assess(prop(take_profit=None), ctx())
    assert not a.approved and "take_profit_missing" in a.checks_failed


def test_wrong_side_and_tiny_stops():
    a = engine().assess(prop(stop_loss=1.1050), ctx())
    assert "stop_side_valid" in a.checks_failed
    a = engine().assess(prop(stop_loss=1.0999, take_profit=1.1100), ctx())
    assert "min_stop_distance" in a.checks_failed


def test_stale_data_and_unknown_age():
    a = engine().assess(prop(), ctx(data_age_seconds=500))
    assert "data_fresh" in a.checks_failed
    a = engine().assess(prop(), ctx(data_age_seconds=None))
    assert "data_age_unavailable" in a.checks_failed and not a.approved


def test_spread_limit_and_unknown_spread():
    assert "spread_ok" in engine().assess(prop(), ctx(spread=0.0005)).checks_failed
    a = engine().assess(prop(), ctx(spread=None))
    assert not a.approved and "spread_unavailable" in a.checks_failed


def test_excessive_size_is_capped_not_exceeded():
    a = engine(max_position_units=5_000, max_exposure_per_pair_units=5_000).assess(prop(), ctx())
    assert a.approved and a.position_size_units == 5_000


def test_pair_exposure_limit():
    open_ = [OpenPosition("EURUSD", Direction.BUY, 98_000, 1.1)]
    a = engine().assess(prop(), ctx(open_positions=open_))
    assert "pair_exposure" in a.checks_failed


def test_net_currency_exposure_counts_correlated_usd_shorts():
    cfg = dict(max_net_currency_exposure_usd=70_000.0, max_position_units=50_000.0)
    open_ = [OpenPosition("GBPUSD", Direction.BUY, 50_000, 1.27)]  # GBP leg 63.5k alone is under 70k; with the new EUR leg, net short USD ~73.4k is over
    a = engine(**cfg).assess(prop(), ctx(open_positions=open_))
    assert "net_currency_exposure" in a.checks_failed


def test_daily_loss_limit_breached():
    a = engine().assess(prop(), ctx(equity=9_700.0, day_start_equity=10_000.0))
    assert not a.approved and "daily_loss_limit" in a.checks_failed


def test_drawdown_limit_and_halt():
    a = engine().assess(prop(), ctx(equity=8_900.0, day_start_equity=8_900.0, peak_equity=10_000.0))
    assert "max_drawdown" in a.checks_failed
    assert "not_halted" in engine().assess(prop(), ctx(halted=True)).checks_failed


def test_max_positions_session_news_and_kill_switch():
    pos = [OpenPosition("GBPUSD", Direction.BUY, 1000, 1.27)] * 3
    assert "max_positions" in engine().assess(prop(), ctx(open_positions=pos)).checks_failed
    late = ctx(now=pd.Timestamp("2024-01-02 23:00", tz="UTC"))
    assert "session_allowed" in engine().assess(prop(), late).checks_failed
    assert "no_news_blackout" in engine().assess(prop(), ctx(news_blackout=True)).checks_failed
    assert "kill_switch_off" in engine().assess(prop(), ctx(kill_switch=True)).checks_failed


def test_missing_equity_rejects():
    a = engine().assess(prop(), ctx(equity=None))
    assert not a.approved and "equity_unavailable" in a.checks_failed


def test_size_below_minimum_rejected():
    a = engine().assess(prop(stop_loss=1.0000, take_profit=1.2000), ctx(equity=500.0,
                        day_start_equity=500.0, peak_equity=500.0))
    assert not a.approved and "size_above_minimum" in a.checks_failed


def test_unsupported_cross_pair_rejected_not_guessed():
    a = engine().assess(prop(symbol="EURGBP", entry_reference=0.85, stop_loss=0.845, take_profit=0.86), ctx())
    assert not a.approved and "pair_supported" in a.checks_failed


def test_failed_checks_always_have_reason():
    a = engine().assess(prop(stop_loss=None), ctx(data_age_seconds=999))
    assert not a.approved and a.reason and a.position_size_units is None
