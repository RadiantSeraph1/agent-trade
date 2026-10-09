"""OANDA v20 PRACTICE-account client: prices and candles (read-only).

Hard guard: only the practice hosts are allowed. Any other host raises at
construction, so live money cannot be reached through this class. Order
placement is intentionally not implemented here yet.
Token is passed in by the caller (Secret Manager) and never logged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import pandas as pd
import requests

PRACTICE_REST = "https://api-fxpractice.oanda.com"
ALLOWED_HOSTS = {"api-fxpractice.oanda.com", "stream-fxpractice.oanda.com"}


class OandaError(RuntimeError):
    pass


def instrument(symbol: str) -> str:
    s = symbol.upper().replace("/", "").replace("_", "")
    if len(s) != 6:
        raise OandaError(f"bad symbol {symbol!r}")
    return f"{s[:3]}_{s[3:]}"


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: float
    ask: float
    quote_time: datetime
    recv_time: datetime
    tradeable: bool

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def age_seconds(self) -> float:
        return (self.recv_time - self.quote_time).total_seconds()


class OandaPracticeClient:
    def __init__(self, token: str, account_id: str, base_url: str = PRACTICE_REST,
                 session: requests.Session | None = None, timeout: float = 10.0):
        if not token or not account_id:
            raise ValueError("token and account_id are required")
        if urlparse(base_url).hostname not in ALLOWED_HOSTS or not base_url.startswith("https://"):
            raise ValueError("only OANDA practice hosts are allowed (demo-only guard)")
        self._token, self.account_id = token, account_id
        self.base_url = base_url.rstrip("/")
        self._s = session or requests.Session()
        self.timeout = timeout

    def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            r = self._s.get(f"{self.base_url}{path}", params=params, timeout=self.timeout,
                            headers={"Authorization": f"Bearer {self._token}"})
        except requests.RequestException as e:
            raise OandaError(f"request failed: {type(e).__name__}") from None
        if r.status_code != 200:
            raise OandaError(f"HTTP {r.status_code} for {path.split('?')[0]}")
        return r.json()

    def current_price(self, symbol: str, now: datetime | None = None) -> Quote:
        j = self._get(f"/v3/accounts/{self.account_id}/pricing", {"instruments": instrument(symbol)})
        try:
            p = j["prices"][0]
            bid, ask = float(p["bids"][0]["price"]), float(p["asks"][0]["price"])
            qt = pd.Timestamp(p["time"]).tz_convert("UTC").to_pydatetime()
            tradeable = bool(p.get("tradeable", False))
        except (KeyError, IndexError, ValueError, TypeError):
            raise OandaError("malformed price payload") from None
        if not (bid > 0 and ask > 0) or ask < bid:
            raise OandaError(f"invalid quote bid={bid} ask={ask}")
        return Quote(symbol.upper(), bid, ask, qt, now or datetime.now(timezone.utc), tradeable)

    def candles(self, symbol: str, granularity: str = "M15", count: int = 500,
                to: str | None = None) -> pd.DataFrame:
        """Completed candles only, as the bars contract (bid OHLC + spread from ask-bid close)."""
        params = {"price": "BA", "granularity": granularity, "count": min(count, 5000)}
        if to:
            params["to"] = to
        j = self._get(f"/v3/instruments/{instrument(symbol)}/candles", params)
        rows = []
        try:
            for c in j["candles"]:
                if not c.get("complete", False):
                    continue
                b, a = c["bid"], c["ask"]
                rows.append((pd.Timestamp(c["time"]).tz_convert("UTC"), float(b["o"]), float(b["h"]),
                             float(b["l"]), float(b["c"]), float(c.get("volume", 0)), float(a["c"]) - float(b["c"])))
        except (KeyError, ValueError, TypeError):
            raise OandaError("malformed candle payload") from None
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume", "spread"]).set_index("ts")
        df.attrs.update(symbol=symbol.upper(), source="live", vendor="oanda_practice", price_basis="bid")
        return df
