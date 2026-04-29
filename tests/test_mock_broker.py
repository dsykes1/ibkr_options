from datetime import date
from decimal import Decimal

import pytest

from broker.contracts import OptionChainRequest, same_week_friday
from broker.mock_broker import MOCK_AS_OF, MOCK_OPTION_CHAINS, MOCK_UNDERLYING_QUOTES, MockBroker


def test_mock_broker_connects_and_disconnects() -> None:
    broker = MockBroker()

    assert broker.is_connected is False

    broker.connect()
    assert broker.is_connected is True

    broker.disconnect()
    assert broker.is_connected is False


def test_mock_broker_requires_connection_before_fetching_data() -> None:
    broker = MockBroker()

    with pytest.raises(RuntimeError):
        broker.fetch_underlying_quotes(["AAPL"])


def test_mock_broker_returns_realistic_underlying_quotes_for_stocks_and_etfs() -> None:
    broker = MockBroker()
    broker.connect()

    quotes = broker.fetch_underlying_quotes(["AAPL", "SPY", "UNKNOWN"])

    assert [quote.symbol for quote in quotes] == ["AAPL", "SPY"]
    assert quotes[0].last_price == Decimal("192.40")
    assert quotes[1].volume == 72_000_000


def test_mock_broker_returns_option_chain_entries_with_market_fields() -> None:
    broker = MockBroker()
    broker.connect()

    chain = broker.fetch_option_chain(
        OptionChainRequest(
            underlying_symbol="AAPL",
            option_right="put",
            min_strike=Decimal("185"),
            max_strike=Decimal("190"),
        )
    )

    assert len(chain) == 3
    assert all(option.bid > 0 for option in chain)
    assert all(option.ask >= option.bid for option in chain)
    assert all(option.delta is not None for option in chain)
    assert all(option.implied_volatility is not None for option in chain)
    assert all(option.open_interest is not None for option in chain)
    assert all(option.volume is not None for option in chain)


def test_mock_broker_filters_same_week_friday_expiry() -> None:
    broker = MockBroker()
    broker.connect()
    chain = broker.fetch_option_chain(OptionChainRequest(underlying_symbol="AAPL"))

    filtered = broker.filter_same_week_friday_expiry(chain, as_of=MOCK_AS_OF)

    assert len(filtered) == 2
    assert {option.expiration_date.date() for option in filtered} == {
        date(2026, 5, 1)
    }


def test_same_week_friday_helper_handles_before_and_after_friday() -> None:
    assert same_week_friday(date(2026, 4, 29)) == date(2026, 5, 1)
    assert same_week_friday(date(2026, 5, 2)) == date(2026, 5, 1)


def test_mock_sample_data_contains_stock_etf_and_option_samples() -> None:
    assert {"AAPL", "MSFT", "SPY", "TQQQ"}.issubset(MOCK_UNDERLYING_QUOTES)
    assert all(MOCK_OPTION_CHAINS[symbol] for symbol in ["AAPL", "MSFT", "SPY", "TQQQ"])
