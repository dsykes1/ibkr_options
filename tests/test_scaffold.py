from pathlib import Path

from typer.testing import CliRunner

from main import app, load_settings
from strategy.models import EligibilityStatus, RiskFlag


def test_load_settings_reads_default_config() -> None:
    settings = load_settings(Path("config/settings.yaml"))

    assert settings.app.name == "ibkr-options"
    assert settings.app.environment == "development"
    assert settings.market_data.default_type == "live"
    assert settings.market_data.reject_if_delayed is True
    assert settings.scanner.account_size == 50000
    assert settings.scanner.ranking_mode == "ultra_safe"
    assert "capital_efficient" in settings.scanner.ranking_modes


def test_scan_command_is_available() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["scan"])

    assert result.exit_code == 0
    assert "Mock scan complete." in result.stdout


def test_domain_enums_are_string_values() -> None:
    assert RiskFlag.LOW_LIQUIDITY == "low_liquidity"
    assert EligibilityStatus.ELIGIBLE == "eligible"
