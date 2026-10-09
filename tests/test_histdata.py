import io
import zipfile

import pandas as pd

from fxlab.market_data.histdata import load_histdata, read_m1_csv, resample

M1 = (
    "20240102 170000;1.1000;1.1010;1.0995;1.1005;0\n"
    "20240102 170100;1.1005;1.1020;1.1000;1.1015;0\n"
    "20240102 171500;1.1015;1.1030;1.1010;1.1025;0\n"   # next 15m bucket; minutes 2-14 missing
)


def test_new_york_local_time_converted_with_dst():
    winter = read_m1_csv(io.StringIO(M1))                               # EST: UTC-5
    assert winter.index[0] == pd.Timestamp("2024-01-02 22:00", tz="UTC")
    summer = read_m1_csv(io.StringIO("20240702 170000;1.1;1.1;1.1;1.1;0\n"))  # EDT: UTC-4
    assert summer.index[0] == pd.Timestamp("2024-07-02 21:00", tz="UTC")


def test_dst_weekend_transition_times_are_dropped_not_guessed():
    # 2024-03-10 02:30 does not exist in New York; 2024-11-03 01:30 is ambiguous.
    df = read_m1_csv(io.StringIO("20240310 023000;1.1;1.1;1.1;1.1;0\n20240311 090000;1.1;1.1;1.1;1.1;0\n"
                                 "20241103 013000;1.1;1.1;1.1;1.1;0\n"))
    assert len(df) == 1


def test_resample_ohlc_and_gap_preserved():
    out = resample(read_m1_csv(io.StringIO(M1)), "15m")
    assert len(out) == 2
    a = out.iloc[0]
    assert (a.open, a.high, a.low, a.close) == (1.1000, 1.1020, 1.0995, 1.1015)
    assert out.index[1] == pd.Timestamp("2024-01-02 22:15", tz="UTC")


def test_load_from_zip_labels_source(tmp_path):
    p = tmp_path / "x.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("DAT_ASCII_EURUSD_M1_2024.csv", M1)
        z.writestr("DAT_ASCII_EURUSD_M1_2024.txt", "status report, ignored")
    bars, rep = load_histdata([p], "eurusd", "15m")
    assert rep.ok and bars.attrs["source"] == "replay" and bars.attrs["price_basis"] == "bid"
