from broker.ibkr_client import IBKR_MARKET_DATA_TYPES, IbkrClientConfig
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
