from __future__ import annotations

from datetime import date
from decimal import Decimal

from broker.base import Broker
from broker.contracts import OptionChainRequest, same_week_friday
from configuration import ScanConfig
from data.models import OptionQuote


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
) -> dict[str, list[OptionQuote]]:
    """Fetch option chains for a specific expiration date."""
    chains: dict[str, list[OptionQuote]] = {}
    for symbol in symbols:
        request = OptionChainRequest(
            underlying_symbol=symbol,
            option_right=scan_config.option_type,
            min_strike=_to_decimal(scan_config.default_filters.min_underlying_price),
            max_strike=None,
            expiration_date=expiration_date,
            as_of=as_of,
        )
        chain = broker.fetch_option_chain(request)
        chains[symbol] = [
            option
            for option in chain
            if option.expiration_date.date() == expiration_date
        ]

    return chains


def _to_decimal(value: float | int | None) -> Decimal | None:
    if value is None:
        return None

    return Decimal(str(value))
