"""HistData.com M1 ASCII reader.

Format: `YYYYMMDD HHMMSS;open;high;low;close;volume`, BID prices.

TIMEZONE: the vendor FAQ says "EST without daylight saving", but the data does
NOT behave that way. Verified empirically on 2020-2025 EURUSD: the 08:30 New York
data-release volatility spike and the London-open spike both sit at the same
wall-clock time in summer and winter, i.e. timestamps are New York LOCAL time
(EST/EDT) with DST. We therefore localise to America/New_York and convert to UTC.
See tests and docs/DECISIONS.md #24. Minutes with no ticks are absent (not
filled). Resampling keeps only buckets with data, so closures stay gaps.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd

from fxlab.market_data.validation import ValidationReport, parse_timeframe, validate_bars
from fxlab.schemas import DataSource

NY = "America/New_York"


def read_m1_csv(f) -> pd.DataFrame:
    raw = pd.read_csv(f, sep=";", header=None, names=["t", "open", "high", "low", "close", "volume"],
                      dtype={"t": str})
    ts = pd.to_datetime(raw["t"], format="%Y%m%d %H%M%S", errors="coerce")
    raw = raw.drop(columns="t").set_index(pd.DatetimeIndex(ts))
    raw = raw[raw.index.notna()]
    # DST transitions happen on weekends while FX is closed; any ambiguous/nonexistent
    # local time is dropped (NaT) rather than guessed.
    local = raw.index.tz_localize(NY, ambiguous="NaT", nonexistent="NaT")
    raw = raw[local.notna()]
    raw.index = local[local.notna()].tz_convert("UTC")
    return raw


def read_zip(path: str | Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv") and "/" not in n and ".." not in n]
        if len(names) != 1:
            raise ValueError(f"{path}: expected exactly one csv, found {names}")
        with z.open(names[0]) as f:
            return read_m1_csv(io.TextIOWrapper(f, encoding="ascii"))


def resample(m1: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    step = parse_timeframe(timeframe)
    g = m1.resample(step, label="left", closed="left")
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum()})
    return out[g["open"].count() > 0]


def load_histdata(paths: list[str | Path], symbol: str, timeframe: str = "15m"
                  ) -> tuple[pd.DataFrame, ValidationReport]:
    m1 = pd.concat([read_zip(p) for p in sorted(map(str, paths))]).sort_index()
    m1 = m1[~m1.index.duplicated(keep="first")]
    bars, rep = validate_bars(resample(m1, timeframe), timeframe)
    bars.attrs.update(symbol=symbol.upper(), timeframe=timeframe, source=DataSource.REPLAY.value,
                      vendor="histdata.com", price_basis="bid", tz_note="vendor times are New York local with DST (verified), converted to UTC")
    return bars, rep
