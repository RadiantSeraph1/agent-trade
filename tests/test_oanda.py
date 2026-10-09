import pytest

from fxlab.market_data.oanda import OandaError, OandaPracticeClient, instrument


class R:
    def __init__(self, status, payload):
        self.status_code, self._p = status, payload

    def json(self):
        return self._p


class S:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append((url, params, headers))
        if isinstance(self.resp, Exception):
            raise self.resp
        return self.resp


def mk(resp):
    s = S(resp)
    return OandaPracticeClient("SECRET", "101-004-1", session=s), s


def test_only_practice_hosts_allowed():
    for bad in ("https://api-fxtrade.oanda.com", "http://api-fxpractice.oanda.com",
                "https://evil.example.com", "https://api-fxpractice.oanda.com.evil.com"):
        with pytest.raises(ValueError):
            OandaPracticeClient("t", "a", base_url=bad)
    OandaPracticeClient("t", "a", base_url="https://stream-fxpractice.oanda.com")


def test_symbol_mapping():
    assert instrument("EURUSD") == "EUR_USD" and instrument("gbp/usd") == "GBP_USD"
    with pytest.raises(OandaError):
        instrument("EUR")


PRICE = {"prices": [{"time": "2024-01-02T10:00:00.123456789Z", "tradeable": True,
                     "bids": [{"price": "1.10000"}], "asks": [{"price": "1.10012"}]}]}


def test_price_parsed():
    c, s = mk(R(200, PRICE))
    q = c.current_price("EURUSD")
    assert q.spread == pytest.approx(0.00012) and q.tradeable
    url, params, headers = s.calls[0]
    assert url.endswith("/v3/accounts/101-004-1/pricing") and params == {"instruments": "EUR_USD"}
    assert headers["Authorization"] == "Bearer SECRET"


@pytest.mark.parametrize("payload", [{"prices": []}, {"prices": [{"time": "2024-01-02T10:00:00Z",
    "bids": [{"price": "1.2"}], "asks": [{"price": "1.1"}]}]}, {}])
def test_bad_price_payload_rejected(payload):
    with pytest.raises(OandaError):
        mk(R(200, payload))[0].current_price("EURUSD")


def test_errors_do_not_leak_token():
    import requests
    with pytest.raises(OandaError) as e:
        mk(R(401, {}))[0].current_price("EURUSD")
    assert "SECRET" not in str(e.value)
    with pytest.raises(OandaError) as e:
        mk(requests.ConnectionError("SECRET"))[0].current_price("EURUSD")
    assert "SECRET" not in str(e.value)


def test_candles_complete_only_with_spread():
    j = {"candles": [
        {"complete": True, "time": "2024-01-02T10:00:00Z", "volume": 120,
         "bid": {"o": "1.1000", "h": "1.1010", "l": "1.0995", "c": "1.1005"},
         "ask": {"o": "1.1001", "h": "1.1011", "l": "1.0996", "c": "1.1006"}},
        {"complete": False, "time": "2024-01-02T10:15:00Z", "volume": 3,
         "bid": {"o": "1", "h": "1", "l": "1", "c": "1"}, "ask": {"o": "1", "h": "1", "l": "1", "c": "1"}}]}
    c, s = mk(R(200, j))
    df = c.candles("EURUSD", "M15", 2)
    assert len(df) == 1 and df.attrs["source"] == "live"
    assert df["spread"].iloc[0] == pytest.approx(0.0001)
    assert s.calls[0][1]["price"] == "BA"


def test_client_has_no_order_methods():
    names = {n.lower() for n in dir(OandaPracticeClient)}
    assert not {n for n in names if any(w in n for w in ("order", "trade", "buy", "sell", "position"))}
