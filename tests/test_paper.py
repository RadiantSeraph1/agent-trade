import pandas as pd
import pytest

from fxlab.execution.paper import ExecConfig, Order, PaperBroker
from fxlab.schemas import Direction

T = [pd.Timestamp("2024-01-02 10:00", tz="UTC") + pd.Timedelta(minutes=15 * i) for i in range(6)]
SP = 0.0001


def broker():
    return PaperBroker(ExecConfig(default_spread_pips=1.0, slippage_pips=0.2, initial_balance=10_000.0))


def buy(key="k1", sl=1.0950, tp=1.1100, units=10_000):
    return Order("EURUSD", Direction.BUY, units, sl, tp, "t", key, T[0])


def sell(key="s1", sl=1.1050, tp=1.0900, units=10_000):
    return Order("EURUSD", Direction.SELL, units, sl, tp, "t", key, T[0])


def fill_buy(b):
    assert b.submit(buy())[0]
    b.on_bar(T[1], 1.1000, 1.1010, 1.0990, 1.1005, SP)   # fills at open + spread + slippage
    return b


def test_buy_fills_next_bar_open_plus_costs_and_marks_to_market():
    b = fill_buy(broker())
    p = b.positions[0]
    assert p.entry_price == pytest.approx(1.1000 + 0.0001 + 0.00002)
    assert b.pending == [] and p.entry_ts == T[1]
    assert b.equity == pytest.approx(10_000 + (1.1005 - 1.10012) * 10_000)


def test_stop_loss_closes_position_with_slippage():
    b = fill_buy(broker())
    b.on_bar(T[2], 1.0990, 1.0995, 1.0940, 1.0945, SP)
    t = b.trades[0]
    assert t.exit_reason == "stop_loss" and t.exit_price == pytest.approx(1.0950 - 0.00002)
    assert t.net_pnl == pytest.approx((1.09498 - 1.10012) * 10_000)
    assert b.positions == [] and b.balance == pytest.approx(10_000 + t.net_pnl) and b.equity == b.balance


def test_take_profit_closes_at_target_not_better():
    b = fill_buy(broker())
    b.on_bar(T[2], 1.1050, 1.1130, 1.1040, 1.1120, SP)
    t = b.trades[0]
    assert t.exit_reason == "take_profit" and t.exit_price == pytest.approx(1.1100)
    assert t.net_pnl == pytest.approx((1.1100 - 1.10012) * 10_000)


def test_same_bar_stop_and_target_assumes_stop_first():
    b = fill_buy(broker())
    b.on_bar(T[2], 1.1000, 1.1150, 1.0900, 1.1000, SP)
    assert b.trades[0].exit_reason == "stop_loss"


def test_gap_through_stop_fills_at_worse_open():
    b = fill_buy(broker())
    b.on_bar(T[2], 1.0900, 1.0910, 1.0890, 1.0905, SP)
    assert b.trades[0].exit_price == pytest.approx(1.0900 - 0.00002)


def test_short_enters_at_bid_exits_on_ask():
    b = broker()
    b.submit(sell())
    b.on_bar(T[1], 1.1000, 1.1010, 1.0990, 1.1000, SP)
    assert b.positions[0].entry_price == pytest.approx(1.1000 - 0.00002)
    b.on_bar(T[2], 1.1020, 1.1055, 1.1010, 1.1030, SP)      # ask high 1.1056 >= stop 1.1050
    t = b.trades[0]
    assert t.exit_reason == "stop_loss" and t.exit_price == pytest.approx(1.1050 + 0.00002)
    assert t.net_pnl == pytest.approx((1.09998 - 1.10502) * 10_000)


def test_short_take_profit_uses_ask_low():
    b = broker()
    b.submit(sell())
    b.on_bar(T[1], 1.1000, 1.1010, 1.0990, 1.1000, SP)
    b.on_bar(T[2], 1.0950, 1.0960, 1.0895, 1.0900, SP)      # ask low 1.0896 <= tp 1.0900
    assert b.trades[0].exit_reason == "take_profit" and b.trades[0].exit_price == pytest.approx(1.0900)


def test_duplicate_order_prevented_even_after_fill():
    b = broker()
    assert b.submit(buy("dup"))[0]
    assert b.submit(buy("dup")) == (False, "duplicate")
    b.on_bar(T[1], 1.1000, 1.1010, 1.0990, 1.1005, SP)
    assert b.submit(buy("dup")) == (False, "duplicate")
    assert len(b.positions) == 1


def test_invalid_orders_rejected():
    b = broker()
    assert b.submit(buy(units=0)) == (False, "invalid_units")
    assert b.submit(buy(sl=1.12, tp=1.11)) == (False, "invalid_levels")
    assert b.submit(sell(sl=1.08, tp=1.09)) == (False, "invalid_levels")


def test_order_cancelled_if_levels_invalid_at_fill():
    b = broker()
    b.submit(buy(sl=1.0999, tp=1.1100))
    b.on_bar(T[1], 1.1000, 1.1010, 1.0990, 1.1005, SP)      # fill 1.10012 is above the stop? no: stop below fill ok
    # make the stop sit above the eventual fill instead
    b2 = broker()
    b2.submit(buy("x", sl=1.1005, tp=1.1100))
    b2.on_bar(T[1], 1.1000, 1.1010, 1.0990, 1.1005, SP)
    assert b2.positions == [] and b2.cancelled[0][1] == "levels_invalid_at_fill"


def test_kill_switch_blocks_new_but_open_positions_keep_stops():
    b = fill_buy(broker())
    b.kill_switch = True
    assert b.submit(buy("k2")) == (False, "kill_switch")
    b.on_bar(T[2], 1.0990, 1.0995, 1.0940, 1.0945, SP)
    assert b.trades[0].exit_reason == "stop_loss"


def test_commission_and_end_of_data_close():
    b = PaperBroker(ExecConfig(commission_per_100k_units=5.0, slippage_pips=0.0, default_spread_pips=0.0))
    b.submit(buy())
    b.on_bar(T[1], 1.1000, 1.1010, 1.0990, 1.1000, 0.0)
    b.close_all(T[2], 1.1010, 0.0)
    t = b.trades[0]
    assert t.exit_reason == "end_of_data" and t.commission == pytest.approx(1.0)
    assert t.net_pnl == pytest.approx(0.0010 * 10_000 - 1.0)
    assert b.balance == pytest.approx(10_000 + t.net_pnl)


def test_usd_base_pair_pnl_converts_to_account_currency():
    b = PaperBroker(ExecConfig(slippage_pips=0.0, default_spread_pips=0.0))
    o = Order("USDJPY", Direction.BUY, 10_000, 149.0, 152.0, "t", "j", T[0])
    b.submit(o)
    b.on_bar(T[1], 150.0, 150.5, 149.5, 150.0, 0.0)
    b.on_bar(T[2], 151.0, 152.5, 150.9, 152.0, 0.0)          # TP 152.0 -> +2 JPY/unit
    assert b.trades[0].net_pnl == pytest.approx(2.0 * 10_000 / 152.0)


def test_no_real_order_capability_on_broker():
    names = {n.lower() for n in dir(PaperBroker)}
    banned = ("live", "real_", "_real", "send", "broker_api", "mt5", "execute")
    assert not {n for n in names if any(w in n for w in banned)}
