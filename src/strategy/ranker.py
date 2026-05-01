from __future__ import annotations

from dataclasses import replace
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from strategy.models import CandidateTrade, EligibilityStatus, RankedTrade, RiskFlag


RankingMode = Literal["ultra_safe", "capital_efficient"]


@dataclass(frozen=True)
class RankingModeSpec:
    name: RankingMode
    pop_weight: float
    return_weight: float
    liquidity_weight: float
    premium_weight: float
    hard_pop_min: float
    target_pop: float
    target_annualized_return: float
    target_premium: float
    flag_penalties: dict[RiskFlag, float] = field(default_factory=dict)
    rejection_flags: frozenset[RiskFlag] = frozenset()


MODE_SPECS: dict[RankingMode, RankingModeSpec] = {
    "ultra_safe": RankingModeSpec(
        name="ultra_safe",
        pop_weight=0.50,
        return_weight=0.25,
        liquidity_weight=0.20,
        premium_weight=0.05,
        hard_pop_min=0.95,
        target_pop=0.98,
        target_annualized_return=0.18,
        target_premium=1.00,
        flag_penalties={
            RiskFlag.LOW_LIQUIDITY: 20,
            RiskFlag.WIDE_SPREAD: 15,
            RiskFlag.LOW_PRICE_STOCK: 20,
            RiskFlag.LEVERAGED_ETF: 30,
            RiskFlag.HIGH_IV: 10,
            RiskFlag.KNOWN_EVENT_NEAR_EXPIRATION: 10,
            RiskFlag.CONCENTRATION_RISK: 100,
        },
        rejection_flags=frozenset(
            {
                RiskFlag.INSUFFICIENT_CASH,
                RiskFlag.CONCENTRATION_RISK,
                RiskFlag.HIGH_POSITION_CONCENTRATION,
            }
        ),
    ),
    "capital_efficient": RankingModeSpec(
        name="capital_efficient",
        pop_weight=0.30,
        return_weight=0.40,
        liquidity_weight=0.20,
        premium_weight=0.10,
        hard_pop_min=0.90,
        target_pop=0.94,
        target_annualized_return=0.30,
        target_premium=1.50,
        flag_penalties={
            RiskFlag.LOW_LIQUIDITY: 12,
            RiskFlag.WIDE_SPREAD: 10,
            RiskFlag.LOW_PRICE_STOCK: 15,
            RiskFlag.LEVERAGED_ETF: 20,
            RiskFlag.HIGH_IV: 8,
            RiskFlag.KNOWN_EVENT_NEAR_EXPIRATION: 8,
            RiskFlag.CONCENTRATION_RISK: 100,
        },
        rejection_flags=frozenset(
            {
                RiskFlag.INSUFFICIENT_CASH,
                RiskFlag.CONCENTRATION_RISK,
                RiskFlag.HIGH_POSITION_CONCENTRATION,
            }
        ),
    ),
}


class RankerInput(BaseModel):
    candidate: CandidateTrade
    probability_of_profit: float | None = Field(default=None, ge=0, le=1)
    annualized_return: float | None = Field(default=None, ge=0)
    liquidity_score: float | None = Field(default=None, ge=0, le=100)
    premium: float | None = Field(default=None, ge=0)


def rank_candidates(
    inputs: list[RankerInput],
    mode: RankingMode = "ultra_safe",
    hard_pop_min_override: float | None = None,
) -> list[RankedTrade]:
    """Rank candidate trades using mode-specific weights, thresholds, and penalties.

    All modes consume the same raw inputs: probability of profit, annualized
    return, liquidity score, and premium. Component scores are normalized to
    0-100, combined by weights, then reduced by risk-flag penalties.
    """
    spec = _spec_for_mode(mode, hard_pop_min_override=hard_pop_min_override)
    ranked = [
        _rank_single(rank_input=rank_input, spec=spec, provisional_rank=index + 1)
        for index, rank_input in enumerate(inputs)
    ]
    ranked.sort(
        key=lambda trade: (
            trade.eligibility_status == EligibilityStatus.REJECTED,
            -trade.final_score,
        )
    )

    return [
        trade.model_copy(update={"rank": index + 1})
        for index, trade in enumerate(ranked)
    ]


def rank_candidate(
    rank_input: RankerInput,
    mode: RankingMode = "ultra_safe",
    hard_pop_min_override: float | None = None,
) -> RankedTrade:
    """Rank a single candidate and return a rank-1 `RankedTrade`."""
    return _rank_single(
        rank_input=rank_input,
        spec=_spec_for_mode(mode, hard_pop_min_override=hard_pop_min_override),
        provisional_rank=1,
    )


