import numpy as np
import pandas as pd
import pytest

from fxlab.analytics.metrics import compute_metrics, max_drawdown_pct
from fxlab.backtesting.engine import run_backtest
from fxlab.config import RiskConfig
from fxlab.execution.paper import ExecConfig
from fxlab.market_data.synthetic import make_synthetic
from fxlab.persistence.sqlite_repo import SqliteRepository
from fxlab.schemas import DecisionType, Direction, TradeProposal
from fxlab.strategies.trend_following import TrendFollowingV1


@pytest.fixture(scope="module")
def bars():
    return make_synthetic(n=6000, seed=7)


@pytest.fixture(scope="module")
def result(bars):
    return run_backtest(bars, TrendFollowingV1(), RiskConfig())


def test_backtest_is_labelled_not_live(result):
    assert result.kind == "backtest" and result.data_source == "synthetic"


def test_every_decision_is_audited_and_veto_holds(result):
    assert result.decisions
    for d in result.decisions:
        assert d.risk is not None and d.config_version == result.config_version
        if d.decision is DecisionType.APPROVE:
            assert d.risk.approved and not d.risk.checks_failed
        else:
            assert d.reason
    assert sum(result.rejection_counts.values()) >= 1


def test_trades_enter_only_after_signal_close_at_next_open(bars, result):
    by_id = {d.decision_id: d for d in result.decisions}
    assert len(result.trades) > 0
    for t in result.trades.itertuples():
        d = by_id[t.meta["decision_id"]]
        assert t.entry_ts >= d.data_ts                      # never on the signalling bar
        assert t.entry_ts == d.data_ts                      # exactly the next bar
        o = bars.loc[t.entry_ts, "open"]
        spread = bars.loc[t.entry_ts, "spread"]
        expected = o + spread + 0.00002 if t.direction == "BUY" else o - 0.00002
        assert t.entry_price == pytest.approx(expected)


def test_no_lookahead_future_changes_do_not_alter_past_decisions(bars):
    k = 3000
    future_changed = bars.copy()
    future_changed.iloc[k:, :4] = future_changed.iloc[k:, :4] * 1.5   # keeps OHLC ordering valid
    a = run_backtest(bars, TrendFollowingV1(), RiskConfig())
    b = run_backtest(future_changed, TrendFollowingV1(), RiskConfig())
    cut = bars.index[k]
    ka = [(d.decision_id, d.decision, d.reason, d.evidence) for d in a.decisions if d.data_ts <= cut]
    kb = [(d.decision_id, d.decision, d.reason, d.evidence) for d in b.decisions if d.data_ts <= cut]
    assert ka and ka == kb
    pd.testing.assert_series_equal(a.equity[:bars.index[k - 1]], b.equity[:bars.index[k - 1]])


def test_oos_window_uses_warmup_but_only_trades_inside(bars):
    r = run_backtest(bars, TrendFollowingV1(), RiskConfig(), start=bars.index[4000], end=bars.index[5500])
    assert r.equity.index.min() >= bars.index[4000] and r.equity.index.max() < bars.index[5500]
    assert all(t.entry_ts >= bars.index[4000] for t in r.trades.itertuples())


def test_backtest_is_deterministic(bars, result):
    again = run_backtest(bars, TrendFollowingV1(), RiskConfig())
    assert [d.decision_id for d in again.decisions] == [d.decision_id for d in result.decisions]
    assert again.metrics.final_equity == result.metrics.final_equity


def test_equity_accounting_reconciles(result):
    assert result.metrics.final_equity == pytest.approx(
        result.metrics.initial_equity + result.trades["net_pnl"].sum())


def test_drawdown_halt_stops_new_entries():
    df = make_synthetic(n=6000, seed=3)
    cfg = RiskConfig(max_drawdown_pct=0.5, max_daily_loss_pct=0.5, max_risk_per_trade_pct=0.5)
    r = run_backtest(df, TrendFollowingV1(), cfg)
    assert any("not_halted" in d.risk.checks_failed for d in r.decisions) or r.metrics.max_drawdown_pct < 0.5


def test_gap_in_data_skips_signals():
    df = make_synthetic(n=800, seed=5)
    holed = pd.concat([df.iloc[:400], df.iloc[420:]])        # 20-bar hole mid-week-ish
    holed.attrs.update(df.attrs)
    r = run_backtest(holed, TrendFollowingV1(), RiskConfig())
    assert any(why == "data_gap" for _, why in r.skipped)


def test_metrics_undefined_cases_not_invented():
    eq = pd.Series([10_000.0, 10_100.0], index=pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC"))
    t = pd.DataFrame({"net_pnl": [100.0, 50.0]})
    m = compute_metrics(t, eq, 10_000.0)
    assert m.profit_factor is None and m.avg_loss is None        # no losing trades
    assert not m.sufficient_sample and "INSUFFICIENT" in m.note
    assert m.sharpe_daily_annualised is None                     # too few days
    empty = compute_metrics(pd.DataFrame({"net_pnl": []}), eq.iloc[:0], 10_000.0)
    assert empty.n_trades == 0 and empty.win_rate is None and empty.expectancy is None


def test_metrics_values():
    eq = pd.Series([100.0, 120.0, 90.0, 110.0], index=pd.date_range("2024-01-01", periods=4, freq="D", tz="UTC"))
    assert max_drawdown_pct(eq) == pytest.approx(25.0)
    t = pd.DataFrame({"net_pnl": [30.0, -10.0, -20.0, 20.0]})
    m = compute_metrics(t, eq, 100.0)
    assert m.win_rate == 0.5 and m.profit_factor == pytest.approx(50 / 30)
    assert m.expectancy == pytest.approx(5.0) and m.net_return_pct == pytest.approx(10.0)
    lo, hi = m.expectancy_ci95
    assert lo <= 5.0 <= hi


def test_win_rate_alone_does_not_imply_profit():
    t = pd.DataFrame({"net_pnl": [10.0] * 9 + [-200.0]})
    eq = pd.Series([100.0, 90.0], index=pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC"))
    m = compute_metrics(t, eq, 100.0)
    assert m.win_rate == 0.9 and m.expectancy < 0 and m.profit_factor < 1


def test_persistence_idempotent_and_restart_safe(result, tmp_path):
    url = f"sqlite:///{tmp_path/'t.db'}"
    repo = SqliteRepository(url)
    d = result.decisions[0]
    repo.save_decision(d)
    repo.save_decision(d)                                    # reprocessing is a no-op
    SqliteRepository(url)                                    # "restart": reopen same file
    assert len(SqliteRepository(url).decisions()) == 1
    p = TradeProposal(symbol="EURUSD", direction=Direction.BUY, timeframe="15m",
                      signal_ts=pd.Timestamp("2024-01-02 10:15", tz="UTC"), entry_reference=1.1,
                      stop_loss=1.09, take_profit=1.12, strategy_id="t", confidence=0.5)
    assert repo.save_order_once(p, "d1") is True
    assert repo.save_order_once(p, "d1") is False
