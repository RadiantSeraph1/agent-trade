from __future__ import annotations

import pandas as pd

from fxlab.market_data.validation import parse_timeframe


def resample_bars(bars: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Aggregate bid bars to a coarser timeframe. Buckets without data stay absent."""
    g = bars.resample(parse_timeframe(timeframe), label="left", closed="left")
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum(),
                        "spread": g["spread"].mean()})
    out = out[g["open"].count() > 0]
    out.attrs.update(bars.attrs)
    out.attrs["timeframe"] = timeframe
    return out
