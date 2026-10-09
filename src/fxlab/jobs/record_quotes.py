"""Cloud Run Job: snapshot bid/ask for configured symbols into Firestore.

Read-only. Intended to run every minute from Cloud Scheduler. Idempotent: the
document id is symbol + quote timestamp, so a retry cannot duplicate a quote.

Env: METAAPI_TOKEN (from Secret Manager), METAAPI_ACCOUNT_ID, FXLAB_SYMBOLS (comma list,
default EURUSD,GBPUSD), FXLAB_METAAPI_BASE_URL (optional), FXLAB_QUOTES_COLLECTION.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Protocol

from fxlab.fx import pip_size
from fxlab.market_data.metaapi import DEFAULT_BASE_URL, MetaApiClient, MetaApiError, Quote

STALE_AFTER_SECONDS = 120.0


class QuoteStore(Protocol):
    def put(self, doc_id: str, doc: dict) -> bool: ...   # True if newly written


def quote_doc(q: Quote) -> tuple[str, dict]:
    pip = pip_size(q.symbol)
    doc = {"symbol": q.symbol, "bid": q.bid, "ask": q.ask, "spread": q.spread,
           "spread_pips": q.spread / pip, "quote_time": q.quote_time.isoformat(),
           "recv_time": q.recv_time.isoformat(), "age_s": q.age_seconds,
           "stale": q.age_seconds > STALE_AFTER_SECONDS,
           "data_source": "live", "venue": "mt5_demo_via_metaapi"}
    return f"{q.symbol}_{int(q.quote_time.timestamp() * 1000)}", doc


def record_once(client, store: QuoteStore, symbols: list[str]) -> dict[str, str]:
    """Returns per-symbol outcome: 'written' | 'duplicate' | 'error: ...'. Never raises for one bad symbol."""
    out: dict[str, str] = {}
    for sym in symbols:
        try:
            doc_id, doc = quote_doc(client.current_price(sym))
            out[sym] = "written" if store.put(doc_id, doc) else "duplicate"
        except MetaApiError as e:
            out[sym] = f"error: {e}"
    return out


class FirestoreQuoteStore:
    def __init__(self, collection: str = "quotes", project: str | None = None):
        from google.cloud import firestore
        self._col = firestore.Client(project=project).collection(collection)

    def put(self, doc_id: str, doc: dict) -> bool:
        from google.api_core.exceptions import AlreadyExists
        try:
            self._col.document(doc_id).create(doc)
            return True
        except AlreadyExists:
            return False


def main() -> int:
    token, acct = os.environ.get("METAAPI_TOKEN", ""), os.environ.get("METAAPI_ACCOUNT_ID", "")
    if not token or not acct:
        print("METAAPI_TOKEN / METAAPI_ACCOUNT_ID not set", file=sys.stderr)
        return 2
    symbols = [s.strip().upper() for s in os.environ.get("FXLAB_SYMBOLS", "EURUSD,GBPUSD").split(",") if s.strip()]
    client = MetaApiClient(token, acct, os.environ.get("FXLAB_METAAPI_BASE_URL", DEFAULT_BASE_URL))
    store = FirestoreQuoteStore(os.environ.get("FXLAB_QUOTES_COLLECTION", "quotes"))
    res = record_once(client, store, symbols)
    print(datetime.now(timezone.utc).isoformat(), res, flush=True)
    return 0 if all(not v.startswith("error") for v in res.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
