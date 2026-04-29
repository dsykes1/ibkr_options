from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from broker.contracts import OptionChainRequest
from data.models import OptionQuote, UnderlyingQuote


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
    def fetch_option_chain(self, request: OptionChainRequest) -> list[OptionQuote]:
        """Return option chain entries for a single underlying request."""

    @abstractmethod
    def filter_same_week_friday_expiry(
        self,
        options: list[OptionQuote],
        as_of: date | None = None,
    ) -> list[OptionQuote]:
        """Return only contracts expiring on the same-week Friday."""
