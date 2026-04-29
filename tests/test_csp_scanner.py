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

    ranked_rows = json.loads(result.report_paths.ranked_json.read_text(encoding="utf-8"))
    rejected_rows = json.loads(
        result.report_paths.rejected_json.read_text(encoding="utf-8")
    )

    assert ranked_rows
    assert "rank" in ranked_rows[0]
    assert "final_score" in ranked_rows[0]
    assert "suggested_contracts" in ranked_rows[0]
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
