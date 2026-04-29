from __future__ import annotations

from datetime import date
from decimal import Decimal

from broker.base import Broker
from broker.contracts import OptionChainRequest
from configuration import ScanConfig
from data.models import OptionQuote


def fetch_same_week_option_chains(
    broker: Broker,
    symbols: list[str],
    scan_config: ScanConfig,
    as_of: date | None = None,
) -> dict[str, list[OptionQuote]]:
    """Fetch same-week Friday option chains for each symbol."""
    chains: dict[str, list[OptionQuote]] = {}
    for symbol in symbols:
        request = OptionChainRequest(
            underlying_symbol=symbol,
            option_right=scan_config.option_type,
            min_strike=_to_decimal(scan_config.default_filters.min_underlying_price),
            max_strike=None,
            as_of=as_of,
        )
        chain = broker.fetch_option_chain(request)
        chains[symbol] = broker.filter_same_week_friday_expiry(chain, as_of=as_of)

    return chains


def _to_decimal(value: float | int | None) -> Decimal | None:
    if value is None:
        return None

    return Decimal(str(value))
