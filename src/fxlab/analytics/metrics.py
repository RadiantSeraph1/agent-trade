from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

MIN_TRADES_FOR_CONCLUSIONS = 100


@dataclass
class Metrics:
    n_trades: int
    start: str | None
    end: str | None
    initial_equity: float
    final_equity: float
    net_return_pct: float
    max_drawdown_pct: float
    win_rate: float | None
    profit_factor: float | None       # None when undefined (no losing trades)
    expectancy: float | None          # mean net P&L per trade
    avg_win: float | None
    avg_loss: float | None
    gross_profit: float
    gross_loss: float
    sharpe_daily_annualised: float | None
    expectancy_ci95: tuple[float, float] | None   # bootstrap, only if n >= 2
    sufficient_sample: bool
    note: str

    def to_dict(self) -> dict:
        return asdict(self)


def max_drawdown_pct(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    return float(((peak - equity) / peak).max() * 100)


def bootstrap_ci(x: np.ndarray, n_boot: int = 2000, seed: int = 12345,
                 level: float = 0.95) -> tuple[float, float] | None:
    if len(x) < 2:
        return None
    rng = np.random.default_rng(seed)
    means = rng.choice(x, size=(n_boot, len(x)), replace=True).mean(axis=1)
    tail = (1 - level) / 2 * 100
    lo, hi = np.percentile(means, [tail, 100 - tail])
    return float(lo), float(hi)


def r_multiples(trades: pd.DataFrame) -> np.ndarray:
    """net P&L divided by the monetary risk taken at entry (needs meta['risk_amount'])."""
    if trades.empty:
        return np.array([])
    risk = trades["meta"].map(lambda m: m.get("risk_amount")).astype(float)
    return (trades["net_pnl"].astype(float) / risk).to_numpy()


def compute_metrics(trades: pd.DataFrame, equity: pd.Series, initial_equity: float) -> Metrics:
    n = len(trades)
    pnl = trades["net_pnl"].to_numpy(float) if n else np.array([])
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    gp, gl = float(wins.sum()), float(-losses.sum())
    final = float(equity.iloc[-1]) if len(equity) else initial_equity

    sharpe = None
    if len(equity) > 1:
        daily = equity.resample("1D").last().dropna()
        r = daily.pct_change().dropna()
        if len(r) >= 30 and r.std(ddof=1) > 0:
            sharpe = float(r.mean() / r.std(ddof=1) * math.sqrt(252))

    ok = n >= MIN_TRADES_FOR_CONCLUSIONS
    return Metrics(
        n_trades=n,
        start=str(equity.index[0]) if len(equity) else None,
        end=str(equity.index[-1]) if len(equity) else None,
        initial_equity=initial_equity, final_equity=final,
        net_return_pct=(final / initial_equity - 1) * 100,
        max_drawdown_pct=max_drawdown_pct(equity),
        win_rate=float(len(wins) / n) if n else None,
        profit_factor=(gp / gl) if gl > 0 else None,
        expectancy=float(pnl.mean()) if n else None,
        avg_win=float(wins.mean()) if len(wins) else None,
        avg_loss=float(losses.mean()) if len(losses) else None,
        gross_profit=gp, gross_loss=gl,
        sharpe_daily_annualised=sharpe,
        expectancy_ci95=bootstrap_ci(pnl),
        sufficient_sample=ok,
        note="" if ok else f"INSUFFICIENT SAMPLE: {n} trades < {MIN_TRADES_FOR_CONCLUSIONS}; no conclusions may be drawn",
    )
