"""Event-driven, chronological backtest.

Loop per bar i (bar i is CLOSED when the strategy sees it):
  1. broker.on_bar(bar i): fills orders queued from bar i-1 at bar i's OPEN, then
     checks stops/targets inside bar i.
  2. update equity / peak / day-start.
  3. strategy sees bars[0..i] only -> proposal -> risk engine (veto) -> queue order
     to fill at bar i+1's open.
Indicators are causal (tested), so precomputing them over the full frame cannot
leak the future into bar i. Results are BACKTEST results, never live results.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pandas as pd

from fxlab.analytics.metrics import Metrics, compute_metrics
from fxlab.config import RiskConfig
from fxlab.execution.paper import ExecConfig, Order, PaperBroker
from fxlab.fx import pip_size
from fxlab.market_data.validation import parse_timeframe
from fxlab.risk.engine import OpenPosition, RiskContext, RiskEngine
from fxlab.schemas import DataSource, Decision, DecisionType, RiskAssessment

_NS = uuid.UUID("6b1f1c0e-7a52-4d5e-9c63-0d0c0a8d9e11")


@dataclass
class BacktestResult:
    kind: str                       # always "backtest"
    data_source: str
    symbol: str
    timeframe: str
    strategy_id: str
    config_version: str
    trades: pd.DataFrame
    equity: pd.Series
    decisions: list[Decision]
    skipped: list[tuple[pd.Timestamp, str]]
    metrics: Metrics
    rejection_counts: dict[str, int] = field(default_factory=dict)


def run_backtest(bars: pd.DataFrame, strategy, risk_cfg: RiskConfig, exec_cfg: ExecConfig | None = None,
                 start: str | pd.Timestamp | None = None, end: str | pd.Timestamp | None = None,
                 max_gap_bars: int = 3) -> BacktestResult:
    symbol = bars.attrs.get("symbol") or "EURUSD"
    timeframe = bars.attrs.get("timeframe") or "15m"
    source = bars.attrs.get("source", "unknown")
    exec_cfg = exec_cfg or ExecConfig(initial_balance=risk_cfg.initial_balance,
                                      account_currency=risk_cfg.account_currency)
    step = parse_timeframe(timeframe)
    pip = pip_size(symbol)
    feats = strategy.features(bars)
    broker = PaperBroker(exec_cfg)
    risk = RiskEngine(risk_cfg)
    version = risk_cfg.version()

    lo = bars.index.searchsorted(_utc(start)) if start is not None else 0
    hi = bars.index.searchsorted(_utc(end)) if end is not None else len(bars)
    equity_pts: dict[pd.Timestamp, float] = {}
    decisions: list[Decision] = []
    skipped: list[tuple[pd.Timestamp, str]] = []
    rejections: dict[str, int] = {}
    peak = day_start = broker.equity
    cur_day = None
    halted = False

    for i in range(lo, hi):
        ts = bars.index[i]
        o, h, l, c = (float(bars[k].iloc[i]) for k in ("open", "high", "low", "close"))
        sp_raw = bars["spread"].iloc[i]
        spread = float(sp_raw) if sp_raw == sp_raw else None
        eff_spread = spread if spread is not None else exec_cfg.default_spread_pips * pip

        if ts.date() != cur_day:
            cur_day, day_start = ts.date(), broker.equity   # equity at prior close
        broker.on_bar(ts, o, h, l, c, spread)
        peak = max(peak, broker.equity)
        equity_pts[ts] = broker.equity
        if (peak - broker.equity) / peak * 100 >= risk_cfg.max_drawdown_pct:
            halted = True   # stays halted: needs explicit human reset (documented)

        if i + 1 >= len(bars) or i + 1 >= hi:
            continue  # no next bar to fill on
        if i >= 1 and (ts - bars.index[i - 1]) > step * max_gap_bars and (ts - bars.index[i - 1]) < pd.Timedelta(days=2) \
                and not _weekend(bars.index[i - 1], ts):
            skipped.append((ts, "data_gap")); continue
        if i < strategy.warmup:
            continue

        prop = strategy.propose(symbol, timeframe, bars, feats, i)
        if prop is None:
            continue
        ctx = RiskContext(
            now=ts + step, data_age_seconds=0.0, spread=eff_spread, equity=broker.equity,
            day_start_equity=day_start, peak_equity=peak,
            open_positions=[OpenPosition(p.order.symbol, p.order.direction, p.order.units, p.entry_price)
                            for p in broker.positions],
            kill_switch=broker.kill_switch, halted=halted)
        ra: RiskAssessment = risk.assess(prop, ctx)
        did = str(uuid.uuid5(_NS, f"{prop.dedupe_key}|{version}"))
        evidence = {"reasoning": prop.reasoning, "entry_reference": prop.entry_reference,
                    "stop_loss": prop.stop_loss, "take_profit": prop.take_profit}
        if not ra.approved:
            for ch in ra.checks_failed:
                rejections[ch] = rejections.get(ch, 0) + 1
            decisions.append(Decision(decision_id=did, decision=DecisionType.REJECT, data_ts=prop.signal_ts,
                                      symbol=symbol, timeframe=timeframe, strategy_id=prop.strategy_id,
                                      data_source=DataSource(source), reason=ra.reason,
                                      config_version=version, evidence=evidence, risk=ra))
            continue
        order = Order(symbol, prop.direction, ra.position_size_units, prop.stop_loss, prop.take_profit,
                      prop.strategy_id, prop.dedupe_key, prop.signal_ts,
                      meta={"decision_id": did, "risk_amount": ra.risk_amount})
        ok, why = broker.submit(order)
        decisions.append(Decision(
            decision_id=did, decision=DecisionType.APPROVE if ok else DecisionType.REJECT,
            data_ts=prop.signal_ts, symbol=symbol, timeframe=timeframe, strategy_id=prop.strategy_id,
            data_source=DataSource(source), reason=ra.reason if ok else f"order not accepted: {why}",
            config_version=version, evidence=evidence, risk=ra))

    if hi > lo:
        last = hi - 1
        broker.close_all(bars.index[last], float(bars["close"].iloc[last]),
                         float(bars["spread"].iloc[last]) if bars["spread"].iloc[last] == bars["spread"].iloc[last] else None)
        equity_pts[bars.index[last]] = broker.equity

    trades = pd.DataFrame([t.__dict__ for t in broker.trades])
    if trades.empty:
        trades = pd.DataFrame(columns=["id", "symbol", "direction", "units", "strategy_id", "entry_ts",
                                       "entry_price", "exit_ts", "exit_price", "exit_reason",
                                       "gross_pnl", "commission", "net_pnl", "meta"])
    equity = pd.Series(equity_pts, dtype=float).sort_index()
    return BacktestResult(
        kind="backtest", data_source=source, symbol=symbol, timeframe=timeframe,
        strategy_id=strategy.strategy_id, config_version=version, trades=trades, equity=equity,
        decisions=decisions, skipped=skipped,
        metrics=compute_metrics(trades, equity, exec_cfg.initial_balance), rejection_counts=rejections)


def _utc(x) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _weekend(prev: pd.Timestamp, nxt: pd.Timestamp) -> bool:
    from fxlab.market_data.validation import _is_weekend_gap
    return _is_weekend_gap(prev, nxt)
