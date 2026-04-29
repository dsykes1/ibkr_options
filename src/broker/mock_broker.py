from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from broker.base import Broker
from broker.contracts import (
    BrokerConnection,
    OptionChainRequest,
    expiry_datetime,
    same_week_friday,
)
from data.models import OptionQuote, UnderlyingQuote


MOCK_AS_OF = date(2026, 4, 29)


MOCK_UNDERLYING_QUOTES: dict[str, UnderlyingQuote] = {
    "AAPL": UnderlyingQuote(
        symbol="AAPL",
        last_price=Decimal("192.40"),
        bid=Decimal("192.35"),
        ask=Decimal("192.45"),
        volume=48_500_000,
        average_volume=56_000_000,
        market_timestamp=datetime(2026, 4, 29, 15, 45),
    ),
    "MSFT": UnderlyingQuote(
        symbol="MSFT",
        last_price=Decimal("418.75"),
        bid=Decimal("418.60"),
        ask=Decimal("418.90"),
        volume=21_200_000,
        average_volume=24_000_000,
        market_timestamp=datetime(2026, 4, 29, 15, 45),
    ),
    "SPY": UnderlyingQuote(
        symbol="SPY",
        last_price=Decimal("525.30"),
        bid=Decimal("525.28"),
        ask=Decimal("525.32"),
        volume=72_000_000,
        average_volume=68_000_000,
        market_timestamp=datetime(2026, 4, 29, 15, 45),
    ),
    "TQQQ": UnderlyingQuote(
        symbol="TQQQ",
        last_price=Decimal("67.85"),
        bid=Decimal("67.83"),
        ask=Decimal("67.87"),
        volume=44_000_000,
        average_volume=51_000_000,
        market_timestamp=datetime(2026, 4, 29, 15, 45),
    ),
}


def _option(
    *,
    underlying_symbol: str,
    expiry: date,
    strike: str,
    option_type: str,
    bid: str,
    ask: str,
    last_price: str,
    delta: str,
    implied_volatility: str,
    open_interest: int,
    volume: int,
) -> OptionQuote:
    return OptionQuote(
        symbol=f"{underlying_symbol} {expiry.isoformat()} {strike}{option_type[0].upper()}",
        underlying_symbol=underlying_symbol,
        expiration_date=expiry_datetime(expiry),
        strike=Decimal(strike),
        option_type=option_type,
        bid=Decimal(bid),
        ask=Decimal(ask),
        last_price=Decimal(last_price),
        delta=Decimal(delta),
        implied_volatility=Decimal(implied_volatility),
        open_interest=open_interest,
        volume=volume,
        market_timestamp=datetime(2026, 4, 29, 15, 45),
    )


THIS_FRIDAY = same_week_friday(MOCK_AS_OF)
NEXT_FRIDAY = THIS_FRIDAY + timedelta(days=7)


