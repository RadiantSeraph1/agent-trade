import numpy as np
import pandas as pd
import pytest

from fxlab.market_data.resample import resample_bars
from fxlab.market_data.synthetic import make_synthetic
from fxlab.schemas import Direction
from fxlab.strategies.london_breakout import LondonBreakoutV1
from fxlab.strategies.mean_reversion import MeanReversionV1


def day_bars(day="2024-01-03", asian_hi=1.1010, asian_lo=1.0970, post=()):
    """15m bars: flat-ish Asian session 00:00-06:45 (hi/lo set), then `post` closes from 07:00."""
    idx = pd.date_range(f"{day} 00:00", periods=28 + len(post), freq="15min", tz="UTC")
    c = np.full(len(idx), 1.0990)
    h = np.full(len(idx), 1.0995)
    l = np.full(len(idx), 1.0985)
    h[5], l[9] = asian_hi, asian_lo
    for k, px in enumerate(post):
        c[28 + k] = px
        h[28 + k], l[28 + k] = px + 0.0002, px - 0.0002
    df = pd.DataFrame({"open": c, "high": np.maximum(h, c), "low": np.minimum(l, c), "close": c,
                       "volume": 0.0, "spread": np.nan}, index=idx)
    df.attrs.update(symbol="EURUSD", timeframe="15m", source="synthetic")
    return df


def test_london_first_break_up_sets_midpoint_stop_and_tp():
    bars = day_bars(post=[1.1000, 1.1015, 1.1030])            # 07:15 closes above 1.1010
    s = LondonBreakoutV1()
    f = s.features(bars)
    i = 29
    assert f["first_up"].iloc[i] and not f["first_up"].iloc[30]     # only the FIRST break
    p = s.propose("EURUSD", "15m", bars, f, i)
    assert p.direction is Direction.BUY and p.stop_loss == pytest.approx(1.0990)   # (1.1010+1.0970)/2
    assert p.take_profit == pytest.approx(1.1015 + 1.5 * (1.1015 - 1.0990))
    assert s.propose("EURUSD", "15m", bars, f, 30) is None


def test_london_break_down_and_range_filter():
    bars = day_bars(post=[1.0990, 1.0960])
    s = LondonBreakoutV1()
    p = s.propose("EURUSD", "15m", bars, s.features(bars), 29)
    assert p.direction is Direction.SELL and p.stop_loss > p.entry_reference > p.take_profit
    tiny = day_bars(asian_hi=1.0995, asian_lo=1.0985, post=[1.0990, 1.1000])     # 10-pip range
    assert s.propose("EURUSD", "15m", tiny, s.features(tiny), 29) is None
    huge = day_bars(asian_hi=1.1100, asian_lo=1.0900, post=[1.0990, 1.1120])
    assert s.propose("EURUSD", "15m", huge, s.features(huge), 29) is None


def test_london_range_not_visible_before_seven_and_no_signal_after_window():
    bars = day_bars(post=[1.0990] * 20 + [1.1030])          # break arrives at 12:00, outside 07-11 window
    s = LondonBreakoutV1()
    f = s.features(bars)
    assert f["ah"].iloc[:28].isna().all() and f["ah"].iloc[28:].notna().all()
    assert not f["first_up"].any()


def test_london_features_are_causal():
    bars = make_synthetic(n=1500, seed=11)
    s = LondonBreakoutV1()
    full, part = s.features(bars), s.features(bars.iloc[:900])
    pd.testing.assert_frame_equal(full.iloc[:900].drop(columns="atr"), part.drop(columns="atr"))
    pd.testing.assert_series_equal(full["atr"].iloc[:900], part["atr"])


def test_mean_reversion_signals_and_ranging_filter():
    n = 120
    idx = pd.date_range("2024-01-02 08:00", periods=n, freq="15min", tz="UTC")
    rng = np.random.default_rng(2)
    c = 1.10 + rng.normal(0, 0.0002, n)
    c[100] -= 0.0030                                       # sharp dip -> z far below -2
    df = pd.DataFrame({"open": c, "high": c + 0.0002, "low": c - 0.0002, "close": c,
                       "volume": 0.0, "spread": np.nan}, index=idx)
    s = MeanReversionV1()
    f = s.features(df)
    p = s.propose("EURUSD", "15m", df, f, 100)
    assert p is not None and p.direction is Direction.BUY
    assert p.take_profit - p.entry_reference == pytest.approx(1.5 * (p.entry_reference - p.stop_loss))
    f2 = f.copy(); f2["trend_strength"] = 2.0              # trending -> no fade
    assert s.propose("EURUSD", "15m", df, f2, 100) is None


def test_mean_reversion_features_are_causal():
    bars = make_synthetic(n=800, seed=4)
    s = MeanReversionV1()
    pd.testing.assert_frame_equal(s.features(bars).iloc[:500], s.features(bars.iloc[:500]))


def test_resample_hourly_ohlc():
    idx = pd.date_range("2024-01-02 10:00", periods=8, freq="15min", tz="UTC")
    df = pd.DataFrame({"open": range(8), "high": [x + 1 for x in range(8)], "low": [x - 1 for x in range(8)],
                       "close": [x + 0.5 for x in range(8)], "volume": 1.0, "spread": np.nan}, index=idx)
    df.attrs.update(symbol="EURUSD", source="replay")
    h = resample_bars(df, "1h")
    assert len(h) == 2 and h.attrs["timeframe"] == "1h"
    assert (h.iloc[0].open, h.iloc[0].high, h.iloc[0].low, h.iloc[0].close) == (0, 4, -1, 3.5)
