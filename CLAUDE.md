# Forex research lab

Read `docs/SPEC.md` first; it is the source of truth. Log choices in
`docs/DECISIONS.md` and experiments in `docs/EXPERIMENTS.md`.

Non-negotiables:
- Paper/replay, plus orders on a broker DEMO account only (decision #6). Never add live-money execution. Any broker executor must verify the account is a demo account (MT5 trade mode) on every order and refuse otherwise. Never ask for, log, or store MT5 passwords; the user links accounts in the bridge provider's own dashboard.
- Never fabricate prices or test results. Synthetic data must be labelled.
- Risk engine is deterministic and has absolute veto. LLMs never do arithmetic or override risk.
- Respect go/no-go gates (SPEC §3). Do not build the AI layer or dashboard before G3.
- No look-ahead. Signal on bar t close, fill on bar t+1 open. Same-bar stop+target ⇒ stop first.
- Don't touch the frozen test window while tuning.

Dev: `uv` + Python 3.12, venv `.venv`. `uv pip install -e ".[dev]"`, `pytest`.
Keep tests offline and deterministic. Report real test output.
