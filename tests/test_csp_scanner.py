import json

from configuration import load_settings
from broker.mock_broker import (
    MOCK_OPTION_CHAINS,
    MOCK_UNDERLYING_QUOTES,
    MockBroker,
    NEXT_FRIDAY,
)
from strategy.csp_scanner import run_mock_scan
from strategy.models import EligibilityStatus, RiskFlag


def test_run_mock_scan_produces_ranked_rejected_and_report_files(tmp_path) -> None:
    settings = load_settings()

    result = run_mock_scan(settings, output_dir=tmp_path)

    assert result.ranked_trades
    assert result.sizing_result.decisions
    assert result.report_paths.ranked_json.exists()
    assert result.report_paths.ranked_csv.exists()
    assert result.report_paths.rejected_json.exists()
    assert result.report_paths.decision_log.exists()
    assert "MockBroker scan complete." in result.console_output

    ranked_output = json.loads(result.report_paths.ranked_json.read_text(encoding="utf-8"))
    # New format: {"target_summary": {...}, "trades": [...]}
    assert "trades" in ranked_output
    assert "target_summary" in ranked_output
    ranked_rows = ranked_output["trades"]
    rejected_rows = json.loads(
        result.report_paths.rejected_json.read_text(encoding="utf-8")
    )

    assert ranked_rows
    assert "rank" in ranked_rows[0]
    assert "final_score" in ranked_rows[0]
    assert "suggested_contracts" in ranked_rows[0]
    assert "target_eligible" in ranked_rows[0]
    assert isinstance(rejected_rows, list)


def test_run_mock_scan_allocates_only_within_config_constraints(tmp_path) -> None:
    settings = load_settings()

    result = run_mock_scan(settings, output_dir=tmp_path)

    assert float(result.sizing_result.total_allocated) <= settings.scanner.account_size
    assert result.sizing_result.positions_allocated <= settings.scanner.max_positions
    assert all(
        decision.capital_required <= decision.collateral_per_contract
        * decision.max_allowed_contracts_by_ticker
        for decision in result.sizing_result.decisions
        if decision.suggested_contracts > 0
    )


def test_run_mock_scan_console_includes_target_fields(tmp_path) -> None:
    settings = load_settings()

    result = run_mock_scan(settings, output_dir=tmp_path)

    assert "Weekly premium target:" in result.console_output
    assert "Premium captured:" in result.console_output
    assert "Target achieved:" in result.console_output
    assert "Unused cash:" in result.console_output


def test_scan_rejects_delayed_data_when_config_requires_live(tmp_path) -> None:
    settings = load_settings()
    delayed_underlyings = {
        symbol: quote.model_copy(update={"market_data_type": "delayed"})
        for symbol, quote in MOCK_UNDERLYING_QUOTES.items()
    }
    delayed_chains = {
        symbol: [
            option.model_copy(update={"market_data_type": "delayed"})
            for option in chain
        ]
        for symbol, chain in MOCK_OPTION_CHAINS.items()
    }
    broker = MockBroker(
        underlying_quotes=delayed_underlyings,
        option_chains=delayed_chains,
    )

    result = run_mock_scan(settings, broker=broker, output_dir=tmp_path)

    assert result.ranked_trades
    assert all(
        trade.eligibility_status == EligibilityStatus.REJECTED
        for trade in result.ranked_trades
    )
    assert all(
        RiskFlag.DATA_QUALITY_WARNING in trade.candidate.risk_flags
        for trade in result.ranked_trades
    )


def test_run_mock_scan_can_target_specific_expiration(tmp_path) -> None:
    settings = load_settings()

    result = run_mock_scan(
        settings,
        output_dir=tmp_path,
        expiration_date=NEXT_FRIDAY,
    )

    assert result.ranked_trades
    assert {
        trade.candidate.option.expiration_date.date()
        for trade in result.ranked_trades
    } == {NEXT_FRIDAY}


def test_scan_rejects_zero_bid_options_as_untradeable(tmp_path) -> None:
    settings = load_settings()
    symbol, chain = next(iter(MOCK_OPTION_CHAINS.items()))
    zero_bid_option = chain[0].model_copy(update={"bid": 0})
    adjusted_chain = [zero_bid_option, *chain[1:]]
    adjusted_chains = {**MOCK_OPTION_CHAINS, symbol: adjusted_chain}
    broker = MockBroker(
        underlying_quotes=MOCK_UNDERLYING_QUOTES,
        option_chains=adjusted_chains,
    )

    result = run_mock_scan(settings, broker=broker, output_dir=tmp_path)

    zero_bid_trades = [
        trade
        for trade in result.ranked_trades
        if trade.candidate.option.symbol == zero_bid_option.symbol
    ]
    assert zero_bid_trades
    assert all(
        trade.eligibility_status == EligibilityStatus.REJECTED
        for trade in zero_bid_trades
    )
    assert all(
        RiskFlag.DATA_QUALITY_WARNING in trade.candidate.risk_flags
        for trade in zero_bid_trades
    )


def test_capital_efficient_requested_contracts_scale_with_open_interest(tmp_path) -> None:
    settings = load_settings().model_copy(
        update={
            "scanner": load_settings().scanner.model_copy(
                update={"ranking_mode": "capital_efficient"}
            )
        }
    )

    result = run_mock_scan(settings, output_dir=tmp_path)

    aapl_190 = next(
        trade
        for trade in result.ranked_trades
        if trade.candidate.option.symbol == "AAPL 2026-05-01 190P"
    )
    assert aapl_190.candidate.option.open_interest == 6_750
    assert aapl_190.candidate.contracts == 67


def test_capital_efficient_falls_back_to_fixed_cap_without_open_interest_pct(tmp_path) -> None:
    base_settings = load_settings()
    capital_efficient = base_settings.scanner.ranking_modes["capital_efficient"].model_copy(
        update={
            "max_contracts_per_trade": 7,
            "open_interest_contract_limit_pct": None,
        }
    )
    settings = base_settings.model_copy(
        update={
            "scanner": base_settings.scanner.model_copy(
                update={
                    "ranking_mode": "capital_efficient",
                    "ranking_modes": {
                        **base_settings.scanner.ranking_modes,
                        "capital_efficient": capital_efficient,
                    },
                }
            )
        }
    )

    result = run_mock_scan(settings, output_dir=tmp_path)

    assert any(trade.candidate.contracts == 7 for trade in result.ranked_trades)
