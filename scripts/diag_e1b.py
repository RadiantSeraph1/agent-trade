"""E1b diagnostics on TRAIN+VALIDATION ONLY (data cut at 2023-12-31). Not tuning:
the strategy parameters are unchanged; only the evaluation harness varies."""
import pandas as pd

from fxlab.backtesting.engine import run_backtest
from fxlab.config import RiskConfig
from fxlab.execution.paper import ExecConfig
from fxlab.strategies.trend_following import TrendFollowingV1

bars = pd.read_pickle("data/raw/eurusd_15m_2020_2025.pkl")
dev = bars[bars.index < "2024-01-01"].copy(); dev.attrs.update(bars.attrs)
cfgs = {
 "A halt off, modelled costs": (RiskConfig(max_drawdown_pct=50.0), ExecConfig()),
 "B halt off, ZERO costs":     (RiskConfig(max_drawdown_pct=50.0), ExecConfig(default_spread_pips=0.0, slippage_pips=0.0)),
}
for name, (rc, ec) in cfgs.items():
    for w, (a, b) in {"train": ("2020-01-01", "2023-01-01"), "val": ("2023-01-01", "2024-01-01")}.items():
        # the dev dataset has fewer bars for B because spread column is NaN -> default spread used; zero it explicitly
        d = dev.copy()
        if ec.default_spread_pips == 0.0: d["spread"] = 0.0
        m = run_backtest(d, TrendFollowingV1(), rc, ec, start=a, end=b).metrics
        ci = tuple(round(x, 1) for x in m.expectancy_ci95) if m.expectancy_ci95 else None
        print(f"{name:28s} {w:5s} n={m.n_trades:3d} ret={m.net_return_pct:7.2f}% dd={m.max_drawdown_pct:5.2f}% "
              f"win={m.win_rate:.3f} pf={m.profit_factor:.3f} exp={m.expectancy:7.2f} ci95={ci}", flush=True)
