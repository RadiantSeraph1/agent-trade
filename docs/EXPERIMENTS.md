# Experiment log

Pre-register each experiment BEFORE running it: hypothesis, data, train/val
windows, frozen test window, parameters and number of configurations to be
tried, success criterion.

## Frozen windows (set 2026-10-09, BEFORE any real data was downloaded or any backtest run on it)

| Role | Window (UTC, bar-open times) | Rules |
|------|------------------------------|-------|
| Train | 2020-01-01 to 2022-12-31 | May be examined and used for parameter exploration. |
| Validation | 2023-01-01 to 2023-12-31 | Used to choose among candidate configurations. |
| **Frozen test** | **2024-01-01 to 2025-12-31** | Not examined during development. Touched once per pre-registered hypothesis; every touch is logged below. |
| Second holdout | 2026-01-01 onward | Untouched; reserved for a final confirmation. |

Pair/timeframe: EURUSD, 15m (resampled from M1 bid bars). Source: HistData M1.

## E1: baseline trend_following_v1, default parameters (NOT tuned)

- Hypothesis: the untuned EMA20/50-cross baseline has positive net expectancy after modelled costs.
- Parameters: fast=20, slow=50, atr_n=14, rsi_n=14, stop=1.5 ATR, reward:risk=2.0, RSI filters 70/30. Risk config = RiskConfig() defaults. Exec: spread 1.0 pip, slippage 0.2 pip, commission 0 (assumptions).
- Configurations tried: 1 (no sweep).
- Run order: train, then validation. Test only after both are reported here.
- G3 edge bar (set now): on the frozen test set, net expectancy > 0 AND lower bound of the 95% bootstrap CI for expectancy > 0 AND >= 100 trades AND max drawdown below the configured limit.
- Touches of the frozen test window: NONE (data was physically cut at 2023-12-31 for all runs below).

### Results (dev data only; scripts/run_e1.py, scripts/diag_e1b.py)

