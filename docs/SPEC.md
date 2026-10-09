# Forex Research & Paper-Trading Lab — Specification (v2)

Status: living document. v2 incorporates the review of the original brief:
research framing, go/no-go gates, statistical rigor, FX mechanics, news context.

## 1. Purpose and framing

A **quantitative research project first, an AI project second.** The question:

> Can a rule-based, then AI-assisted, Forex system find opportunities that stay
> profitable **after costs**, out of sample, across regimes, without
> unacceptable risk?

"No edge found" is a valid, expected-possible outcome. Technical correctness
of the software is not evidence of a profitable strategy.

**Hard scope limits**
- Paper trading and historical replay only. No real-order execution method
  may exist anywhere in the codebase. No broker credentials.
- Never fabricate prices. Synthetic data is only for tests/demos and must be
  labelled as such everywhere it appears.
- Do not claim profitability or statistical significance without evidence.

## 2. Environment and conventions

- macOS, Apple M1, 8 GB RAM. Python 3.12 via `uv`, venv at `.venv`.
- Modular monolith in `src/fxlab/`. Everything replaceable behind an interface:
  data provider, AI provider, strategy, database, execution.
- Plain Python pipeline for orchestration. LangGraph only if a concrete need
  appears (decision recorded in `docs/DECISIONS.md`).
- Custom event-driven backtester (the risk veto must sit inside the loop).
  No Backtrader.
- Core test suite runs offline, deterministic, no paid APIs.

## 3. Go/no-go gates (the process backbone)

Work proceeds in order. A gate must pass, or the failure is documented and the
plan is revisited, before the next stage begins.

| Gate | Condition to proceed |
|------|----------------------|
| G1 | Deterministic core works end to end on fixtures (load → indicators → signal → risk → paper fill → persisted), tests green. |
| G2 | Backtester passes chronology / no-look-ahead tests. Costs, slippage, same-bar stop/target policy implemented and tested. |
| G3 | **Baseline strategy evaluated on held-out data after costs.** Test period frozen *before* tuning. If there is no credible edge (see §7), do **not** build the AI layer to "rescue" it. Document the result and decide: new baseline hypotheses, or stop. |
| G4 | AI layer is built only to answer a stated question (e.g. does news/macro context improve a filter?), with a pre-registered comparison. |
| G5 | Dashboard is built after G3. Minimal first (overview, positions, trades, rejections, risk, AI cost, data-source banner). |

The 12-page dashboard in the original brief is deferred and reduced.

## 4. Architecture

```
data provider ─▶ validation/normalisation ─▶ indicators ─▶ regime
        ─▶ news/calendar context (blackouts; LLM-readable summary)
        ─▶ strategy (explicit rules) ─▶ RISK ENGINE (deterministic, veto)
        ─▶ decision ─▶ paper execution ─▶ portfolio ─▶ persistence ─▶ analytics
```

Modules (`src/fxlab/`): `config`, `market_data`, `indicators`, `market_regime`,
`news`, `strategies`, `risk`, `execution`, `portfolio`, `backtesting`,
`paper_trading`, `persistence`, `analytics`, `agents`, `ai`, `api`,
`dashboard`, `monitoring`.

### Agents
Five logical roles with validated Pydantic input/output schemas. Most are
deterministic code; an LLM is optional and only *interprets* computed
evidence. Be honest in naming: deterministic roles are functions, not "AI".

| Role | Nature |
|------|--------|
| Market Intelligence | Deterministic regime/volatility/freshness; may return UNKNOWN. LLM optional for summary. |
| Technical Analysis | Deterministic indicators; LLM may interpret, never invent values. |
| Strategy | Explicit testable rules → proposal or NO_TRADE. |
| Risk Management | **Deterministic only.** Absolute veto. Missing value ⇒ reject. |
| Decision | APPROVE / REJECT / NO_TRADE. Cannot approve what risk rejected. Idle ≠ reason to trade. |

Every decision records: id, data timestamp, pair, timeframe, strategy id,
evidence, agent findings, risk checks, reason, config version, model + prompt
version if AI was used.

## 5. Market data and FX mechanics

**Data**
- Interface supports CSV import, replay, live provider, health check, synthetic
  (labelled). Timestamps UTC. Validation: OHLC sanity, duplicates, gaps,
  staleness, invalid prices. Source id on every candle batch.
- Prefer **bid/ask** (or mid + modelled time-varying spread). Mid-only candles
  must be flagged as a limitation in reports.
- Candidate sources to evaluate (terms/limits **unverified** — check before
  relying): Dukascopy and HistData for history; a broker's free practice-account
  API or a rate-limited free data API for live quotes. Decision recorded in
  `docs/DECISIONS.md` once chosen.

**Mechanics that must be modelled**
- Pip value and conversion to account currency (quote ≠ account currency).
- Swap/rollover for positions held across the daily rollover.
- Weekend gaps and market closures (no fills inside gaps at stop price —
  gap-through fills at the worse available price).
- Time-varying spread (wider at rollover and around news).
- Execution convention: signal on bar *t* close → fill at bar *t+1* open (plus
  spread/slippage). Same-bar stop and target both touched ⇒ **stop assumed
  first** (conservative), documented and tested.
- Session restrictions configurable.

## 6. News / macro context
- Economic-calendar blackout windows are a *deterministic risk filter*
  (no new entries within N minutes of high-impact events for the pair's
  currencies).
