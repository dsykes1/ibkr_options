from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal


OptionRight = Literal["put", "call"]


@dataclass(frozen=True)
class BrokerConnection:
    host: str
    port: int
    client_id: int
    connected: bool = False


@dataclass(frozen=True)
class OptionChainRequest:
    underlying_symbol: str
    option_right: OptionRight = "put"
    min_strike: Decimal | None = None
    max_strike: Decimal | None = None
    expiration_date: date | None = None
    as_of: date | None = None


def same_week_friday(as_of: date | None = None) -> date:
    """Return the Friday in the same Monday-Sunday calendar week as `as_of`."""
    current_date = as_of or date.today()
    days_until_friday = 4 - current_date.weekday()
    return current_date + timedelta(days=days_until_friday)


def expiry_datetime(expiry_date: date) -> datetime:
    """Return a normalized market-close-ish datetime for an option expiry date."""
    return datetime.combine(expiry_date, time(hour=16, minute=0))
