from datetime import datetime
from decimal import Decimal

from data.models import OptionQuote, UnderlyingQuote
from strategy.models import CandidateTrade, EligibilityStatus, RiskFlag
from strategy.ranker import RankerInput, classify_eligibility, rank_candidate, rank_candidates


def _candidate(
    *,
    symbol: str = "AAPL",
    risk_flags: list[RiskFlag] | None = None,
) -> CandidateTrade:
    underlying = UnderlyingQuote(
        symbol=symbol,
        last_price=Decimal("100"),
        bid=Decimal("99.95"),
        ask=Decimal("100.05"),
    )
    option = OptionQuote(
        symbol=f"{symbol} 2026-05-15 95P",
        underlying_symbol=symbol,
        expiration_date=datetime(2026, 5, 15),
        strike=Decimal("95"),
        option_type="put",
        bid=Decimal("1.00"),
        ask=Decimal("1.10"),
    )
    return CandidateTrade(
        underlying=underlying,
        option=option,
        cash_required=Decimal("9500"),
        estimated_premium=Decimal("105"),
        risk_flags=risk_flags or [],
    )


def test_ultra_safe_ranking_uses_required_weights() -> None:
    ranked = rank_candidate(
        RankerInput(
            candidate=_candidate(),
            probability_of_profit=0.98,
            annualized_return=0.09,
            liquidity_score=80,
            premium=0.50,
        ),
        mode="ultra_safe",
    )

    assert ranked.ranking_mode_used == "ultra_safe"
    assert ranked.pop_score == Decimal("100")
    assert ranked.return_score == Decimal("50.0")
    assert ranked.liquidity_score == Decimal("80.0")
    assert ranked.premium_score == Decimal("50.0")
    assert ranked.final_score == Decimal("81.0")
    assert ranked.eligibility_status == EligibilityStatus.ELIGIBLE


def test_capital_efficient_ranking_uses_required_weights() -> None:
    ranked = rank_candidate(
        RankerInput(
            candidate=_candidate(),
            probability_of_profit=0.94,
            annualized_return=0.15,
            liquidity_score=80,
            premium=0.75,
        ),
        mode="capital_efficient",
    )

    assert ranked.ranking_mode_used == "capital_efficient"
    assert ranked.pop_score == Decimal("100")
    assert ranked.return_score == Decimal("50.0")
    assert ranked.liquidity_score == Decimal("80.0")
    assert ranked.premium_score == Decimal("50.0")
    assert ranked.final_score == Decimal("71.0")
    assert ranked.eligibility_status == EligibilityStatus.ELIGIBLE


def test_hard_pop_threshold_rejects_by_mode() -> None:
    ultra_safe = rank_candidate(
        RankerInput(
            candidate=_candidate(),
            probability_of_profit=0.94,
            annualized_return=0.30,
            liquidity_score=100,
            premium=2.00,
        ),
        mode="ultra_safe",
    )
    capital_efficient = rank_candidate(
        RankerInput(
            candidate=_candidate(),
            probability_of_profit=0.94,
            annualized_return=0.30,
            liquidity_score=100,
            premium=2.00,
        ),
        mode="capital_efficient",
    )

    assert ultra_safe.eligibility_status == EligibilityStatus.REJECTED
    assert ultra_safe.final_score == Decimal("0")
    assert capital_efficient.eligibility_status == EligibilityStatus.ELIGIBLE
    assert capital_efficient.final_score == Decimal("100")


def test_risk_flags_apply_mode_specific_penalties_and_classification() -> None:
    ultra_safe = rank_candidate(
        RankerInput(
            candidate=_candidate(risk_flags=[RiskFlag.LOW_LIQUIDITY]),
            probability_of_profit=0.98,
            annualized_return=0.18,
            liquidity_score=100,
            premium=1.00,
        ),
        mode="ultra_safe",
    )
    capital_efficient = rank_candidate(
        RankerInput(
            candidate=_candidate(risk_flags=[RiskFlag.LOW_LIQUIDITY]),
            probability_of_profit=0.94,
            annualized_return=0.30,
            liquidity_score=100,
            premium=1.50,
        ),
        mode="capital_efficient",
    )

    assert ultra_safe.eligibility_status == EligibilityStatus.ELIGIBLE_WITH_FLAGS
    assert ultra_safe.final_score == Decimal("80")
    assert capital_efficient.eligibility_status == EligibilityStatus.ELIGIBLE_WITH_FLAGS
    assert capital_efficient.final_score == Decimal("88")


def test_rejection_flags_reject_candidate_after_scoring() -> None:
    ranked = rank_candidate(
        RankerInput(
            candidate=_candidate(risk_flags=[RiskFlag.CONCENTRATION_RISK]),
            probability_of_profit=0.98,
            annualized_return=0.18,
            liquidity_score=100,
            premium=1.00,
        ),
        mode="ultra_safe",
    )

    assert ranked.eligibility_status == EligibilityStatus.REJECTED
    assert ranked.final_score == Decimal("0")


def test_rank_candidates_orders_non_rejected_by_final_score_first() -> None:
    lower_score = RankerInput(
        candidate=_candidate(symbol="LOW"),
        probability_of_profit=0.96,
        annualized_return=0.05,
        liquidity_score=50,
        premium=0.25,
    )
    higher_score = RankerInput(
        candidate=_candidate(symbol="HIGH"),
        probability_of_profit=0.98,
        annualized_return=0.18,
        liquidity_score=100,
        premium=1.00,
    )
    rejected = RankerInput(
        candidate=_candidate(symbol="BAD"),
        probability_of_profit=0.50,
        annualized_return=1.00,
        liquidity_score=100,
        premium=10.00,
    )

    ranked = rank_candidates([lower_score, rejected, higher_score], mode="ultra_safe")

    assert [trade.rank for trade in ranked] == [1, 2, 3]
    assert [trade.candidate.underlying.symbol for trade in ranked] == ["HIGH", "LOW", "BAD"]
    assert ranked[-1].eligibility_status == EligibilityStatus.REJECTED


def test_classify_eligibility_handles_clean_flagged_and_rejected_cases() -> None:
    assert (
        classify_eligibility(
            probability_of_profit=0.98,
            risk_flags=[],
            mode="ultra_safe",
        )
        == EligibilityStatus.ELIGIBLE
    )
    assert (
        classify_eligibility(
            probability_of_profit=0.98,
            risk_flags=[RiskFlag.WIDE_SPREAD],
            mode="ultra_safe",
        )
        == EligibilityStatus.ELIGIBLE_WITH_FLAGS
    )
    assert (
        classify_eligibility(
            probability_of_profit=0.89,
            risk_flags=[],
            mode="capital_efficient",
        )
        == EligibilityStatus.REJECTED
    )


def test_hard_pop_override_allows_lower_scan_threshold() -> None:
    ranked = rank_candidate(
        RankerInput(
            candidate=_candidate(),
            probability_of_profit=0.85,
            annualized_return=0.30,
            liquidity_score=100,
            premium=2.00,
        ),
        mode="capital_efficient",
        hard_pop_min_override=0.85,
    )

    assert ranked.eligibility_status == EligibilityStatus.ELIGIBLE
    assert ranked.final_score > 0


def test_classify_eligibility_uses_hard_pop_override() -> None:
    assert (
        classify_eligibility(
            probability_of_profit=0.85,
            risk_flags=[],
            mode="capital_efficient",
            hard_pop_min_override=0.85,
        )
        == EligibilityStatus.ELIGIBLE
    )
