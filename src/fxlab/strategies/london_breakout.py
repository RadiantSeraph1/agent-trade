"""H1 (pre-registered in docs/EXPERIMENTS.md): breakout of the Asian range at the London open.

All parameters fixed. Causal: the Asian range for a date uses only bars opening
00:00-06:45 UTC that date and is only visible to bars opening 07:00 or later.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from fxlab import indicators as ind
from fxlab.fx import pip_size
from fxlab.market_data.validation import parse_timeframe
from fxlab.schemas import Direction, TradeProposal


@dataclass(frozen=True)
class LondonParams:
    range_end_hour: int = 7          # range = bars opening before this hour (UTC), from 00:00
    window_end_hour: int = 11        # signals on bars opening in [range_end_hour, window_end_hour)
    min_range_pips: float = 15.0
    max_range_pips: float = 60.0
    tp_multiple: float = 1.5


class LondonBreakoutV1:
    strategy_id = "london_breakout_v1"

    def __init__(self, params: LondonParams | None = None, symbol: str = "EURUSD"):
        self.p = params or LondonParams()
        self.pip = pip_size(symbol)

    warmup = 100  # first days only; range needs a full prior session anyway

    def features(self, bars: pd.DataFrame) -> pd.DataFrame:
        p = self.p
        day = bars.index.normalize()
        in_range = bars.index.hour < p.range_end_hour
        hi = bars["high"].where(in_range)
        lo = bars["low"].where(in_range)
        f = pd.DataFrame(index=bars.index)
        f["ah"] = hi.groupby(day).transform("max")
        f["al"] = lo.groupby(day).transform("min")
        visible = bars.index.hour >= p.range_end_hour       # range complete only from 07:00
        f.loc[~visible, ["ah", "al"]] = np.nan
        f["atr"] = ind.atr(bars["high"], bars["low"], bars["close"], 14)
        up = bars["close"] > f["ah"]
        dn = bars["close"] < f["al"]
        broke = (up | dn) & (bars.index.hour < p.window_end_hour)
        prior = broke.astype(int).groupby(day).cumsum() - broke.astype(int)   # earlier breaks same day
        f["first_up"] = up & broke & (prior == 0)
        f["first_dn"] = dn & broke & (prior == 0)
        return f

    def propose(self, symbol: str, timeframe: str, bars: pd.DataFrame, feats: pd.DataFrame,
                i: int) -> TradeProposal | None:
        cur = feats.iloc[i]
        if not (cur.first_up or cur.first_dn) or np.isnan(cur.ah):
            return None
        p = self.p
        rng_pips = (cur.ah - cur.al) / self.pip
        if not (p.min_range_pips <= rng_pips <= p.max_range_pips):
            return None
        close = float(bars["close"].iloc[i])
        mid = (cur.ah + cur.al) / 2
        dist = abs(close - mid)
        buy = bool(cur.first_up)
        sl = mid
        tp = close + p.tp_multiple * dist if buy else close - p.tp_multiple * dist
        return TradeProposal(
            symbol=symbol, direction=Direction.BUY if buy else Direction.SELL, timeframe=timeframe,
            signal_ts=bars.index[i] + parse_timeframe(timeframe), entry_reference=close,
            stop_loss=float(sl), take_profit=float(tp), strategy_id=self.strategy_id, confidence=0.5,
            reasoning=[f"first close {'above' if buy else 'below'} Asian range ({rng_pips:.1f} pips)",
                       "stop at range midpoint", f"TP {p.tp_multiple}R"])
