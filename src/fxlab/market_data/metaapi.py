"""Read-only MetaApi REST client (MT5 demo market data).

This module can READ prices and account info only. It has no order methods.
The token is passed in by the caller (from Secret Manager) and never logged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import requests

DEFAULT_BASE_URL = "https://mt-client-api-v1.new-york.agiliumtrade.ai"  # region-specific; configurable


class MetaApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: float
    ask: float
    quote_time: datetime        # when the broker price was produced (UTC)
    recv_time: datetime         # when we received it (UTC)

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def age_seconds(self) -> float:
        return (self.recv_time - self.quote_time).total_seconds()


class MetaApiClient:
    def __init__(self, token: str, account_id: str, base_url: str = DEFAULT_BASE_URL,
                 session: requests.Session | None = None, timeout: float = 10.0):
        if not token or not account_id:
            raise ValueError("token and account_id are required")
        self._token, self.account_id = token, account_id
        self.base_url = base_url.rstrip("/")
        self._s = session or requests.Session()
        self.timeout = timeout

    def _get(self, path: str) -> dict:
        url = f"{self.base_url}/users/current/accounts/{self.account_id}{path}"
        try:
            r = self._s.get(url, headers={"auth-token": self._token, "Accept": "application/json"},
                            timeout=self.timeout)
        except requests.RequestException as e:                    # never include headers in the message
            raise MetaApiError(f"request failed: {type(e).__name__}") from None
        if r.status_code != 200:
            raise MetaApiError(f"HTTP {r.status_code} for {path}")
        return r.json()

    def current_price(self, symbol: str, now: datetime | None = None) -> Quote:
        j = self._get(f"/symbols/{symbol}/current-price")
        try:
            bid, ask = float(j["bid"]), float(j["ask"])
            qt = datetime.fromisoformat(str(j["time"]).replace("Z", "+00:00"))
        except (KeyError, ValueError, TypeError):
            raise MetaApiError("malformed price payload") from None
        if not (bid > 0 and ask > 0) or ask < bid:
            raise MetaApiError(f"invalid quote bid={bid} ask={ask}")
        return Quote(symbol, bid, ask, qt.astimezone(timezone.utc), now or datetime.now(timezone.utc))

    def account_info(self) -> dict:
        return self._get("/account-information")
