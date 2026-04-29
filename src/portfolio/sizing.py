from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_FLOOR

from configuration import PortfolioTargetsConfig, ScanConfig
from portfolio.models import PortfolioSnapshot
from strategy.models import EligibilityStatus, RankedTrade


CONTRACT_MULTIPLIER = Decimal("100")


@dataclass(frozen=True)
class PositionSizingDecision:
    ranked_trade: RankedTrade
    collateral_per_contract: Decimal
    max_allowed_contracts_by_ticker: int
    suggested_contracts: int
    capital_required: Decimal
    skipped: bool
    skip_reason: str | None = None
    portfolio_snapshot: PortfolioSnapshot | None = None
    # Target-tracking fields
    target_eligible: bool = True
    target_skip_reason: str | None = None


@dataclass(frozen=True)
class PositionSizingResult:
    decisions: list[PositionSizingDecision] = field(default_factory=list)
    total_allocated: Decimal = Decimal("0")
    positions_allocated: int = 0
    portfolio_snapshot: PortfolioSnapshot | None = None
    # Portfolio-target summary fields
    target_weekly_premium: Decimal = Decimal("0")
    premium_captured: Decimal = Decimal("0")
    target_achieved_pct: float = 0.0
    target_met: bool = False
    unused_cash: Decimal = Decimal("0")


def size_ranked_trades(
    ranked_trades: list[RankedTrade],
    scan_config: ScanConfig,
    portfolio_snapshot: PortfolioSnapshot | None = None,
) -> PositionSizingResult:
    """Allocate whole cash-secured put contracts in rank order.

    Assumptions:
        collateral_per_contract = strike * 100
        total allocated capital <= account_size
        ticker exposure <= max_per_ticker_exposure
        allocated positions <= max_positions

    Trades are processed by ascending rank. Rejected trades or trades that do not
    fit the remaining account, position, or ticker constraints receive zero
    suggested contracts.

    Portfolio-target tracking:
        A trade is *target eligible* when:
            - its POP meets portfolio_targets.min_pop, and
            - premium/strike meets portfolio_targets.weekly_return_target_pct.
        If reject_if_target_requires_low_quality_trades is True, ineligible trades
        are skipped from allocation rather than just annotated.
        premium_captured accumulates mid-premium * 100 * contracts for eligible
        allocated trades and is compared against target_weekly_premium.
    """
    total_allocated = Decimal("0")
    positions_allocated = 0
    ticker_allocations: dict[str, Decimal] = {}
    decisions: list[PositionSizingDecision] = []

    account_size = _to_decimal(scan_config.account_size)
    max_per_ticker_exposure = _to_decimal(scan_config.max_per_ticker_exposure)

    # Portfolio-target state
    portfolio_targets: PortfolioTargetsConfig = scan_config.portfolio_targets
    portfolio_value = (
        portfolio_snapshot.net_liquidation
        if portfolio_snapshot is not None
        else account_size
    )
    target_weekly_premium = (
        portfolio_value
        * _to_decimal(portfolio_targets.weekly_return_target_pct)
        / Decimal("100")
    )
    premium_captured = Decimal("0")

    for ranked_trade in sorted(ranked_trades, key=lambda trade: trade.rank):
        candidate = ranked_trade.candidate
        ticker = candidate.underlying.symbol
        collateral_per_contract = _collateral_per_contract(ranked_trade)
        ticker_allocated = ticker_allocations.get(ticker, Decimal("0"))
        max_allowed_by_ticker = _floor_contracts(
            (max_per_ticker_exposure - ticker_allocated) / collateral_per_contract
            if collateral_per_contract > 0
            else Decimal("0")
        )

        # Determine target eligibility from POP and premium-vs-risked-capital.
        trade_pop = _pop_from_notes(candidate)
        premium_vs_risked_pct = _premium_vs_risked_pct(ranked_trade)
        pop_ok = trade_pop is None or trade_pop >= portfolio_targets.min_pop
        premium_ok = (
            premium_vs_risked_pct is not None
            and premium_vs_risked_pct >= portfolio_targets.weekly_return_target_pct
        )
        target_eligible = pop_ok and premium_ok
        target_skip_reason: str | None = None
        if not pop_ok:
            target_skip_reason = "pop_below_target_min_pop"
        elif not premium_ok:
            target_skip_reason = "premium_below_weekly_target_pct"

        skip_reason = _initial_skip_reason(
            ranked_trade=ranked_trade,
            collateral_per_contract=collateral_per_contract,
            positions_allocated=positions_allocated,
            max_positions=scan_config.max_positions,
        )

        # Quality gate: skip low-quality trades entirely when configured
        if (
            skip_reason is None
            and not target_eligible
            and portfolio_targets.reject_if_target_requires_low_quality_trades
        ):
            skip_reason = "below_target_quality_threshold"

        suggested_contracts = 0
        capital_required = Decimal("0")

        if skip_reason is None:
            remaining_account_capital = account_size - total_allocated
            max_allowed_by_account = _floor_contracts(
                remaining_account_capital / collateral_per_contract
            )
            requested_contracts = candidate.contracts
            suggested_contracts = min(
                requested_contracts,
                max_allowed_by_ticker,
                max_allowed_by_account,
            )
            capital_required = collateral_per_contract * suggested_contracts

            if suggested_contracts <= 0:
                skip_reason = "constraints_allow_zero_contracts"
                capital_required = Decimal("0")
            else:
                total_allocated += capital_required
                ticker_allocations[ticker] = ticker_allocated + capital_required
                positions_allocated += 1
                # Accrue premium toward target
                if target_eligible:
                    marketable_premium = _marketable_premium(ranked_trade)
                    premium_captured += (
                        marketable_premium
                        * CONTRACT_MULTIPLIER
                        * suggested_contracts
                    )

        decisions.append(
            PositionSizingDecision(
                ranked_trade=ranked_trade,
                collateral_per_contract=collateral_per_contract,
                max_allowed_contracts_by_ticker=max(max_allowed_by_ticker, 0),
                suggested_contracts=suggested_contracts,
                capital_required=capital_required,
                skipped=suggested_contracts == 0,
                skip_reason=skip_reason,
                portfolio_snapshot=portfolio_snapshot,
                target_eligible=target_eligible,
                target_skip_reason=target_skip_reason,
            )
        )

    target_achieved_pct = (
        float(premium_captured / target_weekly_premium * 100)
        if target_weekly_premium > 0
        else 0.0
    )
    target_met = premium_captured >= target_weekly_premium and target_weekly_premium > 0
    unused_cash = max(account_size - total_allocated, Decimal("0"))

    return PositionSizingResult(
        decisions=decisions,
        total_allocated=total_allocated,
        positions_allocated=positions_allocated,
        portfolio_snapshot=portfolio_snapshot,
        target_weekly_premium=target_weekly_premium,
        premium_captured=premium_captured,
        target_achieved_pct=target_achieved_pct,
        target_met=target_met,
        unused_cash=unused_cash,
    )