Data: HistData EURUSD M1 bid -> 15m, 2020-2025 (timezone corrected, see DECISIONS #24). Backtest, not live.

**E1 as pre-registered (10% drawdown halt active)**

| Window | Trades | Net return | Max DD | Win rate | Profit factor | Expectancy/trade | 95% CI |
|---|---|---|---|---|---|---|---|
| Train 2020-22 | 261 | -9.17% | 10.19% | 32.6% | 0.89 | -3.51 | (-10.8, +3.5) |
| Validation 2023 | 77 | -9.31% | 10.21% | 27.3% | 0.66 | -12.09 | (-25.7, +1.7) |

Both runs hit the drawdown halt and then stopped trading permanently, so these numbers describe behaviour up to the halt, not the whole window. Validation is flagged INSUFFICIENT SAMPLE (<100 trades).

**E1b diagnostics (same strategy parameters; only the evaluation harness varies; dev data only)**

| Config | Window | Trades | Net return | Win rate | PF | Expectancy | 95% CI |
|---|---|---|---|---|---|---|---|
| A: halt off, modelled costs | Train | 759 | -40.76% | 30.8% | 0.80 | -5.37 | (-9.0, -1.5) |
| A: halt off, modelled costs | Val | 225 | -11.47% | 32.4% | 0.84 | -5.10 | (-12.8, +2.4) |
| B: halt off, ZERO costs | Train | 769 | -3.98% | 32.8% | 0.98 | -0.52 | (-5.0, +4.3) |
| B: halt off, ZERO costs | Val | 226 | -0.50% | 33.6% | 0.99 | -0.22 | (-8.5, +7.8) |

Configurations examined so far: 3 (E1, A, B), each on train and validation.

**Interpretation (what the evidence supports, and no more):**
- With costs, the baseline loses money; on the 759-trade train sample the CI excludes zero (negative).
- With zero costs, expectancy is statistically indistinguishable from zero: there is no gross edge for costs to be hiding. A ~33% win rate at 2:1 reward:risk is roughly breakeven by construction.
- E1 therefore FAILS the G3 edge bar on development data. The frozen test window has NOT been spent and should not be on this hypothesis.
- Costs are modelled by assumption (1.0 pip spread, 0.2 pip slippage), not measured. A tighter real spread would shrink the loss but cannot create an edge that the zero-cost run does not show.

**Data-quality caveats**
- HistData 2023 is sparser (~13% fewer 15m bars; quiet buckets with no ticks are absent). 680 validation-window signals were skipped by the >45-minute gap rule. Validation numbers are therefore less reliable than train.
- Prices are bid only; spread is assumed.
- Swap/rollover is not modelled.

---

## Round 2 pre-registration (written 2026-10-09, BEFORE any Round 2 code was written or run)

Why: E1 showed no gross edge (zero-cost expectancy ~0). Round 2 tests three structurally different ideas. Each is run ONCE with the parameters below. No parameter is changed after seeing results; a changed idea is a new hypothesis and increases the count.

### Evaluation harness (identical for all three; fixed now)
- Data: EURUSD HistData bid bars, dev data only (< 2024-01-01), train 2020-2022, validation 2023.
- Costs: spread 1.0 pip, slippage 0.2 pip, commission 0 (assumptions; same as E1). Zero-cost run reported for information only, never used for the decision.
- Risk config defaults EXCEPT max_drawdown_pct=50 so the halt does not truncate the sample. (Halt behaviour is evaluated separately; here we estimate per-trade edge.) Daily loss limit stays on.
- Metric of record: expectancy in R-multiples = net_pnl / risk_amount at entry (comparable across strategies and position sizes).
- Multiple-testing: configurations examined so far = 3 (E1, A, B) + 3 new = 6. Bonferroni-style confidence level for the decision: 1 - 0.05/6 = 99.17% bootstrap CI (2000 resamples, seed 12345) on pooled train+validation R-multiples.
- A hypothesis ADVANCES to the frozen test only if ALL hold: (1) pooled expectancy_R > 0 with the 99.17% CI lower bound > 0; (2) expectancy_R > 0 in train AND in validation separately; (3) pooled trades >= 100; (4) max drawdown (halt off) <= 30%.
- Otherwise it is REJECTED and the frozen test window is not touched for it.
- The frozen test is spent at most once per advancing hypothesis, with unchanged parameters.

### H1: London-open breakout of the Asian range (15m)
- Idea: overnight consolidation stores order flow released at the London open.
- Asian range = high/low of 15m bars opening 00:00-06:45 UTC of the same UTC date (known by 07:00). Trade only if range is 15-60 pips.
- Signal: FIRST 15m bar of the day, opening 07:00-10:45 UTC, whose CLOSE is above the range high (BUY) or below the range low (SELL). One signal per day.
- Stop = range midpoint. Take-profit = 1.5 x risk. No time exit (positions run to stop/target).
- Parameters (all fixed): range window 00:00-07:00 UTC, trade window 07:00-11:00 UTC, range size 15-60 pips, TP multiple 1.5.

### H2: Mean reversion in ranging conditions (15m)
- Idea: when trend strength is low, stretched prices revert to the mean.
- Ranging = |EMA20 - EMA50| / ATR14 < 1.0.
- z = (close - SMA50) / rolling std(50, ddof=1) of close.
- Signal: BUY when z crosses below -2.0 (prev z >= -2.0, current z < -2.0) while ranging; SELL when z crosses above +2.0 while ranging.
- Stop = 1.0 x ATR14; Take-profit = 1.5 x risk (risk config requires reward:risk >= 1.5). No time exit.

### H3: Trend following on hourly bars (1h)
- Idea: same EMA-cross rule as E1, but on 1h bars the fixed spread/slippage is a smaller share of each stop.
- Identical parameters to E1 (EMA20/50, ATR14, RSI14 filters 70/30, stop 1.5 ATR, RR 2.0). 1h bars are resampled from the 15m bars (open first, high max, low min, close last).
- Sessions per default RiskConfig (07:00-20:00 UTC entries).

### Results
Run 2026-10-09 with scripts/run_round2.py, dev data only. Frozen test window NOT touched.

| Hypothesis | Train n / expR | Val n / expR | Pooled n | Pooled expR | 99.17% CI | Zero-cost expR (info) | Outcome |
|---|---|---|---|---|---|---|---|
| H1 London breakout 15m | 220 / -0.110 | 78 / +0.128 | 298 | -0.048 | (-0.239, +0.134) | +0.029 (n=593) | see validity note; fails rule |
| H2 Mean reversion 15m | 536 / -0.200 | 169 / -0.126 | 705 | -0.182 | (-0.298, -0.072) | +0.031 (n=1477) | see validity note; fails rule |
| H3 Trend following 1h | 191 / -0.002 | 56 / +0.128 | 247 | +0.027 | (-0.203, +0.259) | +0.092 (n=247) | **REJECT** (CI includes 0; train not positive) |

**H3 is the only valid test as specified. REJECTED.** Pooled expectancy +0.027R is indistinguishable from zero, and train expectancy was not positive.

**VALIDITY NOTE for H1 and H2 (harness/specification flaw found after the run):** their take-profit was pre-registered as exactly 1.5 x risk, equal to the risk engine's minimum reward:risk of 1.5. The engine measures reward:risk from the real entry price. BUYs enter at the ask (bid + spread), which pushes reward:risk just below 1.5, so the engine vetoed them. Checked on H1 train: 287 of 287 BUY signals rejected for `minimum_reward_to_risk`, versus 68 of 288 SELL signals. H1 (and very likely H2) therefore traded SHORT ONLY, which is not the hypothesis registered. Their with-cost results are NOT a valid test of the hypotheses and are not evidence for or against the underlying ideas. They are also not evidence of a short-side edge: the sample is one side of a market that drifted, and no such hypothesis was registered.

What the information-only zero-cost runs do show (both sides trade there): gross expectancy of about +0.03R over 593 and 1477 trades. Modelled costs (1.2 pips on stops of roughly 8-15 pips) cost on the order of 0.1R per trade, so a gross edge that small would not survive them. This is suggestive, not a pre-registered result.

**Configurations examined so far: 6** (E1, A, B, H1, H2, H3). A corrected H1b/H2b (e.g. take-profit 1.75R so net reward:risk clears 1.5 after spread) would be NEW hypotheses and raise the count to 8 (CI level 99.375%). Not run.

**Lesson recorded:** every pre-registered strategy must be checked for risk-engine compatibility (net-of-spread reward:risk, session window, sizing) before registration.

**Status of G3:** no hypothesis has advanced. The frozen test window (2024-2025) has not been used for any hypothesis.
