"""Deterministic risk engine. Absolute veto; no LLM involvement.

Every required input that is missing produces a failed `<check>_unavailable`
check: unknown means reject.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from fxlab.config import RiskConfig
from fxlab.fx import UnsupportedPair, notional_account, pip_size, quote_to_account, split_symbol
from fxlab.schemas import Direction, RiskAssessment, TradeProposal


@dataclass(frozen=True)
class OpenPosition:
    symbol: str
    direction: Direction
    units: float
    price: float


@dataclass
class RiskContext:
    now: pd.Timestamp                    # timestamp of the data used for the decision
    data_age_seconds: float | None
    spread: float | None                 # price units
    equity: float | None
    day_start_equity: float | None
    peak_equity: float | None
    open_positions: list[OpenPosition] = field(default_factory=list)
    news_blackout: bool = False
    kill_switch: bool = False
    halted: bool = False                 # drawdown halt (needs explicit reset)


class RiskEngine:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg

    def assess(self, p: TradeProposal, ctx: RiskContext) -> RiskAssessment:
        c = self.cfg
        passed: list[str] = []
        failed: list[str] = []
        reasons: list[str] = []

        def check(name: str, ok: bool, why: str = "") -> bool:
            (passed if ok else failed).append(name)
            if not ok and why:
                reasons.append(why)
            return ok

        def unavailable(name: str) -> None:
            failed.append(f"{name}_unavailable")
            reasons.append(f"{name} unavailable")

        check("kill_switch_off", not ctx.kill_switch, "kill switch active")
        check("not_halted", not ctx.halted, "trading halted by drawdown limit")

        if ctx.data_age_seconds is None:
            unavailable("data_age")
        else:
            check("data_fresh", ctx.data_age_seconds <= c.max_data_age_seconds,
                  f"data age {ctx.data_age_seconds:.0f}s > {c.max_data_age_seconds}s")

        pip = pip_size(p.symbol)
        if ctx.spread is None:
            unavailable("spread")
            spread = None
        else:
            spread = ctx.spread
            check("spread_ok", spread / pip <= c.max_spread_pips,
                  f"spread {spread / pip:.2f} pips > {c.max_spread_pips}")

        hour = ctx.now.hour
        check("session_allowed", any(a <= hour < b for a, b in c.allowed_sessions_utc),
              f"hour {hour} UTC outside allowed sessions")
        check("no_news_blackout", not ctx.news_blackout, "news blackout window")

        # Account state
        if ctx.equity is None or ctx.day_start_equity is None or ctx.peak_equity is None or ctx.equity <= 0:
            unavailable("equity")
        else:
            daily_loss = (ctx.day_start_equity - ctx.equity) / ctx.day_start_equity * 100
            check("daily_loss_limit", daily_loss < c.max_daily_loss_pct,
                  f"daily loss {daily_loss:.2f}% >= {c.max_daily_loss_pct}%")
            dd = (ctx.peak_equity - ctx.equity) / ctx.peak_equity * 100
            check("max_drawdown", dd < c.max_drawdown_pct, f"drawdown {dd:.2f}% >= {c.max_drawdown_pct}%")

        check("max_positions", len(ctx.open_positions) < c.max_concurrent_positions,
              f"{len(ctx.open_positions)} open positions at limit")

        # Levels and reward:risk
        sl, tp = p.stop_loss, p.take_profit
        buy = p.direction is Direction.BUY
        entry = None
        risk_dist = None
        if sl is None:
            failed.append("stop_loss_missing"); reasons.append("no stop-loss")
        if tp is None:
            failed.append("take_profit_missing"); reasons.append("no take-profit")
        if sl is not None and spread is not None:
            entry = p.entry_reference + (spread if buy else 0.0)  # buy at ask, sell at bid
            risk_dist = (entry - sl) if buy else (sl - entry)
            if check("stop_side_valid", risk_dist > 0, "stop-loss on wrong side of entry"):
                check("min_stop_distance", risk_dist / pip >= c.min_stop_pips,
                      f"stop {risk_dist / pip:.1f} pips < {c.min_stop_pips}")
        if sl is not None and tp is not None and entry is not None and risk_dist and risk_dist > 0:
            reward = (tp - entry) if buy else (entry - tp)
            check("take_profit_side_valid", reward > 0, "take-profit on wrong side of entry")
            if reward > 0:
                rr = reward / risk_dist
                check("minimum_reward_to_risk", rr >= c.min_reward_to_risk,
                      f"reward:risk {rr:.2f} < {c.min_reward_to_risk}")

        # Sizing + exposure
        units = risk_amount = risk_pct = None
        if (risk_dist and risk_dist > 0 and entry is not None and ctx.equity and ctx.equity > 0
                and "equity_unavailable" not in failed):
            try:
                q2a = quote_to_account(p.symbol, entry, c.account_currency)
                budget = ctx.equity * c.max_risk_per_trade_pct / 100
                raw = budget / (risk_dist * q2a)
                step = c.min_position_units
                units = math.floor(min(raw, c.max_position_units) / step) * step
                if check("size_above_minimum", units >= c.min_position_units,
                         f"size {raw:.0f} below minimum {c.min_position_units:.0f}"):
                    risk_amount = units * risk_dist * q2a
                    risk_pct = risk_amount / ctx.equity * 100
                    check("risk_within_limit", risk_pct <= c.max_risk_per_trade_pct + 1e-9,
                          f"risk {risk_pct:.3f}% > {c.max_risk_per_trade_pct}%")
                    same = sum(q.units for q in ctx.open_positions if q.symbol == p.symbol)
                    check("pair_exposure", same + units <= c.max_exposure_per_pair_units,
                          f"pair exposure {same + units:.0f} > {c.max_exposure_per_pair_units:.0f}")
                    expo: dict[str, float] = {}
                    for q in [*ctx.open_positions, OpenPosition(p.symbol, p.direction, units, entry)]:
                        sign = 1.0 if q.direction is Direction.BUY else -1.0
                        base, quote = split_symbol(q.symbol)
                        usd = sign * notional_account(q.symbol, q.units, q.price, c.account_currency)
                        expo[base] = expo.get(base, 0.0) + usd
                        expo[quote] = expo.get(quote, 0.0) - usd
                    worst = max((abs(v) for v in expo.values()), default=0.0)
                    check("net_currency_exposure", worst <= c.max_net_currency_exposure_usd,
                          f"net currency exposure {worst:.0f} > {c.max_net_currency_exposure_usd:.0f}")
            except UnsupportedPair as e:
                failed.append("pair_supported"); reasons.append(str(e))
        elif "stop_loss_missing" not in failed and not failed:
            unavailable("position_size")

        approved = not failed
        return RiskAssessment(
            approved=approved,
            reason="all risk checks passed" if approved else "; ".join(dict.fromkeys(reasons)) or "risk checks failed",
            risk_amount=risk_amount, risk_percentage=risk_pct,
            position_size_units=units if approved else None,
            checks_passed=passed, checks_failed=failed,
        )
