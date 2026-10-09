"""Causal indicators: value at bar t uses only bars <= t. Wilder smoothing
seeded with a simple average (the textbook definition)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _first_valid(v: np.ndarray) -> int | None:
    ok = np.flatnonzero(~np.isnan(v))
    return int(ok[0]) if len(ok) else None


def _smooth(x: pd.Series, n: int, alpha: float) -> pd.Series:
    v = x.to_numpy(float)
    out = np.full(len(v), np.nan)
    start = _first_valid(v)
    if start is None or len(v) - start < n:
        return pd.Series(out, index=x.index)
    seed = start + n - 1
    out[seed] = v[start:start + n].mean()
    for i in range(seed + 1, len(v)):
        out[i] = alpha * v[i] + (1 - alpha) * out[i - 1]
    return pd.Series(out, index=x.index)


def ema(s: pd.Series, n: int) -> pd.Series:
    return _smooth(s, n, 2.0 / (n + 1))


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    gain, loss = d.clip(lower=0), (-d).clip(lower=0)
    ag, al = _smooth(gain, n, 1.0 / n), _smooth(loss, n, 1.0 / n)
    out = 100 - 100 / (1 + ag / al)
    out = out.where(al != 0, 100.0)
    return out.where(~((al == 0) & (ag == 0)), 50.0).where(ag.notna())


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    pc = close.shift(1)
    return pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1, skipna=False)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    return _smooth(true_range(high, low, close), n, 1.0 / n)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def rolling_vol(close: pd.Series, n: int = 20) -> pd.Series:
    return np.log(close).diff().rolling(n).std(ddof=1)


def trend_direction(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """+1 fast above slow, -1 below, 0 equal, NaN until both exist."""
    d = fast - slow
    return np.sign(d).where(d.notna())


def support_resistance(high: pd.Series, low: pd.Series, n: int = 50) -> pd.DataFrame:
    """Highest high / lowest low of the PREVIOUS n bars (excludes the current bar)."""
    return pd.DataFrame({"resistance": high.shift(1).rolling(n).max(),
                         "support": low.shift(1).rolling(n).min()})
