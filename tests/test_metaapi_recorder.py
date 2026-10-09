from datetime import datetime, timedelta, timezone

import pytest

from fxlab.analytics.spreads import spread_profile
from fxlab.jobs.record_quotes import quote_doc, record_once
from fxlab.market_data.metaapi import MetaApiClient, MetaApiError

NOW = datetime(2024, 1, 2, 10, 0, 5, tzinfo=timezone.utc)


class FakeResp:
    def __init__(self, status, payload):
        self.status_code, self._p = status, payload

    def json(self):
        return self._p


class FakeSession:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        if isinstance(self.resp, Exception):
            raise self.resp
        return self.resp


def client(resp):
    s = FakeSession(resp)
    return MetaApiClient("SECRET-TOKEN", "acct1", session=s), s


GOOD = {"symbol": "EURUSD", "bid": 1.10000, "ask": 1.10012, "time": "2024-01-02T10:00:00.000Z"}


def test_price_parsed_with_spread_and_age():
    c, s = client(FakeResp(200, GOOD))
    q = c.current_price("EURUSD", now=NOW)
    assert q.spread == pytest.approx(0.00012) and q.age_seconds == 5.0
    assert s.calls[0][0].endswith("/users/current/accounts/acct1/symbols/EURUSD/current-price")
    assert s.calls[0][1]["auth-token"] == "SECRET-TOKEN"


@pytest.mark.parametrize("payload", [
    {"bid": 1.1, "ask": 1.0, "time": "2024-01-02T10:00:00Z"},     # crossed
    {"bid": -1, "ask": 1.0, "time": "2024-01-02T10:00:00Z"},
    {"ask": 1.1, "time": "2024-01-02T10:00:00Z"},                    # missing bid
    {"bid": 1.1, "ask": 1.2, "time": "garbage"},
])
def test_bad_payloads_rejected_not_recorded(payload):
    c, _ = client(FakeResp(200, payload))
    with pytest.raises(MetaApiError):
        c.current_price("EURUSD")


def test_http_errors_do_not_leak_token():
    import requests
    c, _ = client(FakeResp(401, {}))
    with pytest.raises(MetaApiError) as e:
        c.current_price("EURUSD")
    assert "SECRET-TOKEN" not in str(e.value)
    c, _ = client(requests.ConnectionError("boom SECRET-TOKEN"))
    with pytest.raises(MetaApiError) as e:
        c.current_price("EURUSD")
    assert "SECRET-TOKEN" not in str(e.value)


def test_client_has_no_order_methods():
    names = {n.lower() for n in dir(MetaApiClient)}
    assert not {n for n in names if any(w in n for w in ("order", "trade", "buy", "sell", "position"))}


def test_quote_doc_is_idempotent_id_and_flags_stale():
    c, _ = client(FakeResp(200, GOOD))
    q = c.current_price("EURUSD", now=NOW)
    doc_id, doc = quote_doc(q)
    assert doc_id == quote_doc(q)[0] and doc["spread_pips"] == pytest.approx(1.2) and not doc["stale"]
    old = c.current_price("EURUSD", now=NOW + timedelta(minutes=10))
    assert quote_doc(old)[1]["stale"]
    assert doc["data_source"] == "live"


class MemStore(dict):
    def put(self, k, v):
        if k in self:
            return False
        self[k] = v
        return True


def test_record_once_dedupes_and_isolates_failures():
    class C:
        def current_price(self, sym, now=None):
            if sym == "BAD":
                raise MetaApiError("HTTP 404")
            return MetaApiClient("t", "a", session=FakeSession(FakeResp(200, GOOD))).current_price(sym, now=NOW)

    store = MemStore()
    r1 = record_once(C(), store, ["EURUSD", "BAD"])
    r2 = record_once(C(), store, ["EURUSD"])
    assert r1 == {"EURUSD": "written", "BAD": "error: HTTP 404"} and r2 == {"EURUSD": "duplicate"} and len(store) == 1


def test_spread_profile_excludes_stale_and_thin_hours():
    docs = [{"symbol": "EURUSD", "quote_time": f"2024-01-02T10:{m:02d}:00Z", "spread_pips": 1.0 + (m % 3) * 0.1,
             "stale": False} for m in range(40)]
    docs += [{"symbol": "EURUSD", "quote_time": "2024-01-02T10:59:00Z", "spread_pips": 50.0, "stale": True}]
    docs += [{"symbol": "EURUSD", "quote_time": "2024-01-02T03:00:00Z", "spread_pips": 3.0, "stale": False}]
    p = spread_profile(docs, min_samples=20).set_index("hour_utc")
    assert p.loc[10, "n"] == 40 and p.loc[10, "max_pips"] < 2          # stale 50-pip outlier excluded
    assert p.loc[3, "n"] == 1 and pd_isna(p.loc[3, "median_pips"])      # too thin -> not guessed


def pd_isna(x):
    return x != x
