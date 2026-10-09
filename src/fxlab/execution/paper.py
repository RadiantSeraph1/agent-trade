"""Simulated broker. There is deliberately NO method that sends a real order.

Conventions (documented limitations in docs/SPEC.md §5):
- Bars are BID prices; ask = bid + spread.
- Orders are market orders filled at the NEXT bar's open (+spread for buys,
  +slippage against us). Signals never fill on the bar that produced them.
- Longs exit on bid, shorts exit on ask.
- Stop-loss: gap-through fills at the (worse) open, plus slippage.
  Take-profit: fills at the target price (a favourable gap is NOT credited).
- If one bar touches both stop and target, the STOP is assumed first.
- Swap/rollover is NOT modelled yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from fxlab.fx import pip_size, quote_to_account
from fxlab.schemas import Direction


class ExecConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    default_spread_pips: float = Field(1.0, ge=0)   # used when bars carry no spread. ASSUMPTION.
    slippage_pips: float = Field(0.2, ge=0)         # against us on entries and stop fills. ASSUMPTION.
    commission_per_100k_units: float = Field(0.0, ge=0)  # per side, account currency
    account_currency: str = "USD"
    initial_balance: float = Field(10_000.0, gt=0)


@dataclass
class Order:
    symbol: str
    direction: Direction
    units: float
    stop_loss: float
    take_profit: float
    strategy_id: str
    dedupe_key: str
    signal_ts: pd.Timestamp
    meta: dict = field(default_factory=dict)


@dataclass
class Position:
    id: int
    order: Order
    entry_ts: pd.Timestamp
    entry_price: float
    entry_commission: float
    spread_at_entry: float

    @property
    def sign(self) -> float:
        return 1.0 if self.order.direction is Direction.BUY else -1.0


@dataclass
class Trade:
    id: int
    symbol: str
    direction: str
    units: float
    strategy_id: str
    entry_ts: pd.Timestamp
    entry_price: float
    exit_ts: pd.Timestamp
    exit_price: float
    exit_reason: str
    gross_pnl: float
    commission: float
    net_pnl: float
    meta: dict


class PaperBroker:
    def __init__(self, cfg: ExecConfig | None = None):
        self.cfg = cfg or ExecConfig()
        self.balance = self.cfg.initial_balance
        self.equity = self.balance
        self.pending: list[Order] = []
        self.positions: list[Position] = []
        self.trades: list[Trade] = []
        self.cancelled: list[tuple[Order, str]] = []
        self.kill_switch = False  # blocks NEW orders; open positions keep their stop/target
        self._seen: set[str] = set()
        self._next_id = 1

    # --- order entry -------------------------------------------------------
    def submit(self, order: Order) -> tuple[bool, str]:
        if self.kill_switch:
            return False, "kill_switch"
        if order.dedupe_key in self._seen:
            return False, "duplicate"
        if order.units <= 0:
            return False, "invalid_units"
        buy = order.direction is Direction.BUY
        if (buy and not order.stop_loss < order.take_profit) or (not buy and not order.take_profit < order.stop_loss):
            return False, "invalid_levels"
        self._seen.add(order.dedupe_key)
        self.pending.append(order)
        return True, "accepted"

    # --- simulation step -----------------------------------------------------
    def on_bar(self, ts: pd.Timestamp, o: float, h: float, l: float, c: float, spread: float | None) -> None:
        sp = spread if spread is not None and spread == spread else None
        self._step(ts, o, h, l, c, sp)

    def _step(self, ts, o, h, l, c, spread_in) -> None:
        for order in self.pending:
            pip = pip_size(order.symbol)
            spread = spread_in if spread_in is not None else self.cfg.default_spread_pips * pip
            slip = self.cfg.slippage_pips * pip
            buy = order.direction is Direction.BUY
            fill = o + spread + slip if buy else o - slip
            bad = (buy and not order.stop_loss < fill < order.take_profit) or \
                  (not buy and not order.take_profit < fill < order.stop_loss)
            if bad:
                self.cancelled.append((order, "levels_invalid_at_fill"))
                continue
            comm = order.units / 100_000 * self.cfg.commission_per_100k_units
            self.balance -= comm
            self.positions.append(Position(self._next_id, order, ts, fill, comm, spread))
            self._next_id += 1
        self.pending = []

        still_open: list[Position] = []
        for pos in self.positions:
            pip = pip_size(pos.order.symbol)
            spread = spread_in if spread_in is not None else self.cfg.default_spread_pips * pip
            slip = self.cfg.slippage_pips * pip
            sl, tp = pos.order.stop_loss, pos.order.take_profit
            exit_price = reason = None
            if pos.sign > 0:   # long exits on bid
                if l <= sl:
                    exit_price, reason = min(sl, o) - slip, "stop_loss"
                elif h >= tp:
                    exit_price, reason = tp, "take_profit"
            else:              # short exits on ask
                if h + spread >= sl:
                    exit_price, reason = max(sl, o + spread) + slip, "stop_loss"
                elif l + spread <= tp:
                    exit_price, reason = tp, "take_profit"
            if exit_price is None:
                still_open.append(pos)
            else:
                self._close(pos, ts, exit_price, reason)
        self.positions = still_open
        self.equity = self.balance + sum(self._unrealized(p, c, spread_in) for p in self.positions)

    def _unrealized(self, pos: Position, close_bid: float, spread_in) -> float:
        pip = pip_size(pos.order.symbol)
        spread = spread_in if spread_in is not None else self.cfg.default_spread_pips * pip
        mark = close_bid if pos.sign > 0 else close_bid + spread
        q = quote_to_account(pos.order.symbol, mark, self.cfg.account_currency)
        return pos.sign * (mark - pos.entry_price) * pos.order.units * q

    def _close(self, pos: Position, ts, price: float, reason: str) -> None:
        q = quote_to_account(pos.order.symbol, price, self.cfg.account_currency)
        gross = pos.sign * (price - pos.entry_price) * pos.order.units * q
        exit_comm = pos.order.units / 100_000 * self.cfg.commission_per_100k_units
        self.balance += gross - exit_comm
        comm = pos.entry_commission + exit_comm
        self.trades.append(Trade(
            id=pos.id, symbol=pos.order.symbol, direction=pos.order.direction.value, units=pos.order.units,
            strategy_id=pos.order.strategy_id, entry_ts=pos.entry_ts, entry_price=pos.entry_price,
            exit_ts=ts, exit_price=price, exit_reason=reason, gross_pnl=gross, commission=comm,
            net_pnl=gross - comm, meta=dict(pos.order.meta)))

    def close_all(self, ts, close_bid: float, spread: float | None, reason: str = "end_of_data") -> None:
        for pos in self.positions:
            pip = pip_size(pos.order.symbol)
            sp = spread if spread is not None else self.cfg.default_spread_pips * pip
            self._close(pos, ts, close_bid if pos.sign > 0 else close_bid + sp, reason)
        self.positions = []
        self.pending = []
        self.equity = self.balance
