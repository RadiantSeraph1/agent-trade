import pandas as pd
import pytest

from fxlab.market_data.loader import load_csv
from fxlab.market_data.synthetic import make_synthetic
from fxlab.market_data.validation import is_stale, parse_timeframe, validate_bars
from fxlab.schemas import DataSource


def frame(times, **over):
    idx = pd.DatetimeIndex(pd.to_datetime(times, utc=True))
    df = pd.DataFrame({"open": 1.1, "high": 1.11, "low": 1.09, "close": 1.105}, index=idx)
    for k, v in over.items():
        df[k] = v
    return df


def test_parse_timeframe():
    assert parse_timeframe("15m") == pd.Timedelta(minutes=15)
    assert parse_timeframe("1h") == pd.Timedelta(hours=1)
    for bad in ("", "x", "0m", "15x"):
        with pytest.raises(ValueError):
            parse_timeframe(bad)


def test_duplicates_invalid_and_order():
    df = frame(["2024-01-02 10:15", "2024-01-02 10:00", "2024-01-02 10:00", "2024-01-02 10:30"])
    df.loc[df.index[3], "high"] = 1.0           # high below close -> invalid
    out, rep = validate_bars(df, "15m")
    assert rep.out_of_order and rep.duplicates_dropped == 1 and rep.invalid_dropped == 1
    assert out.index.is_monotonic_increasing and len(out) == 2
    assert not rep.ok


def test_nan_and_nonpositive_rejected():
    df = frame(["2024-01-02 10:00", "2024-01-02 10:15", "2024-01-02 10:30"])
    df.iloc[0, 0] = float("nan")
    df.iloc[1, 3] = -1.0
    out, rep = validate_bars(df, "15m")
    assert rep.invalid_dropped == 2 and len(out) == 1


def test_gap_detection_and_weekend_exception():
    mid = frame(["2024-01-02 10:00", "2024-01-02 11:00"])            # 1h hole on 15m data
    _, r = validate_bars(mid, "15m")
    assert len(r.gaps) == 1 and r.weekend_gaps == 0
    wk = frame(["2024-01-05 21:45", "2024-01-07 22:00"])             # Fri close -> Sun open
    _, r = validate_bars(wk, "15m")
    assert not r.gaps and r.weekend_gaps == 1


def test_naive_index_and_missing_columns_raise():
    with pytest.raises(ValueError):
        validate_bars(pd.DataFrame({"open": [1.0]}, index=pd.DatetimeIndex(["2024-01-01"], tz="UTC")), "15m")
    naive = pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1]},
                         index=pd.DatetimeIndex(["2024-01-01"]))
    with pytest.raises(ValueError):
        validate_bars(naive, "15m")


def test_staleness_measured_from_bar_close():
    last_open = pd.Timestamp("2024-01-02 10:00", tz="UTC")           # closes 10:15
    now = pd.Timestamp("2024-01-02 10:16", tz="UTC")
    assert not is_stale(last_open, "15m", now, 120)
    assert is_stale(last_open, "15m", pd.Timestamp("2024-01-02 10:18", tz="UTC"), 120)


def test_load_dukascopy_style_csv(tmp_path):
    p = tmp_path / "eurusd.csv"
    p.write_text("Gmt time,Open,High,Low,Close,Volume\n"
                 "02.01.2024 10:00:00.000,1.10,1.11,1.09,1.105,10\n"
                 "02.01.2024 10:15:00.000,1.105,1.12,1.10,1.11,12\n")
    df, rep = load_csv(p, "eurusd", "15m")
    assert rep.ok and len(df) == 2
    assert df.index[0] == pd.Timestamp("2024-01-02 10:00", tz="UTC")
    assert df.attrs["source"] == DataSource.REPLAY.value and df.attrs["symbol"] == "EURUSD"


def test_load_csv_without_timestamp_raises(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError):
        load_csv(p, "EURUSD", "15m")


def test_synthetic_is_labelled_and_valid():
    df = make_synthetic(n=500)
    assert df.attrs["source"] == "synthetic"
    _, rep = validate_bars(df, "15m")
    assert rep.ok