def classify_eligibility(
    *,
    probability_of_profit: float | None,
    risk_flags: list[RiskFlag],
    mode: RankingMode = "ultra_safe",
    hard_pop_min_override: float | None = None,
) -> EligibilityStatus:
    """Classify eligibility from hard POP threshold and risk flags.

    Candidates below the mode's hard POP minimum are rejected. Candidates with
    rejection flags are also rejected. Remaining candidates with non-rejection
    flags are eligible with flags; clean candidates are eligible.
    """
    spec = _spec_for_mode(mode, hard_pop_min_override=hard_pop_min_override)
    safe_pop = _safe_float(probability_of_profit)
    if safe_pop is None or safe_pop < spec.hard_pop_min:
        return EligibilityStatus.REJECTED

    if spec.rejection_flags.intersection(risk_flags):
        return EligibilityStatus.REJECTED

    if risk_flags:
        return EligibilityStatus.ELIGIBLE_WITH_FLAGS

    return EligibilityStatus.ELIGIBLE


def _rank_single(
    *,
    rank_input: RankerInput,
    spec: RankingModeSpec,
    provisional_rank: int,
) -> RankedTrade:
    candidate = rank_input.candidate
    risk_flags = candidate.risk_flags
    pop_score = _score_probability_of_profit(
        rank_input.probability_of_profit,
        target_pop=spec.target_pop,
    )
    return_score = _score_positive_metric(
        rank_input.annualized_return,
        target=spec.target_annualized_return,
    )
    liquidity_component_score = _score_liquidity(rank_input.liquidity_score)
    premium_score = _score_positive_metric(rank_input.premium, target=spec.target_premium)

    weighted_score = (
        pop_score * spec.pop_weight
        + return_score * spec.return_weight
        + liquidity_component_score * spec.liquidity_weight
        + premium_score * spec.premium_weight
    )
    penalty = _risk_penalty(risk_flags, spec)
    final_score = _clamp(weighted_score - penalty)
    eligibility_status = classify_eligibility(
        probability_of_profit=rank_input.probability_of_profit,
        risk_flags=risk_flags,
        mode=spec.name,
        hard_pop_min_override=spec.hard_pop_min,
    )

    if eligibility_status == EligibilityStatus.REJECTED:
        final_score = 0

    rationale = _build_rationale(
        probability_of_profit=rank_input.probability_of_profit,
        penalty=penalty,
        eligibility_status=eligibility_status,
        spec=spec,
        risk_flags=risk_flags,
    )

    return RankedTrade(
        candidate=candidate.model_copy(update={"eligibility_status": eligibility_status}),
        rank=provisional_rank,
        score=_to_decimal(final_score),
        ranking_mode=spec.name,
        ranking_mode_used=spec.name,
        pop_score=_to_decimal(pop_score),
        return_score=_to_decimal(return_score),
        liquidity_score=_to_decimal(liquidity_component_score),
        premium_score=_to_decimal(premium_score),
        final_score=_to_decimal(final_score),
        eligibility_status=eligibility_status,
        rationale=rationale,
    )


def _score_probability_of_profit(
    probability_of_profit: float | None,
    *,
    target_pop: float,
) -> float:
    safe_pop = _safe_float(probability_of_profit)
    if safe_pop is None or target_pop <= 0:
        return 0

    return _clamp((safe_pop / target_pop) * 100)


def _score_positive_metric(value: float | None, *, target: float) -> float:
    safe_value = _safe_float(value)
    if safe_value is None or target <= 0:
        return 0

    return _clamp((safe_value / target) * 100)


def _score_liquidity(value: float | None) -> float:
    safe_value = _safe_float(value)
    if safe_value is None:
        return 0

    return _clamp(safe_value)


def _risk_penalty(risk_flags: list[RiskFlag], spec: RankingModeSpec) -> float:
    return sum(spec.flag_penalties.get(flag, 0) for flag in risk_flags)


def _spec_for_mode(
    mode: RankingMode,
    *,
    hard_pop_min_override: float | None = None,
) -> RankingModeSpec:
    spec = MODE_SPECS[mode]
    if hard_pop_min_override is None:
        return spec

    return replace(spec, hard_pop_min=hard_pop_min_override)


def _build_rationale(
    *,
    probability_of_profit: float | None,
    penalty: float,
    eligibility_status: EligibilityStatus,
    spec: RankingModeSpec,
    risk_flags: list[RiskFlag],
) -> list[str]:
    rationale: list[str] = [
        f"Mode {spec.name}: POP {spec.pop_weight:.0%}, return {spec.return_weight:.0%}, "
        f"liquidity {spec.liquidity_weight:.0%}, premium {spec.premium_weight:.0%}."
    ]

    safe_pop = _safe_float(probability_of_profit)
    if safe_pop is None:
        rationale.append("Rejected: missing probability of profit.")
    elif safe_pop < spec.hard_pop_min:
        rationale.append(
            f"Rejected: POP {safe_pop:.1%} is below hard minimum {spec.hard_pop_min:.1%}."
        )

    if risk_flags:
        rationale.append(
            "Risk flags: " + ", ".join(flag.value for flag in risk_flags) + "."
        )

    if penalty > 0:
        rationale.append(f"Risk penalty applied: {penalty:.1f} points.")

    rationale.append(f"Eligibility: {eligibility_status.value}.")
    return rationale


def _safe_float(value: float | None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, lower: float = 0, upper: float = 100) -> float:
    return max(lower, min(value, upper))


def _to_decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 4)))
