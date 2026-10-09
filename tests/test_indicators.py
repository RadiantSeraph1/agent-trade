import numpy as np
import pandas as pd
import pytest

from fxlab import indicators as ind


def S(v):
    return pd.Series(v, dtype=float)


def test_ema_hand_computed():
    out = ind.ema(S([1, 2, 3, 4, 5]), 3)
    assert out.iloc[:2].isna().all()
    assert out.tolist()[2:] == pytest.approx([2.0, 3.0, 4.0])


def test_rsi_hand_computed():
    out = ind.rsi(S([10, 11, 10, 12, 13]), 3)
    assert out.iloc[:3].isna().all()
    assert out.iloc[3] == pytest.approx(75.0)
    assert out.iloc[4] == pytest.approx(100 - 100 / (1 + 4.5))


def test_rsi_extremes():
    assert ind.rsi(S(range(1, 30)), 5).iloc[-1] == 100.0
    assert ind.rsi(S([5.0] * 20), 5).iloc[-1] == 50.0


def test_atr_hand_computed():
    h, l, c = S([10, 12, 13, 14]), S([9, 10, 11, 12]), S([9.5, 11, 12, 13])
    out = ind.atr(h, l, c, 2)
    assert out.iloc[:2].isna().all()
    assert out.iloc[2] == pytest.approx(2.25)
    assert out.iloc[3] == pytest.approx(2.125)


def test_macd_structure_and_constant_series():
    c = S(np.linspace(1, 2, 80))
    m = ind.macd(c)
    assert m["macd"].first_valid_index() == 25          # slow EMA(26) first value
    assert m["signal"].first_valid_index() == 25 + 8     # + signal(9) - 1
    assert (m["hist"].dropna() == (m["macd"] - m["signal"]).dropna()).all()
    flat = ind.macd(S([1.0] * 60))
    assert flat["macd"].dropna().abs().max() == pytest.approx(0)


def test_trend_direction_and_support_resistance():
    f, s = S([1, 2, 3, np.nan]), S([2, 2, 1, 1])
    assert ind.trend_direction(f, s).tolist()[:3] == [-1, 0, 1]
    assert np.isnan(ind.trend_direction(f, s).iloc[3])
    h, l = S([5, 6, 7, 20]), S([1, 2, 3, 0])
    sr = ind.support_resistance(h, l, 3)
    assert sr["resistance"].iloc[3] == 7 and sr["support"].iloc[3] == 1   # excludes bar 3 itself


def test_rolling_vol_zero_for_constant_growth():
    c = S(1.1 * np.exp(0.001 * np.arange(60)))
    assert ind.rolling_vol(c, 20).dropna().max() == pytest.approx(0, abs=1e-12)


def test_indicators_are_causal():
    """Value at t on a truncated series equals value at t on the full series."""
    rng = np.random.default_rng(1)
    c = S(1.1 + np.cumsum(rng.normal(0, 0.001, 300)))
    h, l = c + 0.0005, c - 0.0005
    cut = 200
    pairs = [
        (ind.ema(c, 20), ind.ema(c[:cut], 20)),
        (ind.rsi(c, 14), ind.rsi(c[:cut], 14)),
        (ind.atr(h, l, c, 14), ind.atr(h[:cut], l[:cut], c[:cut], 14)),
        (ind.macd(c)["hist"], ind.macd(c[:cut])["hist"]),
        (ind.rolling_vol(c), ind.rolling_vol(c[:cut])),
        (ind.support_resistance(h, l)["resistance"], ind.support_resistance(h[:cut], l[:cut])["resistance"]),
    ]
    for full, part in pairs:
        pd.testing.assert_series_equal(full.iloc[:cut], part, check_names=False)