def _collateral_per_contract(ranked_trade: RankedTrade) -> Decimal:
    strike = ranked_trade.candidate.option.strike
    if strike <= 0:
        return Decimal("0")

    return strike * CONTRACT_MULTIPLIER


def _marketable_premium(ranked_trade: RankedTrade) -> Decimal:
    """Return conservative premium per share based on executable bid."""
    option = ranked_trade.candidate.option
    return option.bid


def _premium_vs_risked_pct(ranked_trade: RankedTrade) -> float | None:
    """Return premium/strike percentage for one contract."""
    strike = ranked_trade.candidate.option.strike
    if strike <= 0:
        return None

    return float((_marketable_premium(ranked_trade) / strike) * Decimal("100"))


def _pop_from_notes(candidate) -> float | None:
    """Extract the modeled_pop value stored in candidate notes, if present."""
    prefix = "modeled_pop="
    for note in candidate.notes:
        if note.startswith(prefix):
            raw = note.removeprefix(prefix)
            if raw in {"None", ""}:
                return None
            try:
                return float(raw)
            except ValueError:
                return None
    return None


def _initial_skip_reason(
    *,
    ranked_trade: RankedTrade,
    collateral_per_contract: Decimal,
    positions_allocated: int,
    max_positions: int,
) -> str | None:
    if ranked_trade.eligibility_status == EligibilityStatus.REJECTED:
        return "rejected_trade"

    if collateral_per_contract <= 0:
        return "invalid_collateral"

    if positions_allocated >= max_positions:
        return "max_positions_reached"

    return None


def _floor_contracts(value: Decimal) -> int:
    if value <= 0:
        return 0

    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def _to_decimal(value: float | int | Decimal) -> Decimal:
    return Decimal(str(value))
