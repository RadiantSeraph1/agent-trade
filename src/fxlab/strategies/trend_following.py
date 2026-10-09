"""Baseline: EMA-cross trend following with ATR stop and fixed reward:risk.

Parameters are FIXED textbook-style defaults, deliberately untuned. Any change
must be pre-registered in docs/EXPERIMENTS.md. The signal at bar i uses only
data up to and including bar i's close.

Level convention: BUY levels are bid-based (exit on bid); SELL levels are
ask-based (exit on ask). See execution/paper.py.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from fxlab import indicators as ind
from fxlab.market_data.validation import parse_timeframe
from fxlab.schemas import Direction, TradeProposal


@dataclass(frozen=True)
class TrendParams:
    fast: int = 20
    slow: int = 50
    atr_n: int = 14
    rsi_n: int = 14
    atr_stop_mult: float = 1.5
    reward_to_risk: float = 2.0
    rsi_long_max: float = 70.0
    rsi_short_min: float = 30.0


class TrendFollowingV1:
    strategy_id = "trend_following_v1"

    def __init__(self, params: TrendParams | None = None):
        self.p = params or TrendParams()

    @property
    def warmup(self) -> int:
        return max(self.p.slow, self.p.atr_n + 1, self.p.rsi_n + 1) + 2

    def features(self, bars: pd.DataFrame) -> pd.DataFrame:
        p = self.p
        f = pd.DataFrame(index=bars.index)
        f["ema_fast"] = ind.ema(bars["close"], p.fast)
        f["ema_slow"] = ind.ema(bars["close"], p.slow)
        f["rsi"] = ind.rsi(bars["close"], p.rsi_n)
        f["atr"] = ind.atr(bars["high"], bars["low"], bars["close"], p.atr_n)
        f["trend"] = ind.trend_direction(f["ema_fast"], f["ema_slow"])
        return f

    def propose(self, symbol: str, timeframe: str, bars: pd.DataFrame, feats: pd.DataFrame,
                i: int) -> TradeProposal | None:
        if i < 1:
            return None
        cur, prev = feats.iloc[i], feats.iloc[i - 1]
        if cur[["ema_fast", "ema_slow", "rsi", "atr"]].isna().any() or prev[["ema_fast", "ema_slow"]].isna().any():
            return None
        p = self.p
        crossed_up = prev.ema_fast <= prev.ema_slow and cur.ema_fast > cur.ema_slow
        crossed_dn = prev.ema_fast >= prev.ema_slow and cur.ema_fast < cur.ema_slow
        close = float(bars["close"].iloc[i])
        dist = p.atr_stop_mult * float(cur.atr)
        signal_ts = bars.index[i] + parse_timeframe(timeframe)
        if crossed_up and cur.rsi <= p.rsi_long_max:
            d, sl, tp = Direction.BUY, close - dist, close + p.reward_to_risk * dist
            why = [f"EMA{p.fast} crossed above EMA{p.slow}", f"RSI {cur.rsi:.1f} <= {p.rsi_long_max}"]
        elif crossed_dn and cur.rsi >= p.rsi_short_min:
            d, sl, tp = Direction.SELL, close + dist, close - p.reward_to_risk * dist
            why = [f"EMA{p.fast} crossed below EMA{p.slow}", f"RSI {cur.rsi:.1f} >= {p.rsi_short_min}"]
        else:
            return None
        return TradeProposal(symbol=symbol, direction=d, timeframe=timeframe, signal_ts=signal_ts,
                             entry_reference=close, stop_loss=sl, take_profit=tp,
                             strategy_id=self.strategy_id, confidence=0.5,
                             reasoning=why + [f"ATR {float(cur.atr):.5f} x {p.atr_stop_mult} stop"])