MOCK_OPTION_CHAINS: dict[str, list[OptionQuote]] = {
    "AAPL": [
        _option(
            underlying_symbol="AAPL",
            expiry=THIS_FRIDAY,
            strike="185",
            option_type="put",
            bid="0.42",
            ask="0.48",
            last_price="0.45",
            delta="-0.12",
            implied_volatility="0.28",
            open_interest=4_250,
            volume=1_180,
        ),
        _option(
            underlying_symbol="AAPL",
            expiry=THIS_FRIDAY,
            strike="190",
            option_type="put",
            bid="1.35",
            ask="1.44",
            last_price="1.39",
            delta="-0.29",
            implied_volatility="0.31",
            open_interest=6_750,
            volume=2_940,
        ),
        _option(
            underlying_symbol="AAPL",
            expiry=NEXT_FRIDAY,
            strike="185",
            option_type="put",
            bid="0.95",
            ask="1.05",
            last_price="1.00",
            delta="-0.18",
            implied_volatility="0.30",
            open_interest=5_200,
            volume=860,
        ),
    ],
    "MSFT": [
        _option(
            underlying_symbol="MSFT",
            expiry=THIS_FRIDAY,
            strike="405",
            option_type="put",
            bid="1.10",
            ask="1.25",
            last_price="1.18",
            delta="-0.16",
            implied_volatility="0.24",
            open_interest=2_100,
            volume=540,
        ),
        _option(
            underlying_symbol="MSFT",
            expiry=THIS_FRIDAY,
            strike="410",
            option_type="put",
            bid="2.05",
            ask="2.25",
            last_price="2.15",
            delta="-0.27",
            implied_volatility="0.26",
            open_interest=3_850,
            volume=910,
        ),
    ],
    "SPY": [
        _option(
            underlying_symbol="SPY",
            expiry=THIS_FRIDAY,
            strike="515",
            option_type="put",
            bid="1.62",
            ask="1.66",
            last_price="1.64",
            delta="-0.20",
            implied_volatility="0.18",
            open_interest=28_000,
            volume=18_400,
        ),
        _option(
            underlying_symbol="SPY",
            expiry=THIS_FRIDAY,
            strike="520",
            option_type="put",
            bid="2.88",
            ask="2.94",
            last_price="2.91",
            delta="-0.34",
            implied_volatility="0.19",
            open_interest=35_500,
            volume=22_100,
        ),
    ],
    "TQQQ": [
        _option(
            underlying_symbol="TQQQ",
            expiry=THIS_FRIDAY,
            strike="64",
            option_type="put",
            bid="0.36",
            ask="0.43",
            last_price="0.40",
            delta="-0.18",
            implied_volatility="0.78",
            open_interest=8_900,
            volume=3_700,
        ),
        _option(
            underlying_symbol="TQQQ",
            expiry=THIS_FRIDAY,
            strike="66",
            option_type="put",
            bid="0.82",
            ask="0.95",
            last_price="0.88",
            delta="-0.33",
            implied_volatility="0.82",
            open_interest=11_200,
            volume=5_050,
        ),
    ],
}


class MockBroker(Broker):
    """Deterministic broker implementation for scanner tests and local demos."""

    def __init__(
        self,
        underlying_quotes: dict[str, UnderlyingQuote] | None = None,
        option_chains: dict[str, list[OptionQuote]] | None = None,
    ) -> None:
        self._connection = BrokerConnection(host="mock", port=0, client_id=0)
        self._underlying_quotes = underlying_quotes or MOCK_UNDERLYING_QUOTES
        self._option_chains = option_chains or MOCK_OPTION_CHAINS

    def connect(self) -> None:
        self._connection = BrokerConnection(
            host=self._connection.host,
            port=self._connection.port,
            client_id=self._connection.client_id,
            connected=True,
        )

    def disconnect(self) -> None:
        self._connection = BrokerConnection(
            host=self._connection.host,
            port=self._connection.port,
            client_id=self._connection.client_id,
            connected=False,
        )

    @property
    def is_connected(self) -> bool:
        return self._connection.connected

    def fetch_underlying_quotes(self, symbols: list[str]) -> list[UnderlyingQuote]:
        self._ensure_connected()
        return [
            self._underlying_quotes[symbol.upper()]
            for symbol in symbols
            if symbol.upper() in self._underlying_quotes
        ]

    def fetch_option_chain(self, request: OptionChainRequest) -> list[OptionQuote]:
        self._ensure_connected()
        chain = self._option_chains.get(request.underlying_symbol.upper(), [])
        filtered_chain = [
            option
            for option in chain
            if option.option_type == request.option_right
            and _strike_in_range(option, request)
        ]

        return filtered_chain

    def filter_same_week_friday_expiry(
        self,
        options: list[OptionQuote],
        as_of: date | None = None,
    ) -> list[OptionQuote]:
        target_expiry = same_week_friday(as_of or MOCK_AS_OF)
        return [
            option
            for option in options
            if option.expiration_date.date() == target_expiry
        ]

    def _ensure_connected(self) -> None:
        if not self.is_connected:
            raise RuntimeError("MockBroker is not connected.")


def _strike_in_range(option: OptionQuote, request: OptionChainRequest) -> bool:
    if request.min_strike is not None and option.strike < request.min_strike:
        return False

    if request.max_strike is not None and option.strike > request.max_strike:
        return False

    return True
