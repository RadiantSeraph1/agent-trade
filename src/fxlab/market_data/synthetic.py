"""Synthetic bars for tests/demos ONLY. Always labelled source='synthetic'."""

from __future__ import annotations

import numpy as np
import pandas as pd

from fxlab.market_data.validation import parse_timeframe
from fxlab.schemas import DataSource


def make_synthetic(symbol: str = "EURUSD", timeframe: str = "15m", n: int = 3000, seed: int = 7,
                   start: str = "2024-01-01 00:00", base: float = 1.10, vol: float = 0.0004,
                   spread: float = 0.0001) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    step = parse_timeframe(timeframe)
    idx = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=n, freq=step)
    drift = np.sin(np.arange(n) / 400.0) * vol * 0.15  # slow regime changes
    ret = drift + rng.normal(0, vol, n)
    close = base * np.exp(np.cumsum(ret))
    open_ = np.concatenate([[base], close[:-1]])
    wiggle = np.abs(rng.normal(0, vol * 0.5, n)) * close
    high = np.maximum(open_, close) + wiggle
    low = np.minimum(open_, close) - wiggle
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                       "volume": 100.0, "spread": spread}, index=idx)
    df.attrs.update(symbol=symbol, timeframe=timeframe, source=DataSource.SYNTHETIC.value)
    return df
