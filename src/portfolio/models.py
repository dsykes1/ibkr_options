from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class PortfolioSnapshot(BaseModel):
    account_id: str | None = None
    net_liquidation: Decimal = Field(ge=0)
    free_cash: Decimal = Field(ge=0)
    currency: str = "USD"
    data_source: str = "unknown"
    warnings: list[str] = Field(default_factory=list)
