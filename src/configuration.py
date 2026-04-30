from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


RankingModeName = Literal["ultra_safe", "capital_efficient"]
MarketDataTypeName = Literal["live", "frozen", "delayed", "delayed_frozen"]


class PortfolioTargetsConfig(BaseModel):
    weekly_return_target_pct: float = Field(default=0.5, gt=0)
    min_pop: float = Field(default=0.95, ge=0, le=1)
    allow_partial_target: bool = True
    reject_if_target_requires_low_quality_trades: bool = True


class UniverseDiscoveryConfig(BaseModel):
    enabled: bool = True
    use_configured_universe_first: bool = True
    include_sp500: bool = False
    include_nasdaq100: bool = False
    include_etfs: bool = True
    exclude_leveraged_etfs: bool = True
    min_underlying_volume: int | None = Field(default=None, ge=0)
    max_symbols: int | None = Field(default=None, gt=0)


class AppConfig(BaseModel):
    name: str = "ibkr-options"
    environment: str = "development"
    log_level: str = "INFO"


class IbkrConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=7497, ge=1, le=65535)
    client_id: int = Field(default=1, ge=0)


class MarketDataConfig(BaseModel):
    default_type: MarketDataTypeName = "live"
    allow_delayed_fallback: bool = False
    reject_if_delayed: bool = True
    require_bid_ask: bool = True
    require_greeks: bool = True
    require_iv: bool = True
    require_open_interest: bool = True
    require_option_volume: bool = True


class DefaultFiltersConfig(BaseModel):
    min_underlying_price: float | None = Field(default=None, gt=0)
    max_underlying_price: float | None = Field(default=None, gt=0)
    min_option_volume: int = Field(default=0, ge=0)
    min_open_interest: int = Field(default=0, ge=0)
    max_bid_ask_spread_pct: float | None = Field(default=None, ge=0)
    min_days_to_expiration: int = Field(default=0, ge=0)
    max_days_to_expiration: int = Field(default=7, ge=0)
    exclude_earnings_within_days: int | None = Field(default=None, ge=0)


class RankingModeConfig(BaseModel):
    name: RankingModeName
    enabled: bool = True
    description: str = ""
    min_premium: float | None = Field(default=None, ge=0)
    min_annualized_return_pct: float | None = Field(default=None, ge=0)
    max_delta: float | None = None
    max_contracts_per_trade: int = Field(default=1, ge=1)
    open_interest_contract_limit_pct: float | None = Field(
        default=None,
        gt=0,
        le=100,
    )
    prefer_lower_assignment_risk: bool = True


class ScanConfig(BaseModel):
    account_size: float = Field(gt=0)
    max_positions: int = Field(gt=0)
    max_per_ticker_exposure: float = Field(gt=0)
    universe: list[str] = Field(default_factory=lambda: ["AAPL", "MSFT", "SPY", "TQQQ"])
    option_type: Literal["put"] = "put"
    expiration_scope: Literal["weekly"] = "weekly"
    currency: str = "USD"
    default_filters: DefaultFiltersConfig = Field(default_factory=DefaultFiltersConfig)
    ranking_mode: RankingModeName = "capital_efficient"
    ranking_modes: dict[RankingModeName, RankingModeConfig]
    portfolio_targets: PortfolioTargetsConfig = Field(default_factory=PortfolioTargetsConfig)
    universe_discovery: UniverseDiscoveryConfig = Field(default_factory=UniverseDiscoveryConfig)


class Settings(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    ibkr: IbkrConfig = Field(default_factory=IbkrConfig)
    market_data: MarketDataConfig = Field(default_factory=MarketDataConfig)
    scanner: ScanConfig


def load_settings(settings_file: Path = Path("config/settings.yaml")) -> Settings:
    with settings_file.open("r", encoding="utf-8") as file:
        raw_settings = yaml.safe_load(file) or {}

    return Settings.model_validate(raw_settings)
