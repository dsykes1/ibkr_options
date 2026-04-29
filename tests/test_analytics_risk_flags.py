from analytics.risk_flags import identify_risk_flags
from strategy.models import RiskFlag


def test_identify_risk_flags_returns_all_configured_flags() -> None:
    flags = identify_risk_flags(
        symbol="TQQQ",
        liquidity_score=25,
        spread_pct=30,
        underlying_price=5,
        implied_volatility=1.2,
        ticker_exposure=12_000,
        max_per_ticker_exposure=10_000,
    )

    assert flags == [
        RiskFlag.LOW_LIQUIDITY,
        RiskFlag.WIDE_SPREAD,
        RiskFlag.LOW_PRICE_STOCK,
        RiskFlag.LEVERAGED_ETF,
        RiskFlag.HIGH_IV,
        RiskFlag.CONCENTRATION_RISK,
    ]


def test_identify_risk_flags_returns_empty_list_for_clean_inputs() -> None:
    flags = identify_risk_flags(
        symbol="AAPL",
        liquidity_score=90,
        spread_pct=5,
        underlying_price=175,
        implied_volatility=0.3,
        ticker_exposure=5_000,
        max_per_ticker_exposure=10_000,
    )

    assert flags == []


def test_identify_risk_flags_handles_missing_inputs_conservatively() -> None:
    flags = identify_risk_flags(
        symbol="MSFT",
        liquidity_score=None,
        spread_pct=None,
        underlying_price=None,
        implied_volatility=None,
        ticker_exposure=None,
        max_per_ticker_exposure=None,
    )

    assert flags == [
        RiskFlag.LOW_LIQUIDITY,
        RiskFlag.WIDE_SPREAD,
        RiskFlag.LOW_PRICE_STOCK,
    ]