- News/macro text is the one input an LLM can add beyond price. Any LLM use of
  it is a G4 experiment, evaluated against the same strategy without it.
- Source TBD (free calendar feed); recorded in `DECISIONS.md`.

## 7. Evaluation protocol (statistical rigor)

- Chronological splits: train / validation / **frozen out-of-sample test**.
  Test period is written to `docs/EXPERIMENTS.md` *before* any tuning and is
  touched once per hypothesis.
- Walk-forward validation for parameter selection.
- Every parameter sweep logs the number of configurations tried; apply a
  multiple-testing caution (e.g. deflated Sharpe or at minimum report trials).
- Bootstrap confidence intervals on expectancy, profit factor, Sharpe.
- Minimum sample: hundreds of trades before drawing any conclusion; report N
  and period always. Fewer than ~100 trades ⇒ label "insufficient sample".
- Metrics: net return after costs, max drawdown, win rate, profit factor
  (undefined if no losses), expectancy, Sharpe (where meaningful), trade
  frequency, rejection rate and reasons, by-strategy, by-regime.
- Record rejected trades and their counterfactual outcomes.
- "Edge" bar for G3 (to be refined, set before testing): positive net
  expectancy after costs on the frozen test set with the lower bound of the
  bootstrap CI above zero, and drawdown within configured limits.
- Three configurations compared: **Baseline** (rules only) · **AI-assisted**
  (rules + LLM interpretation/filter) · **Multi-agent** (full workflow). Include
  API cost in net results. If AI doesn't beat baseline net of cost, simplify.

### LLM-specific cautions
- **Training-data contamination:** LLMs have seen historical EUR/USD news and
  price narratives; historical backtests of LLM agents are *not clean*. Only
  forward paper trading is. Label LLM backtests accordingly.
- **Cost/determinism:** call the LLM only on candidate signals; temperature 0;
  store every prompt/response and support replay from recorded responses;
  cache only on identical inputs.
- AI failure ⇒ fail closed for AI-dependent decisions; risk controls unaffected.

## 8. Risk engine
Central validated config (conservative, labelled experimental): starting
balance, max risk/trade, max daily loss, max drawdown, max concurrent
positions, max exposure per pair and per currency (correlation-aware),
min reward:risk, max spread, max data age, max position size, sessions,
news blackout. Daily-loss / drawdown breach halts new entries until configured
reset. Every rejection stores exact reasons. Kill switch stops new trades;
existing simulated positions keep their stops/targets (documented).

## 9. AI integration (Vertex AI / Gemini) — optional
- Provider abstraction; no-LLM mode, mock mode, Vertex mode.
- Model id read from config and verified at runtime, never hard-coded.
- Timeouts, bounded retries, token/cost logging, daily & monthly application
  budgets, kill switch. App budgets are **not** a Google billing cap: also set
  Cloud Billing budgets/alerts. Check credit **expiry date** and eligible
  services before relying on them.
- No credentials in the repo; `.env.example` has placeholders only.

## 10. Persistence
SQLite via SQLAlchemy; schema versioning once complex. Persist data refs,
signals, agent I/O, decisions, risk checks, orders, fills, positions, snapshots,
metrics, errors, AI request metadata, config versions. Idempotent order
creation (dedupe key). Restart-safe.

## 11. Testing
pytest, offline, deterministic. Must cover: indicators vs independent values,
data validation, sizing, R:R, each risk limit, fills, stop/target (incl.
same-bar), accounting, drawdown, backtest chronology/look-ahead, duplicate
signals, AI budget + provider failure, persistence; plus the 12 integration
scenarios from the original brief.

## 12. Dashboard (after G3, minimal first)
Streamlit. Always-visible banners: PAPER TRADING and DATA SOURCE (live /
replay / synthetic) with timestamps and stale warnings. Initial pages:
overview, positions, trades, rejections & risk, performance, AI cost, health.
Backtest/config/agent-detail pages later.

## 13. Phases

1. **Environment & design** — structure, schemas, config, docs, tooling. *(current)*
2. **Deterministic core** — data models, validation, indicators, baseline
   strategy, risk engine, paper engine, SQLite. → G1
3. **Backtesting & analytics** — chronological engine, costs, metrics,
   frozen-test protocol. → G2, then **G3 (baseline evaluation)**
4. **Live data provider** — chosen after history source; health/stale checks.
5. **News/calendar context** — blackout filter.
6. **AI layer & multi-agent workflow** — only per G4.
7. **Dashboard** → G5.
8. **Validation** — full tests, sample backtest, e2e paper demo, verify no
   real-order path, document limitations.

## 14. Definition of done (prototype)
Installs clean; starts without cloud credentials; loads history; indicators;
rule-based signals; deterministic risk rejects/approves; simulated fills;
SQLite audit trail; chronological backtest with costs; honest analytics;
works with no LLM; optional Vertex provider; no real-order capability;
documented provider setup; reproducible demo. **Profitability is not part of
"done".**

## 15. Open decisions (tracked in docs/DECISIONS.md)
- Historical data source and format (bid/ask availability).
- Live quote source and its terms.
- Economic-calendar source.
- Baseline strategy parameters and the pre-registered test window.
- Google Cloud credit expiry / eligible services.
- Local only vs. later cloud deployment (default: local; keep cloud possible).
