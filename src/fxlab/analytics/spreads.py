"""Turn recorded live quotes into a measured spread model (replaces assumed spreads)."""

from __future__ import annotations

import pandas as pd


def spread_profile(docs: list[dict], min_samples: int = 20) -> pd.DataFrame:
    """Per symbol and UTC hour: sample count and median/p90/max spread in pips.
    Stale quotes (market closed / feed lag) are excluded. Hours with too few
    samples are reported with NaN stats rather than guessed."""
    if not docs:
        return pd.DataFrame(columns=["symbol", "hour_utc", "n", "median_pips", "p90_pips", "max_pips"])
    df = pd.DataFrame(docs)
    df = df[~df["stale"].astype(bool)].copy()
    df["hour_utc"] = pd.to_datetime(df["quote_time"], utc=True).dt.hour
    g = df.groupby(["symbol", "hour_utc"])["spread_pips"]
    out = g.agg(n="size", median_pips="median", max_pips="max")
    out["p90_pips"] = g.quantile(0.9)
    thin = out["n"] < min_samples
    out.loc[thin, ["median_pips", "p90_pips", "max_pips"]] = float("nan")
    return out.reset_index()[["symbol", "hour_utc", "n", "median_pips", "p90_pips", "max_pips"]]
