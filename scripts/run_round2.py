"""Round 2 (pre-registered in docs/EXPERIMENTS.md). DEV DATA ONLY (< 2024-01-01).
Decision rule is fixed in the log; this script only reports."""
import numpy as np
import pandas as pd

from fxlab.analytics.metrics import bootstrap_ci, r_multiples
from fxlab.backtesting.engine import run_backtest
from fxlab.config import RiskConfig
from fxlab.execution.paper import ExecConfig
from fxlab.market_data.resample import resample_bars
from fxlab.strategies.london_breakout import LondonBreakoutV1
from fxlab.strategies.mean_reversion import MeanReversionV1
from fxlab.strategies.trend_following import TrendFollowingV1

N_CONFIGS = 6
LEVEL = 1 - 0.05 / N_CONFIGS
bars15 = pd.read_pickle("data/raw/eurusd_15m_2020_2025.pkl")
dev15 = bars15[bars15.index < "2024-01-01"].copy(); dev15.attrs.update(bars15.attrs)
assert dev15.index.max() < pd.Timestamp("2024-01-01", tz="UTC")
dev1h = resample_bars(dev15, "1h")
RC = RiskConfig(max_drawdown_pct=50.0)
W = {"train": ("2020-01-01", "2023-01-01"), "val": ("2023-01-01", "2024-01-01")}

H = {"H1 london_breakout (15m)": (LondonBreakoutV1(), dev15),
     "H2 mean_reversion (15m)": (MeanReversionV1(), dev15),
     "H3 trend_following (1h)": (TrendFollowingV1(), dev1h)}

for name, (strat, data) in H.items():
    rs, dds, rows = {}, [], []
    for w, (a, b) in W.items():
        r = run_backtest(data, strat, RC, ExecConfig(), start=a, end=b)
        x = r_multiples(r.trades); rs[w] = x; dds.append(r.metrics.max_drawdown_pct)
        rows.append(f"  {w:5s} n={len(x):4d} expR={x.mean() if len(x) else float('nan'):+.3f} "
                    f"win={r.metrics.win_rate if r.metrics.win_rate is not None else float('nan'):.3f} "
                    f"ret={r.metrics.net_return_pct:+.1f}% dd={r.metrics.max_drawdown_pct:.1f}%")
    pooled = np.concatenate([rs["train"], rs["val"]])
    ci = bootstrap_ci(pooled, level=LEVEL) if len(pooled) > 1 else None
    # zero-cost info run (not used for the decision)
    z = data.copy(); z["spread"] = 0.0
    zr = np.concatenate([r_multiples(run_backtest(z, strat, RC, ExecConfig(default_spread_pips=0, slippage_pips=0),
                                                  start=a, end=b).trades) for a, b in W.values()])
    c1 = len(pooled) > 1 and ci[0] > 0
    c2 = all(len(rs[w]) > 0 and rs[w].mean() > 0 for w in W)
    c3 = len(pooled) >= 100
    c4 = max(dds) <= 30
    print(f"\n{name}  [backtest on replay/histdata, dev data only]")
    print("\n".join(rows))
    print(f"  pooled n={len(pooled)} expR={pooled.mean() if len(pooled) else float('nan'):+.3f} "
          f"CI{LEVEL*100:.2f}%={tuple(round(v,3) for v in ci) if ci else None}")
    print(f"  info only, zero costs: n={len(zr)} expR={zr.mean() if len(zr) else float('nan'):+.3f}")
    print(f"  criteria: CI_lower>0={c1}  both_windows_positive={c2}  n>=100={c3}  maxDD<=30%={c4}  => "
          f"{'ADVANCE' if all([c1,c2,c3,c4]) else 'REJECT'}")
