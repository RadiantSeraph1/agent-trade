from __future__ import annotations

from pathlib import Path

import pandas as pd

from fxlab.market_data.validation import ValidationReport, validate_bars
from fxlab.schemas import DataSource

_TS_NAMES = ["ts", "timestamp", "time", "datetime", "date", "gmt time", "local time"]


def load_csv(path: str | Path, symbol: str, timeframe: str,
             source: DataSource = DataSource.REPLAY) -> tuple[pd.DataFrame, ValidationReport]:
    """Load OHLC(V) CSV. Timestamps are treated as UTC when naive.

    Accepts Dukascopy-style 'Gmt time' (DD.MM.YYYY HH:MM:SS.fff) and ISO times.
    Never substitutes data: bad rows are dropped and counted in the report.
    """
    raw = pd.read_csv(path)
    raw.columns = [c.strip().lower() for c in raw.columns]
    ts_col = next((c for c in _TS_NAMES if c in raw.columns), None)
    if ts_col is None:
        raise ValueError(f"no timestamp column found; columns={list(raw.columns)}")
    s = raw[ts_col].astype(str)
    if s.str.match(r"^\d{2}\.\d{2}\.\d{4}").all():
        ts = pd.to_datetime(s, format="%d.%m.%Y %H:%M:%S.%f", utc=True, errors="coerce")
    else:
        ts = pd.to_datetime(s, utc=True, errors="coerce")
    raw = raw.drop(columns=[ts_col]).set_index(pd.DatetimeIndex(ts))
    raw = raw[raw.index.notna()]
    df, rep = validate_bars(raw, timeframe)
    df.attrs.update(symbol=symbol.upper(), source=source.value)
    return df, rep
