import logging
from decimal import Decimal

from broker.ibkr_client import (
    IBKR_MARKET_DATA_TYPES,
    IbkrClientConfig,
    _OptionDefinition,
    _IbkrApp,
    _dedupe_option_definitions,
    _load_ibapi,
    _select_relevant_strikes,
)
from strategy.models import RiskFlag


def test_ibkr_market_data_type_labels() -> None:
    assert IBKR_MARKET_DATA_TYPES[1] == "live"
    assert IBKR_MARKET_DATA_TYPES[2] == "frozen"
    assert IBKR_MARKET_DATA_TYPES[3] == "delayed"
    assert IBKR_MARKET_DATA_TYPES[4] == "delayed_frozen"


def test_ibkr_config_loads_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("IBKR_HOST", "localhost")
    monkeypatch.setenv("IBKR_PORT", "4002")
    monkeypatch.setenv("IBKR_CLIENT_ID", "7")
    monkeypatch.setenv("IBKR_MARKET_DATA_TYPE", "live")

    config = IbkrClientConfig.from_env()

    assert config.host == "localhost"
    assert config.port == 4002
    assert config.client_id == 7
    assert config.market_data_type == "live"


def test_data_quality_warning_flag_exists() -> None:
    assert RiskFlag.DATA_QUALITY_WARNING == "data_quality_warning"


def test_connectivity_info_callback_marks_ibkr_app_ready() -> None:
    EClient, EWrapper, _Contract = _load_ibapi()
    app = _IbkrApp(EWrapper=EWrapper, EClient=EClient, logger=logging.getLogger(__name__))

    app.error(-1, 2104, "Market data farm connection is OK:usfarm")

    assert app.connected_event.is_set()


def test_put_strikes_are_selected_nearest_otm_first() -> None:
    strikes = [Decimal("185"), Decimal("190"), Decimal("195"), Decimal("200"), Decimal("205")]

    selected = _select_relevant_strikes(strikes=strikes, spot=Decimal("202"), right="P")

    assert selected == [
        Decimal("200"),
        Decimal("195"),
        Decimal("190"),
        Decimal("185"),
    ]


def test_option_definitions_are_deduped_by_contract_identity() -> None:
    definitions = [
        _OptionDefinition("AAPL", "CBOE", "AAPL", "100", "20260501", Decimal("245"), "P"),
        _OptionDefinition("AAPL", "SMART", "AAPL", "100", "20260501", Decimal("245"), "P"),
        _OptionDefinition("AAPL", "AMEX", "AAPL", "100", "20260501", Decimal("245"), "P"),
        _OptionDefinition("AAPL", "SMART", "AAPL", "100", "20260501", Decimal("240"), "P"),
    ]

    deduped = _dedupe_option_definitions(definitions)

    assert len(deduped) == 2
    assert deduped[0].exchange == "SMART"
    assert [definition.strike for definition in deduped] == [
        Decimal("245"),
        Decimal("240"),
    ]
