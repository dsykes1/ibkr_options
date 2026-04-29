from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from analytics.liquidity import liquidity_score, spread_pct
from analytics.pop import delta_proxy_pop, model_pop_above_break_even
from analytics.returns import annualized_return, break_even
from analytics.risk_flags import identify_risk_flags
from broker.base import Broker
from broker.mock_broker import MOCK_AS_OF, MockBroker
from configuration import Settings
from data.models import OptionQuote, UnderlyingQuote
from broker.contracts import same_week_friday
from data.options_chain import fetch_option_chains_for_expiry
from data.universe import load_universe
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

    universe = load_universe(settings.scanner)
    decision_logger.record(f"Loaded universe: {', '.join(universe)}.")
    quotes = {quote.symbol: quote for quote in broker.fetch_underlying_quotes(universe)}
    decision_logger.record(f"Fetched {len(quotes)} underlying quotes.")

    selected_expiration = expiration_date or same_week_friday(as_of)
    decision_logger.record(f"Selected expiration: {selected_expiration.isoformat()}.")
    chains = fetch_option_chains_for_expiry(
        broker=broker,
        symbols=list(quotes),
        scan_config=settings.scanner,
        expiration_date=selected_expiration,
        as_of=as_of,
    )
    decision_logger.record(
        f"Fetched {sum(len(chain) for chain in chains.values())} option contracts "
        f"for {selected_expiration.isoformat()}."
    )

    ranker_inputs: list[RankerInput] = []
    for symbol, chain in chains.items():
        underlying = quotes[symbol]
        for option in chain:
            ranker_input = _evaluate_option(
                underlying=underlying,
                option=option,
                settings=settings,
                as_of=as_of,
                decision_logger=decision_logger,
            )
            ranker_inputs.append(ranker_input)

    ranked_trades = rank_candidates(
        ranker_inputs,
        mode=settings.scanner.ranking_mode,
    )
    decision_logger.record(
        f"Ranked {len(ranked_trades)} candidates using {settings.scanner.ranking_mode} mode."
    )

    sizing_result = size_ranked_trades(ranked_trades, settings.scanner)
    decision_logger.record(
        f"Allocated {sizing_result.positions_allocated} positions "
        f"using ${sizing_result.total_allocated:,.2f}."
    )

    log_path = decision_logger.write(output_dir / "decision_log.txt")
    report_paths = write_scan_outputs(
        sizing_result=sizing_result,
        decision_log_path=log_path,
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
    mid_premium = (option.bid + option.ask) / Decimal("2")
    collateral = option.strike * Decimal("100")
    days_to_expiry = max((option.expiration_date.date() - as_of).days, 1)
    break_even_price = break_even(float(option.strike), float(mid_premium))
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
    probability_of_profit = modeled_pop or fallback_pop
    annualized = annualized_return(
        premium=float(mid_premium),
        collateral=float(option.strike),
        days_to_expiry=days_to_expiry,
    )
    option_spread_pct = spread_pct(float(option.bid), float(option.ask))
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
            mid_premium=mid_premium,
            settings=settings,
        )
    )
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

    candidate = CandidateTrade(
        underlying=underlying,
        option=option,
        contracts=settings.scanner.ranking_modes[
            settings.scanner.ranking_mode
        ].max_contracts_per_trade,
        cash_required=collateral,
        estimated_premium=mid_premium * Decimal("100"),
        risk_flags=risk_flags,
        notes=[
            f"days_to_expiry={days_to_expiry}",
            f"break_even={break_even_price}",
            f"modeled_pop={probability_of_profit}",
            f"annualized_return={annualized}",
            f"liquidity_score={option_liquidity_score}",
        ],
    )
    decision_logger.record(
        f"Evaluated {option.symbol}: POP={_format_optional_float(probability_of_profit)} "
        f"return={annualized:.3f} liquidity={option_liquidity_score:.1f} "
        f"flags={[flag.value for flag in risk_flags]}."
    )

    return RankerInput(
        candidate=candidate,
        probability_of_profit=probability_of_profit,
        annualized_return=annualized,
        liquidity_score=option_liquidity_score,
        premium=float(mid_premium),
    )


def _config_filter_flags(
    *,
    option: OptionQuote,
    annualized: float | None,
    mid_premium: Decimal,
    settings: Settings,
) -> list[RiskFlag]:
    flags: list[RiskFlag] = []
    mode_config = settings.scanner.ranking_modes[settings.scanner.ranking_mode]

    premium_dollars = mid_premium * Decimal("100")
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


def _missing_required_option_fields(option: OptionQuote, settings: Settings) -> bool:
    market_data = settings.market_data
    required_fields: list[object] = []

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
