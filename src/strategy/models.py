from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field

from data.models import OptionQuote, UnderlyingQuote


class RiskFlag(StrEnum):
    EARNINGS_NEAR_EXPIRATION = "earnings_near_expiration"
    KNOWN_EVENT_NEAR_EXPIRATION = "known_event_near_expiration"
    LOW_LIQUIDITY = "low_liquidity"
    WIDE_SPREAD = "wide_spread"
    DATA_QUALITY_WARNING = "data_quality_warning"
    LOW_PRICE_STOCK = "low_price_stock"
    LEVERAGED_ETF = "leveraged_etf"
    HIGH_IV = "high_iv"
    CONCENTRATION_RISK = "concentration_risk"
    HIGH_POSITION_CONCENTRATION = "high_position_concentration"
    INSUFFICIENT_CASH = "insufficient_cash"
    BELOW_MINIMUM_PREMIUM = "below_minimum_premium"
    ABOVE_MAX_DELTA = "above_max_delta"
    BELOW_TARGET_RETURN = "below_target_return"


class EligibilityStatus(StrEnum):
    ELIGIBLE = "eligible"
    ELIGIBLE_WITH_FLAGS = "eligible_with_flags"
    REJECTED = "rejected"
    INELIGIBLE = "ineligible"
    REVIEW = "review"


class CandidateTrade(BaseModel):
    underlying: UnderlyingQuote
    option: OptionQuote
    contracts: int = Field(default=1, ge=1)
    cash_required: Decimal = Field(ge=0)
    estimated_premium: Decimal | None = Field(default=None, ge=0)
    eligibility_status: EligibilityStatus = EligibilityStatus.REVIEW
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RankedTrade(BaseModel):
    candidate: CandidateTrade
    rank: int = Field(ge=1)
    score: Decimal | None = None
    ranking_mode: str = Field(min_length=1)
    ranking_mode_used: str = Field(min_length=1)
    pop_score: Decimal = Field(ge=0, le=100)
    return_score: Decimal = Field(ge=0, le=100)
    liquidity_score: Decimal = Field(ge=0, le=100)
    premium_score: Decimal = Field(ge=0, le=100)
    final_score: Decimal = Field(ge=0, le=100)
    eligibility_status: EligibilityStatus
    rationale: list[str] = Field(default_factory=list)
