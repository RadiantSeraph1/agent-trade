"""FX conventions: pip size, quote->account conversion, notional."""

from __future__ import annotations


class UnsupportedPair(ValueError):
    pass


def split_symbol(symbol: str) -> tuple[str, str]:
    s = symbol.upper().replace("/", "")
    if len(s) != 6 or not s.isalpha():
        raise UnsupportedPair(f"unrecognised symbol {symbol!r}")
    return s[:3], s[3:]


def pip_size(symbol: str) -> float:
    return 0.01 if split_symbol(symbol)[1] == "JPY" else 0.0001


def quote_to_account(symbol: str, price: float, account_ccy: str = "USD") -> float:
    """Multiply a quote-currency amount by this to get account currency.

    Only pairs containing the account currency are supported; crosses need a
    third rate and raise UnsupportedPair (callers must reject, never guess).
    """
    base, quote = split_symbol(symbol)
    if quote == account_ccy:
        return 1.0
    if base == account_ccy:
        return 1.0 / price
    raise UnsupportedPair(f"{symbol} cannot be converted to {account_ccy} without a cross rate")


def notional_account(symbol: str, units: float, price: float, account_ccy: str = "USD") -> float:
    base, quote = split_symbol(symbol)
    if base == account_ccy:
        return units
    return units * price * quote_to_account(symbol, price, account_ccy)


def currency_exposure(symbol: str, signed_units: float, price: float) -> dict[str, float]:
    """Signed exposure per currency in units of that currency."""
    base, quote = split_symbol(symbol)
    return {base: signed_units, quote: -signed_units * price}
