"""Tests for portfolio target-aware position sizing."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from configuration import (
    PortfolioTargetsConfig,
    RankingModeConfig,
    ScanConfig,
)
from data.models import OptionQuote, UnderlyingQuote
from portfolio.models import PortfolioSnapshot
from portfolio.sizing import size_ranked_trades
from strategy.models import CandidateTrade, EligibilityStatus, RankedTrade


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scan_config(
    *,
    account_size: float = 50_000,
    max_positions: int = 10,
    max_per_ticker_exposure: float = 25_000,
    weekly_return_target_pct: float = 0.5,
    min_pop: float = 0.95,
    allow_partial_target: bool = True,
    reject_if_target_requires_low_quality_trades: bool = True,
) -> ScanConfig:
    return ScanConfig(
        account_size=account_size,
        max_positions=max_positions,
        max_per_ticker_exposure=max_per_ticker_exposure,
        ranking_modes={
            "ultra_safe": RankingModeConfig(name="ultra_safe"),
            "capital_efficient": RankingModeConfig(name="capital_efficient"),
        },
        portfolio_targets=PortfolioTargetsConfig(
            weekly_return_target_pct=weekly_return_target_pct,
            min_pop=min_pop,
            allow_partial_target=allow_partial_target,
            reject_if_target_requires_low_quality_trades=reject_if_target_requires_low_quality_trades,
        ),
    )


def _portfolio_snapshot(net_liquidation: float = 50_000, free_cash: float = 50_000) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        net_liquidation=Decimal(str(net_liquidation)),
        free_cash=Decimal(str(free_cash)),
        data_source="test",
    )


def _ranked_trade(
    *,
    symbol: str,
    rank: int,
    strike: str = "50",
    bid: str = "1.00",
    ask: str = "1.10",
    contracts: int = 1,
    eligibility_status: EligibilityStatus = EligibilityStatus.ELIGIBLE,
    modeled_pop: float | None = 0.97,
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
        bid=Decimal(bid),
        ask=Decimal(ask),
    )
    candidate = CandidateTrade(
        underlying=underlying,
        option=option,
        contracts=contracts,
        cash_required=Decimal(strike) * Decimal("100") * contracts,
        eligibility_status=eligibility_status,
        notes=[f"modeled_pop={modeled_pop}"],
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_premium_captured_accumulates_from_allocated_eligible_trades() -> None:
    """Premium captured should equal sum of executable bid premium * 100."""
    config = _scan_config(account_size=20_000, max_positions=3)
    trades = [
        _ranked_trade(symbol="AAPL", rank=1, strike="50", bid="1.00", ask="1.20", modeled_pop=0.97),
        _ranked_trade(symbol="MSFT", rank=2, strike="50", bid="0.80", ask="1.00", modeled_pop=0.96),
    ]
    result = size_ranked_trades(trades, config)

    # Conservative bid-side premium: 1.00*100 + 0.80*100
    expected = Decimal("100") + Decimal("80")
    assert result.premium_captured == expected


def test_target_met_when_enough_premium_captured() -> None:
    """target_met should be True when premium_captured >= target_weekly_premium."""
    # account=100_000, target=0.1% => target=100
    # Each trade: strike=50 => mid=1.05 * 100 = 105
    config = _scan_config(account_size=100_000, max_positions=5, weekly_return_target_pct=0.1)
    snapshot = _portfolio_snapshot(net_liquidation=100_000)
    trades = [
        _ranked_trade(symbol="AAPL", rank=1, strike="50", bid="1.00", ask="1.10", modeled_pop=0.97),
    ]
    result = size_ranked_trades(trades, config, portfolio_snapshot=snapshot)

    assert result.target_weekly_premium == Decimal("100")
    assert result.premium_captured >= result.target_weekly_premium
    assert result.target_met is True
    assert result.target_achieved_pct >= 100.0


def test_target_not_met_returns_partial_when_allow_partial_target_true() -> None:
    """When target is not met and allow_partial_target=True, result is returned as-is."""
    # Very high target (10%) won't be met with a tiny bid
    config = _scan_config(
        account_size=50_000,
        weekly_return_target_pct=10.0,
        allow_partial_target=True,
        reject_if_target_requires_low_quality_trades=False,
    )
    snapshot = _portfolio_snapshot(net_liquidation=50_000)
    trades = [
        _ranked_trade(symbol="AAPL", rank=1, strike="50", bid="0.10", ask="0.12", modeled_pop=0.97),
    ]
    result = size_ranked_trades(trades, config, portfolio_snapshot=snapshot)

    assert result.target_met is False
    assert result.target_achieved_pct < 100.0
    # Partial result: still has one allocated position
    assert result.positions_allocated >= 1


def test_low_quality_trades_skipped_when_reject_flag_enabled() -> None:
    """Trades with POP below target min_pop should be skipped when reject flag is True."""
    config = _scan_config(
        account_size=20_000,
        max_positions=5,
        min_pop=0.95,
        reject_if_target_requires_low_quality_trades=True,
    )
    # pop=0.90 is below min_pop=0.95
    low_quality = _ranked_trade(symbol="AAPL", rank=1, strike="50", modeled_pop=0.90)
    result = size_ranked_trades([low_quality], config)

    assert result.decisions[0].suggested_contracts == 0
    assert result.decisions[0].skip_reason == "below_target_quality_threshold"
    assert result.decisions[0].target_eligible is False


def test_low_quality_trades_allocated_when_reject_flag_disabled() -> None:
    """Trades with POP below target min_pop should still be allocated when reject flag is False."""
    config = _scan_config(
        account_size=20_000,
        max_positions=5,
        min_pop=0.95,
        reject_if_target_requires_low_quality_trades=False,
    )
    low_quality = _ranked_trade(symbol="AAPL", rank=1, strike="50", modeled_pop=0.90)
    result = size_ranked_trades([low_quality], config)

    assert result.decisions[0].suggested_contracts == 1
    assert result.decisions[0].target_eligible is False
    assert result.decisions[0].target_skip_reason == "pop_below_target_min_pop"
    # Low-quality trade doesn't count toward premium_captured
    assert result.premium_captured == Decimal("0")


def test_target_eligible_true_for_high_pop_trade() -> None:
    """Trades passing min_pop threshold are marked target_eligible=True."""
    config = _scan_config(min_pop=0.95)
    trade = _ranked_trade(symbol="SPY", rank=1, strike="50", modeled_pop=0.97)
    result = size_ranked_trades([trade], config)

    assert result.decisions[0].target_eligible is True
    assert result.decisions[0].target_skip_reason is None


def test_trade_below_weekly_premium_vs_risk_target_is_skipped() -> None:
    """Trades below weekly target premium % of strike should not be recommended."""
    config = _scan_config(
        account_size=20_000,
        weekly_return_target_pct=0.5,
        reject_if_target_requires_low_quality_trades=True,
    )
    # mid premium = 0.20, strike = 50 -> 0.4% (below 0.5% target)
    low_premium_trade = _ranked_trade(
        symbol="AAPL",
        rank=1,
        strike="50",
        bid="0.18",
        ask="0.22",
        modeled_pop=0.98,
    )

    result = size_ranked_trades([low_premium_trade], config)

    assert result.decisions[0].suggested_contracts == 0
    assert result.decisions[0].target_eligible is False
    assert result.decisions[0].target_skip_reason == "premium_below_weekly_target_pct"


def test_unused_cash_reflects_unallocated_capital() -> None:
    """unused_cash = account_size - total_allocated."""
    config = _scan_config(account_size=20_000, max_positions=1)
    trade = _ranked_trade(symbol="AAPL", rank=1, strike="50", modeled_pop=0.97)
    result = size_ranked_trades([trade], config)

    expected_unused = Decimal("20000") - result.total_allocated
    assert result.unused_cash == expected_unused


def test_target_achieved_pct_is_zero_when_no_premium_captured() -> None:
    """If no trades are allocated, target_achieved_pct should be 0."""
    config = _scan_config(account_size=1_000, max_positions=1)
    # Rejected trade — won't be allocated
    trade = _ranked_trade(
        symbol="AAPL",
        rank=1,
        strike="50",
        modeled_pop=0.97,
        eligibility_status=EligibilityStatus.REJECTED,
    )
    result = size_ranked_trades([trade], config)

    assert result.premium_captured == Decimal("0")
    assert result.target_achieved_pct == 0.0
    assert result.target_met is False


def test_concentration_controls_preserved_with_target_config() -> None:
    """max_per_ticker_exposure should still prevent over-concentration even with targets."""
    config = _scan_config(
        account_size=20_000,
        max_positions=5,
        max_per_ticker_exposure=5_000,
    )
    # Two AAPL trades; strike=50 => collateral=5000 each; only first fits exposure
    trades = [
        _ranked_trade(symbol="AAPL", rank=1, strike="50", modeled_pop=0.97),
        _ranked_trade(symbol="AAPL", rank=2, strike="50", modeled_pop=0.97),
    ]
    result = size_ranked_trades(trades, config)

    assert result.decisions[0].suggested_contracts == 1
    assert result.decisions[1].suggested_contracts == 0
    assert result.decisions[1].max_allowed_contracts_by_ticker == 0
