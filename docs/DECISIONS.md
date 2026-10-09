# Decisions

| # | Date | Decision | Rationale |
|---|------|----------|-----------|
| 1 | 2026-10-09 | Local-first modular monolith | Simple, cheap; cloud deployable later. |
| 2 | 2026-10-09 | Python 3.12 + uv (system python is 3.9) | Modern typing/pandas; uv already installed. |
| 3 | 2026-10-09 | Custom event-driven backtester, no Backtrader | Risk veto must sit inside the loop; full control of fill/cost rules. |
| 4 | 2026-10-09 | Plain Python pipeline, no LangGraph yet | Linear workflow; revisit if branching/state needs justify it. |
| 5 | 2026-10-09 | No live-money execution code | Project safety boundary. (Amended by #6.) |
| 6 | 2026-10-09 | MT5 DEMO account may receive real API orders; guarded by a per-order demo-account check | User has an MT5 demo; tests execution and live conditions with no real funds. Live-money still needs a new decision after G3. |
| 7 | 2026-10-09 | Cloud-first: PWA + FastAPI on Google Cloud, no local runtime | User request. SQLite is not durable on Cloud Run, so persistence moves to Firestore or Cloud SQL (open). |
| 8 | 2026-10-09 | MT5 bridge: start with MetaApi trial, Windows VM as fallback | Cheapest path that supports order execution and account linking; pricing to be verified at signup. |
| 9 | 2026-10-09 | Dukascopy/HistData for history | User choice. Terms to be verified before bulk download. |
| 10 | 2026-10-09 | Gemini fine-tuning is a G4 experiment, not a Phase 2 task | User choice. Needs our own labelled dataset and a baseline to beat. |
| 11 | 2026-10-09 | Firestore for live state, BigQuery for analytics | User choice. Replaces SQLite in the cloud; SQLAlchemy layer in Phase 2 becomes a repository interface with a Firestore impl. |
| 12 | 2026-10-09 | Single user, Google sign-in via Firebase Auth, email allowlist, fail closed | User choice. |
| 13 | 2026-10-09 | One Cloud Run service serves API and PWA | Fewer moving parts than separate hosting. |
| 14 | 2026-10-09 | Build order: cloud skeleton + PWA shell, then deterministic core | User choice. Gates G1-G3 still apply before AI/MT5 work. |
| 15 | 2026-10-09 | GCP project `<GCP_PROJECT_ID>`, region us-central1, Firestore (native) created | User choice. Cloud Run service `fxlab` max 2 instances. |
| 16 | 2026-10-09 | Org policy blocks allUsers on Cloud Run; service stays private | <owner-org-domain> org restriction. Phone access path undecided (see open). |
| 17 | 2026-10-09 | Granted default compute SA 4 build roles (builder, storage.objectUser, artifactregistry.writer, logging.logWriter) | Needed for source deploys; revocable. |
| 18 | 2026-10-09 | Health route is /api/health (Cloud Run reserves /healthz) | Found while deploying. |
| 19 | 2026-10-09 | Cloud Run direct IAP enabled; access = <owner-org-email> only (roles/iap.httpsResourceAccessor) | Org blocks public services. Verified: anonymous requests redirect to Google sign-in. |
| 20 | 2026-10-09 | App auth verifies the IAP-signed JWT (aud `/projects/<PROJECT_NUMBER>/locations/us-central1/services/fxlab`); Firebase Auth dropped | Verified working on a phone. Env: FXLAB_IAP_AUDIENCE, FXLAB_ALLOWED_EMAILS set on the Cloud Run service. |
| 21 | 2026-10-09 | Budget alert: $50/month on <GCP_PROJECT_ID> (50/90/100%), notify-only | Created via Cloud Billing Budgets; does not cap spend. |
| 22 | 2026-10-09 | Core v0: bars are BID; ask = bid+spread; fills at next-bar open; stop-first on same-bar touch; gap-through stop fills at worse open; TP fills at target; swap NOT yet modelled | See execution/paper.py header. Default spread 1.0 pip and slippage 0.2 pip are ASSUMPTIONS until measured from the MT5 demo. |
| 23 | 2026-10-09 | Data terms (from vendor pages, 2026-10-09): Dukascopy downloads are licensed for personal non-commercial use; HistData offers free M1 bid-based bars by pair/year/month | HistData timestamp timezone must be verified before loading (loader assumes UTC for naive times). |
| 24 | 2026-10-09 | HistData timestamps are New York LOCAL time with DST, not fixed EST as its FAQ claims | Verified on 2020-2025 EURUSD: the 08:30 NY release spike is at 12:30 UTC in summer and 13:30 UTC in winter, London open 07:00/08:00, Friday close 20:45/21:45 UTC. A fixed UTC-5 shift put summer data an hour off. Loader localises to America/New_York. |
| 25 | 2026-10-09 | HistData EURUSD M1 2020-2025 downloaded to data/raw/histdata (git-ignored), 15m bars in data/raw/eurusd_15m_2020_2025.pkl | User-approved download; 6 yearly zips, ~20 MB. |
| 26 | 2026-10-09 | Round 2 (H1-H3) logged; none advanced; H1/H2 declared invalid-as-specified (spread vs min reward:risk made them short-only); frozen test untouched | See docs/EXPERIMENTS.md. Pre-registration checklist now includes risk-engine compatibility. |
| 27 | 2026-10-09 | Drop MetaApi/MT5 bridge for now (user has no card funds; MetaQuotes-Demo is not a real broker). Use a free broker demo API instead; OANDA v20 practice is the default, hard-guarded to practice hosts | MT5 cannot be self-hosted for free (Windows-only Python package). MetaApi trial account created by user should be deleted to avoid charges. IG and Capital.com demo APIs remain alternatives; availability for the user's country unverified. |
| 28 | 2026-10-09 | MetaApi code (market_data/metaapi.py, jobs/record_quotes.py) kept but unused | Read-only, tested; can be revived if a funded bridge is wanted later. |
| 29 | 2026-10-09 | PROJECT PAUSED by user. Cloud Run service `fxlab` deleted (redeploy: `gcloud run deploy fxlab --source . --region us-central1 --project <GCP_PROJECT_ID> --no-allow-unauthenticated --iap --max-instances 2 --set-env-vars ...`; env vars FXLAB_ALLOWED_EMAILS and FXLAB_IAP_AUDIENCE, see #19/#20). UPDATE same day: user then approved deleting the empty Firestore (default) DB, Artifact Registry repo cloud-run-source-deploy and bucket run-sources-<GCP_PROJECT_ID>-us-central1; all deleted and verified (a restart must recreate Firestore, region us-central1 was chosen in #15). Left in place: $50 budget alert, enabled APIs, IAM grants (#17), IAP access binding. No VMs/jobs/schedulers/secrets ever existed. | User request. MetaApi account is outside Google Cloud and must be deleted by the user in its dashboard. |

## Open
- Untested: PWA install on iPhone/Android behind IAP (manifest uses crossorigin=use-credentials).
- Gmail account (<owner-personal-email>) cannot be granted if org policy restricts external identities.
- Historical data source (bid/ask?) — unverified: Dukascopy, HistData.
- Live quote source and terms — unverified.
- Economic-calendar source.
- Google Cloud credit expiry and eligible services.
- gcloud: active account is <owner-org-email>, default project <OTHER_PROJECT_ID>; target project `brain` not yet probed (auth expired).
