from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class UnderlyingQuote(BaseModel):
    symbol: str = Field(min_length=1)
    last_price: Decimal = Field(gt=0)
    bid: Decimal | None = Field(default=None, ge=0)
    ask: Decimal | None = Field(default=None, ge=0)
    volume: int | None = Field(default=None, ge=0)
    average_volume: int | None = Field(default=None, ge=0)
    market_timestamp: datetime | None = None
    market_data_type: str | None = None
    data_quality_warnings: list[str] = Field(default_factory=list)


class OptionQuote(BaseModel):
    symbol: str = Field(min_length=1)
    underlying_symbol: str = Field(min_length=1)
    expiration_date: datetime
    strike: Decimal = Field(gt=0)
    option_type: str = Field(pattern="^(put|call)$")
    bid: Decimal = Field(ge=0)
    ask: Decimal = Field(ge=0)
    last_price: Decimal | None = Field(default=None, ge=0)
    volume: int | None = Field(default=None, ge=0)
    open_interest: int | None = Field(default=None, ge=0)
    implied_volatility: Decimal | None = Field(default=None, ge=0)
    delta: Decimal | None = None
    market_timestamp: datetime | None = None
    market_data_type: str | None = None
    data_quality_warnings: list[str] = Field(default_factory=list)
