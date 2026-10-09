"""H2 (pre-registered in docs/EXPERIMENTS.md): fade 2-sigma stretches while the market is ranging."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from fxlab import indicators as ind
from fxlab.market_data.validation import parse_timeframe
from fxlab.schemas import Direction, TradeProposal


@dataclass(frozen=True)
class MeanRevParams:
    fast: int = 20
    slow: int = 50
    atr_n: int = 14
    z_n: int = 50
    z_entry: float = 2.0
    range_max_trend_atr: float = 1.0   # |EMA fast - EMA slow| / ATR below this = ranging
    atr_stop_mult: float = 1.0
    reward_to_risk: float = 1.5


class MeanReversionV1:
    strategy_id = "mean_reversion_v1"

    def __init__(self, params: MeanRevParams | None = None):
        self.p = params or MeanRevParams()

    @property
    def warmup(self) -> int:
        return max(self.p.slow, self.p.z_n, self.p.atr_n + 1) + 2

    def features(self, bars: pd.DataFrame) -> pd.DataFrame:
        p = self.p
        c = bars["close"]
        f = pd.DataFrame(index=bars.index)
        f["atr"] = ind.atr(bars["high"], bars["low"], c, p.atr_n)
        f["trend_strength"] = (ind.ema(c, p.fast) - ind.ema(c, p.slow)).abs() / f["atr"]
        f["z"] = (c - c.rolling(p.z_n).mean()) / c.rolling(p.z_n).std(ddof=1)
        return f

    def propose(self, symbol: str, timeframe: str, bars: pd.DataFrame, feats: pd.DataFrame,
                i: int) -> TradeProposal | None:
        if i < 1:
            return None
        cur, prev, p = feats.iloc[i], feats.iloc[i - 1], self.p
        if cur[["atr", "trend_strength", "z"]].isna().any() or pd.isna(prev["z"]):
            return None
        if not cur.trend_strength < p.range_max_trend_atr:
            return None
        down = prev.z >= -p.z_entry and cur.z < -p.z_entry
        up = prev.z <= p.z_entry and cur.z > p.z_entry
        if not (down or up):
            return None
        close = float(bars["close"].iloc[i])
        dist = p.atr_stop_mult * float(cur.atr)
        buy = down
        sl = close - dist if buy else close + dist
        tp = close + p.reward_to_risk * dist if buy else close - p.reward_to_risk * dist
        return TradeProposal(
            symbol=symbol, direction=Direction.BUY if buy else Direction.SELL, timeframe=timeframe,
            signal_ts=bars.index[i] + parse_timeframe(timeframe), entry_reference=close,
            stop_loss=sl, take_profit=tp, strategy_id=self.strategy_id, confidence=0.5,
            reasoning=[f"z {cur.z:.2f} crossed {'below -' if buy else 'above '}{p.z_entry}",
                       f"ranging: trend strength {cur.trend_strength:.2f} ATR", f"stop {p.atr_stop_mult} ATR"])
