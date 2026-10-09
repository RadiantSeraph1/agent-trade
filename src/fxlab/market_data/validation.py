"""Candle DataFrame contract and validation.

Bars: UTC DatetimeIndex = bar OPEN time; columns open, high, low, close,
volume, spread (price units, NaN if unknown). Prices are BID; ask = bid + spread.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

REQUIRED = ["open", "high", "low", "close"]
_TF = {"m": "min", "h": "h", "d": "D"}


def parse_timeframe(tf: str) -> pd.Timedelta:
    try:
        n, unit = int(tf[:-1]), _TF[tf[-1]]
    except (ValueError, KeyError, IndexError):
        raise ValueError(f"bad timeframe {tf!r}; use e.g. 15m, 1h, 1d") from None
    if n <= 0:
        raise ValueError("timeframe must be positive")
    return pd.Timedelta(n, unit=unit) if unit != "min" else pd.Timedelta(minutes=n)


@dataclass
class ValidationReport:
    n_input: int = 0
    n_output: int = 0
    duplicates_dropped: int = 0
    invalid_dropped: int = 0
    out_of_order: bool = False
    gaps: list[tuple[pd.Timestamp, pd.Timestamp]] = field(default_factory=list)  # unexpected only
    weekend_gaps: int = 0

    @property
    def ok(self) -> bool:
        return self.n_output > 0 and self.invalid_dropped == 0 and not self.gaps


def _is_weekend_gap(prev: pd.Timestamp, nxt: pd.Timestamp) -> bool:
    # FX closes ~Fri 21-22 UTC and reopens ~Sun 21-22 UTC; a gap containing Saturday is expected.
    day = prev.normalize() + pd.Timedelta(days=1)
    while day < nxt:
        if day.dayofweek == 5:
            return True
        day += pd.Timedelta(days=1)
    return False


def validate_bars(df: pd.DataFrame, timeframe: str) -> tuple[pd.DataFrame, ValidationReport]:
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    if not isinstance(df.index, pd.DatetimeIndex) or df.index.tz is None:
        raise ValueError("index must be a timezone-aware DatetimeIndex")
    rep = ValidationReport(n_input=len(df))
    out = df.copy()
    out.index = out.index.tz_convert("UTC")
    for c in ("volume", "spread"):
        if c not in out.columns:
            out[c] = 0.0 if c == "volume" else np.nan
    out = out[REQUIRED + ["volume", "spread"]].astype(float)

    rep.out_of_order = not out.index.is_monotonic_increasing
    out = out.sort_index(kind="stable")
    dup = out.index.duplicated(keep="first")
    rep.duplicates_dropped = int(dup.sum())
    out = out[~dup]

    p = out[REQUIRED]
    bad = (
        p.isna().any(axis=1) | (p <= 0).any(axis=1)
        | (out["high"] < p.max(axis=1)) | (out["low"] > p.min(axis=1))
        | (out["volume"] < 0) | (out["spread"] < 0)
    )
    rep.invalid_dropped = int(bad.sum())
    out = out[~bad]

    step = parse_timeframe(timeframe)
    if len(out) > 1:
        idx = out.index
        d = idx[1:] - idx[:-1]
        for i in np.flatnonzero(d > step):
            prev, nxt = idx[i], idx[i + 1]
            if _is_weekend_gap(prev, nxt) and (nxt - prev) <= pd.Timedelta(days=3):
                rep.weekend_gaps += 1
            else:
                rep.gaps.append((prev, nxt))
    rep.n_output = len(out)
    out.attrs.update(timeframe=timeframe)
    return out, rep


def is_stale(last_bar_open: pd.Timestamp, timeframe: str, now: pd.Timestamp, max_age_s: int) -> bool:
    """Age is measured from the bar's CLOSE, i.e. when its data became final."""
    age = (now - (last_bar_open + parse_timeframe(timeframe))).total_seconds()
    return age > max_age_s
