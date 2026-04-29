from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_FLOOR

from configuration import ScanConfig
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


@dataclass(frozen=True)
class PositionSizingResult:
    decisions: list[PositionSizingDecision] = field(default_factory=list)
    total_allocated: Decimal = Decimal("0")
    positions_allocated: int = 0


def size_ranked_trades(
    ranked_trades: list[RankedTrade],
    scan_config: ScanConfig,
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
    """
    total_allocated = Decimal("0")
    positions_allocated = 0
    ticker_allocations: dict[str, Decimal] = {}
    decisions: list[PositionSizingDecision] = []

    account_size = _to_decimal(scan_config.account_size)
    max_per_ticker_exposure = _to_decimal(scan_config.max_per_ticker_exposure)

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

        skip_reason = _initial_skip_reason(
            ranked_trade=ranked_trade,
            collateral_per_contract=collateral_per_contract,
            positions_allocated=positions_allocated,
            max_positions=scan_config.max_positions,
        )

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

        decisions.append(
            PositionSizingDecision(
                ranked_trade=ranked_trade,
                collateral_per_contract=collateral_per_contract,
                max_allowed_contracts_by_ticker=max(max_allowed_by_ticker, 0),
                suggested_contracts=suggested_contracts,
                capital_required=capital_required,
                skipped=suggested_contracts == 0,
                skip_reason=skip_reason,
            )
        )

    return PositionSizingResult(
        decisions=decisions,
        total_allocated=total_allocated,
        positions_allocated=positions_allocated,
    )


def _collateral_per_contract(ranked_trade: RankedTrade) -> Decimal:
    strike = ranked_trade.candidate.option.strike
    if strike <= 0:
        return Decimal("0")

    return strike * CONTRACT_MULTIPLIER


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
