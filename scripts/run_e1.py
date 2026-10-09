"""E1 (pre-registered, docs/EXPERIMENTS.md): trend_following_v1 defaults on train + validation.
The frozen test window is physically excluded: data is cut at 2023-12-31."""
import json
import sys

import pandas as pd

from fxlab.backtesting.engine import run_backtest
from fxlab.config import RiskConfig
from fxlab.strategies.trend_following import TrendFollowingV1

bars = pd.read_pickle("data/raw/eurusd_15m_2020_2025.pkl")
bars_dev = bars[bars.index < "2024-01-01"].copy()
bars_dev.attrs.update(bars.attrs)
assert bars_dev.index.max() < pd.Timestamp("2024-01-01", tz="UTC")

windows = {"train 2020-22": ("2020-01-01", "2023-01-01"), "validation 2023": ("2023-01-01", "2024-01-01")}
for name, (a, b) in windows.items():
    r = run_backtest(bars_dev, TrendFollowingV1(), RiskConfig(), start=a, end=b)
    m = r.metrics
    print(f"\n=== E1 {name} | {r.kind} on {r.data_source}/{bars.attrs.get('vendor')} | {r.symbol} {r.timeframe} ===")
    print(f"trades={m.n_trades}  net_return={m.net_return_pct:.2f}%  maxDD={m.max_drawdown_pct:.2f}%")
    print(f"win_rate={m.win_rate}  profit_factor={m.profit_factor}  expectancy={m.expectancy}  CI95={m.expectancy_ci95}")
    print(f"avg_win={m.avg_win}  avg_loss={m.avg_loss}  sharpe={m.sharpe_daily_annualised}")
    print("exit reasons:", r.trades["exit_reason"].value_counts().to_dict() if len(r.trades) else {})
    print("rejections:", r.rejection_counts, "| skipped(gap):", len(r.skipped))
    print("decisions:", len(r.decisions), "| note:", m.note or "sample ok")
