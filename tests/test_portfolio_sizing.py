from datetime import datetime
from decimal import Decimal

from configuration import (
    RankingModeConfig,
    ScanConfig,
)
from data.models import OptionQuote, UnderlyingQuote
from portfolio.sizing import size_ranked_trades
from strategy.models import CandidateTrade, EligibilityStatus, RankedTrade


def _scan_config(
    *,
    account_size: float = 20_000,
    max_positions: int = 3,
    max_per_ticker_exposure: float = 10_000,
) -> ScanConfig:
    return ScanConfig(
        account_size=account_size,
        max_positions=max_positions,
        max_per_ticker_exposure=max_per_ticker_exposure,
        ranking_modes={
            "ultra_safe": RankingModeConfig(name="ultra_safe"),
            "capital_efficient": RankingModeConfig(name="capital_efficient"),
        },
    )


def _ranked_trade(
    *,
    symbol: str,
    rank: int,
    strike: str = "50",
    contracts: int = 1,
    eligibility_status: EligibilityStatus = EligibilityStatus.ELIGIBLE,
) -> RankedTrade:
    underlying = UnderlyingQuote(
        symbol=symbol,
        last_price=Decimal("55"),
    )
    option = OptionQuote(
        symbol=f"{symbol} 2026-05-15 {strike}P",
        underlying_symbol=symbol,
        expiration_date=datetime(2026, 5, 15),
        strike=Decimal(strike),
        option_type="put",
        bid=Decimal("1.00"),
        ask=Decimal("1.10"),
    )
    candidate = CandidateTrade(
        underlying=underlying,
        option=option,
        contracts=contracts,
        cash_required=Decimal(strike) * Decimal("100") * contracts,
        eligibility_status=eligibility_status,
    )
    return RankedTrade(
        candidate=candidate,
        rank=rank,
        score=Decimal("90"),
        ranking_mode="ultra_safe",
        ranking_mode_used="ultra_safe",
        pop_score=Decimal("90"),
        return_score=Decimal("90"),
        liquidity_score=Decimal("90"),
        premium_score=Decimal("90"),
        final_score=Decimal("90"),
        eligibility_status=eligibility_status,
    )


def test_position_sizing_skips_trades_that_overflow_account_capital() -> None:
    result = size_ranked_trades(
        [
            _ranked_trade(symbol="AAPL", rank=1, strike="50"),
            _ranked_trade(symbol="MSFT", rank=2, strike="50"),
            _ranked_trade(symbol="GOOG", rank=3, strike="50"),
        ],
        _scan_config(account_size=10_000, max_positions=3, max_per_ticker_exposure=10_000),
    )

    assert [decision.suggested_contracts for decision in result.decisions] == [1, 1, 0]
    assert result.decisions[2].skip_reason == "constraints_allow_zero_contracts"
    assert result.total_allocated == Decimal("10000")


def test_position_sizing_enforces_ticker_concentration() -> None:
    result = size_ranked_trades(
        [
            _ranked_trade(symbol="AAPL", rank=1, strike="50"),
            _ranked_trade(symbol="AAPL", rank=2, strike="50"),
        ],
        _scan_config(account_size=20_000, max_positions=3, max_per_ticker_exposure=5_000),
    )

    assert result.decisions[0].suggested_contracts == 1
    assert result.decisions[1].max_allowed_contracts_by_ticker == 0
    assert result.decisions[1].suggested_contracts == 0
    assert result.decisions[1].skip_reason == "constraints_allow_zero_contracts"
    assert result.total_allocated == Decimal("5000")


def test_position_sizing_enforces_max_positions() -> None:
    result = size_ranked_trades(
        [
            _ranked_trade(symbol="AAPL", rank=1, strike="50"),
            _ranked_trade(symbol="MSFT", rank=2, strike="50"),
            _ranked_trade(symbol="GOOG", rank=3, strike="50"),
        ],
        _scan_config(account_size=20_000, max_positions=2, max_per_ticker_exposure=10_000),
    )

    assert [decision.suggested_contracts for decision in result.decisions] == [1, 1, 0]
    assert result.decisions[2].skip_reason == "max_positions_reached"
    assert result.positions_allocated == 2


def test_position_sizing_handles_zero_contract_cases() -> None:
    result = size_ranked_trades(
        [
            _ranked_trade(symbol="AAPL", rank=1, strike="100"),
            _ranked_trade(
                symbol="MSFT",
                rank=2,
                strike="50",
                eligibility_status=EligibilityStatus.REJECTED,
            ),
        ],
        _scan_config(account_size=5_000, max_positions=3, max_per_ticker_exposure=10_000),
    )

    assert result.decisions[0].collateral_per_contract == Decimal("10000")
    assert result.decisions[0].suggested_contracts == 0
    assert result.decisions[0].capital_required == Decimal("0")
    assert result.decisions[0].skip_reason == "constraints_allow_zero_contracts"
    assert result.decisions[1].suggested_contracts == 0
    assert result.decisions[1].skip_reason == "rejected_trade"
