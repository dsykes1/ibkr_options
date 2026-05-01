from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from analytics.liquidity import liquidity_score, spread_pct
from analytics.pop import delta_proxy_pop, model_pop_above_break_even
from analytics.returns import (
    annualized_return,
    break_even,
    distance_to_break_even_pct,
    distance_to_strike_pct,
)
from analytics.risk_flags import identify_risk_flags
from broker.base import Broker
from broker.mock_broker import MOCK_AS_OF, MockBroker
from configuration import Settings
from data.models import OptionQuote, UnderlyingQuote
from broker.contracts import same_week_friday
from data.options_chain import fetch_option_chains_for_expiry
from data.universe import load_universe
from data.universe_discovery import KNOWN_LEVERAGED_ETFS, build_universe, filter_by_volume
from portfolio.sizing import PositionSizingResult, size_ranked_trades
from reporting.logger import DecisionLogger
from reporting.output import ReportPaths, summarize_console, write_scan_outputs
from strategy.models import CandidateTrade, RiskFlag
from strategy.ranker import RankerInput, rank_candidates


@dataclass(frozen=True)
class ScanResult:
    ranked_trades: list
    rejected_trades: list
    sizing_result: PositionSizingResult
    report_paths: ReportPaths
    console_output: str


def run_mock_scan(
    settings: Settings,
    broker: Broker | None = None,
    output_dir: Path = Path("logs"),
    as_of: date = MOCK_AS_OF,
    expiration_date: date | None = None,
) -> ScanResult:
    """Run an end-to-end cash-secured put scan using a broker adapter."""
    decision_logger = DecisionLogger()
    broker = broker or MockBroker()
    broker.connect()
    decision_logger.record(f"Connected to {broker.__class__.__name__}.")

    portfolio_snapshot = broker.fetch_portfolio_snapshot()
    # Fix: preserve configured max_per_ticker_exposure; only cap it at free_cash
    # so concentration controls remain meaningful even when cash is large.
    effective_scan_config = settings.scanner.model_copy(
        update={
            "account_size": float(portfolio_snapshot.free_cash),
            "max_per_ticker_exposure": min(
                settings.scanner.max_per_ticker_exposure,
                float(portfolio_snapshot.free_cash),
            ),
        }
    )
    effective_settings = settings.model_copy(update={"scanner": effective_scan_config})
    decision_logger.record(
        f"Portfolio snapshot: net_liquidation=${portfolio_snapshot.net_liquidation:,.2f}, "
        f"free_cash=${portfolio_snapshot.free_cash:,.2f}, "
        f"source={portfolio_snapshot.data_source}."
    )

    # Universe discovery: use build_universe which respects discovery config
    universe = build_universe(effective_scan_config)
    decision_logger.record(f"Loaded universe: {', '.join(universe)}.")
    quotes = {quote.symbol: quote for quote in broker.fetch_underlying_quotes(universe)}
    decision_logger.record(f"Fetched {len(quotes)} underlying quotes.")

    # Pre-scan underlying filter
    quotes = _filter_underlyings(
        quotes,
        effective_scan_config,
        decision_logger,
        as_of=as_of,
    )
    decision_logger.record(
        f"After pre-scan filter: {len(quotes)} underlyings remain."
    )

    selected_expiration = expiration_date or same_week_friday(as_of)
    decision_logger.record(f"Selected expiration: {selected_expiration.isoformat()}.")
    chains = fetch_option_chains_for_expiry(
        broker=broker,
        symbols=list(quotes),
        scan_config=effective_scan_config,
        expiration_date=selected_expiration,
        as_of=as_of,
        underlying_quotes=quotes,
    )
    decision_logger.record(
        f"Fetched {sum(len(chain) for chain in chains.values())} option contracts "
        f"for {selected_expiration.isoformat()}."
    )

    ranker_inputs: list[RankerInput] = []
    premium_drop_counts: dict[str, int] = {}
    for symbol, chain in chains.items():
        underlying = quotes[symbol]
        for option in chain:
            ranker_input = _evaluate_option(
                underlying=underlying,
                option=option,
                settings=effective_settings,
                as_of=as_of,
                decision_logger=decision_logger,
            )
            if not _meets_target_premium_vs_strike(ranker_input, effective_settings):
                premium_drop_counts[symbol] = premium_drop_counts.get(symbol, 0) + 1
                decision_logger.record(
                    f"Dropped {option.symbol}: bid premium/strike below "
                    f"{effective_scan_config.portfolio_targets.weekly_return_target_pct:.2f}% "
                    "weekly target."
                )
                continue
            ranker_inputs.append(ranker_input)

    ranked_trades = rank_candidates(
        ranker_inputs,
        mode=effective_scan_config.ranking_mode,
        hard_pop_min_override=effective_scan_config.portfolio_targets.min_pop,
    )
    decision_logger.record(
        f"Ranked {len(ranked_trades)} candidates using {effective_scan_config.ranking_mode} mode."
    )
    if premium_drop_counts:
        dropped_summary = ", ".join(
            f"{symbol}={count}"
            for symbol, count in sorted(
                premium_drop_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        )
        decision_logger.record(f"Premium target drops by ticker: {dropped_summary}.")

    sizing_result = size_ranked_trades(
        ranked_trades,
        effective_scan_config,
        portfolio_snapshot=portfolio_snapshot,
    )
    decision_logger.record(
        f"Allocated {sizing_result.positions_allocated} positions "
        f"using ${sizing_result.total_allocated:,.2f}."
    )

    log_path = decision_logger.write(output_dir / "decision_log.txt")
    report_paths = write_scan_outputs(
        sizing_result=sizing_result,
        decision_log_path=log_path,
        scan_config=effective_scan_config,
        premium_drop_counts=premium_drop_counts,
        output_dir=output_dir,
    )
    console_output = summarize_console(
        sizing_result,
        report_paths,
        broker_name=broker.__class__.__name__,
    )

    rejected_trades = [
        decision.ranked_trade
        for decision in sizing_result.decisions
        if decision.skipped
    ]

    broker.disconnect()
    return ScanResult(
        ranked_trades=ranked_trades,
        rejected_trades=rejected_trades,
        sizing_result=sizing_result,
        report_paths=report_paths,
        console_output=console_output,
    )


def _evaluate_option(
    *,
    underlying: UnderlyingQuote,
    option: OptionQuote,
    settings: Settings,
    as_of: date,
    decision_logger: DecisionLogger,
) -> RankerInput:
    executable_premium = option.bid
    midpoint_premium = (option.bid + option.ask) / Decimal("2")
    collateral = option.strike * Decimal("100")
    days_to_expiry = max((option.expiration_date.date() - as_of).days, 1)
    break_even_price = break_even(float(option.strike), float(executable_premium))
    distance_to_strike = distance_to_strike_pct(
        float(underlying.last_price),
        float(option.strike),
    )
    distance_to_break_even = (
        distance_to_break_even_pct(float(underlying.last_price), break_even_price)
        if break_even_price is not None
        else None
    )
    modeled_pop = (
        model_pop_above_break_even(
            underlying_price=float(underlying.last_price),
            break_even_price=break_even_price,
            implied_volatility=float(option.implied_volatility),
            days_to_expiry=days_to_expiry,
        )
        if break_even_price is not None and option.implied_volatility is not None
        else None
    )
    fallback_pop = (
        delta_proxy_pop(float(option.delta)) if option.delta is not None else None
    )
    probability_of_profit = (
        modeled_pop if modeled_pop is not None else fallback_pop
    )
    pop_source = (
        "black_scholes"
        if modeled_pop is not None
        else "delta_proxy"
        if fallback_pop is not None
        else "unavailable"
    )
    annualized = annualized_return(
        premium=float(executable_premium),
        collateral=float(option.strike),
        days_to_expiry=days_to_expiry,
    )
    option_spread_pct = spread_pct(float(option.bid), float(option.ask))
    metadata = settings.scanner.symbol_metadata.get(underlying.symbol.upper())
    option_liquidity_score = liquidity_score(
        bid=float(option.bid),
        ask=float(option.ask),
        volume=option.volume,
        open_interest=option.open_interest,
        target_volume=max(settings.scanner.default_filters.min_option_volume, 1),
        target_open_interest=max(settings.scanner.default_filters.min_open_interest, 1),
        max_spread_pct=settings.scanner.default_filters.max_bid_ask_spread_pct or 20,
    )
    risk_flags = identify_risk_flags(
        symbol=underlying.symbol,
        liquidity_score=option_liquidity_score,
        spread_pct=option_spread_pct,
        underlying_price=float(underlying.last_price),
        implied_volatility=float(option.implied_volatility)
        if option.implied_volatility is not None
        else None,
        ticker_exposure=float(collateral),
        max_per_ticker_exposure=settings.scanner.max_per_ticker_exposure,
        max_spread_pct=settings.scanner.default_filters.max_bid_ask_spread_pct or 20,
        min_underlying_price=settings.scanner.default_filters.min_underlying_price or 0,
    )
    risk_flags.extend(
        _config_filter_flags(
            option=option,
            annualized=annualized,
            premium_per_share=executable_premium,
            settings=settings,
        )
    )
    if _event_within_window(
        metadata.next_known_event_date if metadata is not None else None,
        as_of=as_of,
        window_days=settings.scanner.default_filters.exclude_earnings_within_days,
    ):
        risk_flags.append(RiskFlag.KNOWN_EVENT_NEAR_EXPIRATION)
    if not _has_tradeable_bid_ask(option):
        risk_flags.append(RiskFlag.DATA_QUALITY_WARNING)
        probability_of_profit = None
        annualized = None
    if option.data_quality_warnings or underlying.data_quality_warnings:
        risk_flags.append(RiskFlag.DATA_QUALITY_WARNING)
    if _has_disallowed_market_data_type(option, settings) or _has_disallowed_market_data_type(
        underlying,
        settings,
    ):
        risk_flags.append(RiskFlag.DATA_QUALITY_WARNING)
        probability_of_profit = None
    if _missing_required_option_fields(option, settings):
        risk_flags.append(RiskFlag.DATA_QUALITY_WARNING)
        probability_of_profit = None
    risk_flags = list(dict.fromkeys(risk_flags))
    mode_name = settings.scanner.ranking_mode
    mode_config = settings.scanner.ranking_modes[mode_name]

    candidate = CandidateTrade(
        underlying=underlying,
        option=option,
        contracts=_requested_contracts(
            option=option,
            mode_name=mode_name,
            mode_config=mode_config,
        ),
        cash_required=collateral,
        estimated_premium=executable_premium * Decimal("100"),
        risk_flags=risk_flags,
        notes=[
            f"days_to_expiry={days_to_expiry}",
            f"break_even={break_even_price}",
            f"distance_to_strike_pct={distance_to_strike}",
            f"distance_to_break_even_pct={distance_to_break_even}",
            f"bid_ask_spread_pct={option_spread_pct}",
            f"mid_price={midpoint_premium}",
            "return_premium_basis=bid",
            f"modeled_pop={modeled_pop}",
            f"delta_proxy_pop={fallback_pop}",
            f"probability_of_profit={probability_of_profit}",
            f"pop_source={pop_source}",
            f"annualized_return={annualized}",
            f"liquidity_score={option_liquidity_score}",
            f"sector={metadata.sector if metadata is not None else None}",
            f"themes={','.join(metadata.themes) if metadata is not None else None}",
            f"next_earnings_date={metadata.next_earnings_date if metadata is not None else None}",
            f"next_known_event_date={metadata.next_known_event_date if metadata is not None else None}",
            f"next_known_event_name={metadata.next_known_event_name if metadata is not None else None}",
            f"iv_rank={metadata.iv_rank if metadata is not None else None}",
            f"iv_percentile={metadata.iv_percentile if metadata is not None else None}",
            f"max_loss_at_assignment={collateral - executable_premium * Decimal('100')}",
            f"assignment_cost_basis={break_even_price}",
            f"assignment_plan={_assignment_plan(underlying.symbol, metadata)}",
        ],
    )
    decision_logger.record(
        f"Evaluated {option.symbol}: POP={_format_optional_float(probability_of_profit)} "
        f"source={pop_source} "
        f"return={_format_optional_float(annualized)} liquidity={option_liquidity_score:.1f} "
        f"flags={[flag.value for flag in risk_flags]}."
    )

    return RankerInput(
        candidate=candidate,
        probability_of_profit=probability_of_profit,
        annualized_return=annualized,
        liquidity_score=option_liquidity_score,
        premium=float(executable_premium),
    )


def _config_filter_flags(
    *,
    option: OptionQuote,
    annualized: float | None,
    premium_per_share: Decimal,
    settings: Settings,
) -> list[RiskFlag]:
    flags: list[RiskFlag] = []
    mode_config = settings.scanner.ranking_modes[settings.scanner.ranking_mode]

    premium_dollars = premium_per_share * Decimal("100")
    if mode_config.min_premium is not None and premium_dollars < Decimal(
        str(mode_config.min_premium)
    ):
        flags.append(RiskFlag.BELOW_MINIMUM_PREMIUM)

    min_return = mode_config.min_annualized_return_pct
    if (
        min_return is not None
        and annualized is not None
        and annualized < min_return / 100
    ):
        flags.append(RiskFlag.BELOW_TARGET_RETURN)

    if (
        mode_config.max_delta is not None
        and option.delta is not None
        and abs(option.delta) > Decimal(str(mode_config.max_delta))
    ):
        flags.append(RiskFlag.ABOVE_MAX_DELTA)

    return flags


def _meets_target_premium_vs_strike(
    ranker_input: RankerInput,
    settings: Settings,
) -> bool:
    option = ranker_input.candidate.option
    if option.strike <= 0:
        return False

    premium_vs_strike_pct = (option.bid / option.strike) * Decimal("100")
    target_pct = Decimal(str(settings.scanner.portfolio_targets.weekly_return_target_pct))
    return premium_vs_strike_pct >= target_pct


def _missing_required_option_fields(option: OptionQuote, settings: Settings) -> bool:
    market_data = settings.market_data
    required_fields: list[object] = []

    if market_data.require_bid_ask and not _has_tradeable_bid_ask(option):
        return True

    if market_data.require_bid_ask:
        required_fields.extend([option.bid, option.ask])
    if market_data.require_greeks:
        required_fields.append(option.delta)
    if market_data.require_iv:
        required_fields.append(option.implied_volatility)
    if market_data.require_open_interest:
        required_fields.append(option.open_interest)
    if market_data.require_option_volume:
        required_fields.append(option.volume)

    return any(value is None for value in required_fields)


def _has_tradeable_bid_ask(option: OptionQuote) -> bool:
    return option.bid > 0 and option.ask > 0 and option.ask >= option.bid


_UNCAPPED_CONTRACTS = 10_000


def _requested_contracts(
    *,
    option: OptionQuote,
    mode_name: str,
    mode_config,
) -> int:
    max_cap = mode_config.max_contracts_per_trade  # None means uncapped

    if mode_name != "capital_efficient":
        return max_cap if max_cap is not None else _UNCAPPED_CONTRACTS

    open_interest_limit_pct = mode_config.open_interest_contract_limit_pct
    if open_interest_limit_pct is None:
        return max_cap if max_cap is not None else _UNCAPPED_CONTRACTS

    open_interest = max(option.open_interest or 0, 0)
    if open_interest <= 0:
        return max_cap if max_cap is not None else _UNCAPPED_CONTRACTS

    oi_based = max(int(open_interest * (open_interest_limit_pct / 100)), 1)
    return min(oi_based, max_cap) if max_cap is not None else oi_based


def _has_disallowed_market_data_type(
    quote: OptionQuote | UnderlyingQuote,
    settings: Settings,
) -> bool:
    data_type = quote.market_data_type
    if data_type in {None, "live"}:
        return False

    if data_type in {"delayed", "delayed_frozen"}:
        return settings.market_data.reject_if_delayed or not settings.market_data.allow_delayed_fallback

    return settings.market_data.reject_if_delayed


def _format_optional_float(value: float | None) -> str:
    if value is None:
        return "unavailable"

    return f"{value:.3f}"


def _filter_underlyings(
    quotes: dict[str, UnderlyingQuote],
    scan_config,
    decision_logger: DecisionLogger,
    *,
    as_of: date,
) -> dict[str, UnderlyingQuote]:
    """Apply pre-scan underlying-level filters before option chain fetch.

    Filters applied (all config-driven):
    - Price range (min/max_underlying_price)
    - Leveraged ETF exclusion (if universe_discovery.exclude_leveraged_etfs)
    - Minimum underlying volume (if universe_discovery.min_underlying_volume set)
    - Collateral feasibility (at least 1 contract fits account)
    - Earnings exclusion when symbol metadata has an earnings date inside the configured window
    """
    filters = scan_config.default_filters
    disc = scan_config.universe_discovery
    account_size = scan_config.account_size
    result: dict[str, UnderlyingQuote] = {}

    for symbol, quote in quotes.items():
        reasons: list[str] = []
        price = float(quote.last_price)

        if filters.min_underlying_price is not None and price < filters.min_underlying_price:
            reasons.append(
                f"price {price:.2f} below min {filters.min_underlying_price}"
            )

        if filters.max_underlying_price is not None and price > filters.max_underlying_price:
            reasons.append(
                f"price {price:.2f} above max {filters.max_underlying_price}"
            )

        if disc.exclude_leveraged_etfs and symbol in KNOWN_LEVERAGED_ETFS:
            reasons.append("leveraged_etf")

        if disc.min_underlying_volume is not None:
            vol = quote.volume or quote.average_volume
            if vol is not None and vol < disc.min_underlying_volume:
                reasons.append(
                    f"volume {vol} below min {disc.min_underlying_volume}"
                )

        metadata = scan_config.symbol_metadata.get(symbol.upper())
        earnings_date = metadata.next_earnings_date if metadata is not None else None
        if _event_within_window(
            earnings_date,
            as_of=as_of,
            window_days=filters.exclude_earnings_within_days,
        ):
            reasons.append(
                f"earnings {earnings_date.isoformat()} within "
                f"{filters.exclude_earnings_within_days} days"
            )

        # Collateral feasibility: strike roughly ~underlying price; skip if can't fill 1 contract
        min_collateral = price * 100 * 0.70  # rough OTM assumption
        if min_collateral > account_size:
            reasons.append(
                f"collateral ~${min_collateral:,.0f} exceeds account ${account_size:,.0f}"
            )

        if reasons:
            decision_logger.record(
                f"Filtered underlying {symbol}: {'; '.join(reasons)}."
            )
            continue

        earnings_note = (
            f"next earnings {earnings_date.isoformat()}"
            if earnings_date is not None
            else "earnings data unavailable; manual check recommended"
        )
        decision_logger.record(
            f"Underlying {symbol} passed pre-scan filter ({earnings_note})."
        )
        result[symbol] = quote

    return result


def _event_within_window(
    event_date: date | None,
    *,
    as_of: date,
    window_days: int | None,
) -> bool:
    if event_date is None or window_days is None:
        return False

    days_until_event = (event_date - as_of).days
    return 0 <= days_until_event <= window_days


def _assignment_plan(symbol: str, metadata) -> str:
    if metadata is not None and metadata.assignment_plan:
        return metadata.assignment_plan

    return (
        f"If assigned, buy 100 shares per contract of {symbol} at the strike; "
        "only enter if the break-even price is acceptable and the position can be held, "
        "reduced, or managed with covered calls."
    )
