from __future__ import annotations

from datetime import date
from decimal import Decimal

from broker.base import Broker
from broker.contracts import OptionChainRequest, same_week_friday
from configuration import ScanConfig
from data.models import OptionQuote, UnderlyingQuote


def fetch_same_week_option_chains(
    broker: Broker,
    symbols: list[str],
    scan_config: ScanConfig,
    as_of: date | None = None,
) -> dict[str, list[OptionQuote]]:
    """Fetch same-week Friday option chains for each symbol."""
    return fetch_option_chains_for_expiry(
        broker=broker,
        symbols=symbols,
        scan_config=scan_config,
        expiration_date=same_week_friday(as_of),
        as_of=as_of,
    )


def fetch_option_chains_for_expiry(
    broker: Broker,
    symbols: list[str],
    scan_config: ScanConfig,
    expiration_date: date,
    as_of: date | None = None,
    underlying_quotes: dict[str, UnderlyingQuote] | None = None,
) -> dict[str, list[OptionQuote]]:
    """Fetch option chains for a specific expiration date.

    Pass ``underlying_quotes`` (already fetched by the scanner) to let broker
    implementations skip a redundant spot-price round-trip for strike filtering.
    """
    requests = [
        OptionChainRequest(
            underlying_symbol=symbol,
            option_right=scan_config.option_type,
            min_strike=_to_decimal(scan_config.default_filters.min_underlying_price),
            max_strike=_max_strike_for_cash_secured_put(scan_config),
            expiration_date=expiration_date,
            as_of=as_of,
        )
        for symbol in symbols
    ]

    spots: dict[str, Decimal] | None = None
    if underlying_quotes:
        spots = {
            symbol.upper(): quote.last_price
            for symbol, quote in underlying_quotes.items()
        }

    chains = broker.fetch_option_chains(requests, spots)

    # Ensure results are filtered to the exact expiration date.
    return {
        symbol: [
            option
            for option in chain
            if option.expiration_date.date() == expiration_date
        ]
        for symbol, chain in chains.items()
    }


def _to_decimal(value: float | int | None) -> Decimal | None:
    if value is None:
        return None

    return Decimal(str(value))


def _max_strike_for_cash_secured_put(scan_config: ScanConfig) -> Decimal | None:
    if scan_config.option_type != "put":
        return None

    return Decimal(str(scan_config.max_per_ticker_exposure)) / Decimal("100")
