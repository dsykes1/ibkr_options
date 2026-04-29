from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal

from broker.contracts import OptionChainRequest
from data.models import OptionQuote, UnderlyingQuote
from portfolio.models import PortfolioSnapshot


class Broker(ABC):
    """Abstract broker interface used by scanners before real IBKR integration."""

    @abstractmethod
    def connect(self) -> None:
        """Open a broker session or mark the broker as connected."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the broker session."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return whether the broker is ready for data requests."""

    @abstractmethod
    def fetch_underlying_quotes(self, symbols: list[str]) -> list[UnderlyingQuote]:
        """Return latest underlying quotes for requested symbols."""

    @abstractmethod
    def fetch_portfolio_snapshot(self) -> PortfolioSnapshot:
        """Return account value and free cash available for cash-secured puts."""

    @abstractmethod
    def fetch_option_chain(self, request: OptionChainRequest) -> list[OptionQuote]:
        """Return option chain entries for a single underlying request."""

    def fetch_option_chains(
        self,
        requests: list[OptionChainRequest],
        spots: dict[str, Decimal] | None = None,
    ) -> dict[str, list[OptionQuote]]:
        """Bulk fetch option chains for multiple underlyings.

        Default implementation is a serial loop over fetch_option_chain.
        Override (e.g. in IbkrClient) to parallelize setup round-trips and
        run a single combined market-data batch across all symbols.
        The optional ``spots`` mapping (symbol → last price) is forwarded to
        broker implementations that can use it to skip a redundant quote fetch.
        """
        result: dict[str, list[OptionQuote]] = {}
        for request in requests:
            result[request.underlying_symbol.upper()] = self.fetch_option_chain(request)
        return result

    @abstractmethod
    def filter_same_week_friday_expiry(
        self,
        options: list[OptionQuote],
        as_of: date | None = None,
    ) -> list[OptionQuote]:
        """Return only contracts expiring on the same-week Friday."""
