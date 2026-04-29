"""Tests for universe discovery module."""
from __future__ import annotations

import pytest

from configuration import RankingModeConfig, ScanConfig, UniverseDiscoveryConfig
from data.universe_discovery import (
    KNOWN_LEVERAGED_ETFS,
    build_universe,
    filter_by_volume,
)
from data.models import UnderlyingQuote
from decimal import Decimal


def _scan_config(
    *,
    universe: list[str] | None = None,
    discovery: UniverseDiscoveryConfig | None = None,
) -> ScanConfig:
    return ScanConfig(
        account_size=50_000,
        max_positions=5,
        max_per_ticker_exposure=25_000,
        ranking_modes={
            "ultra_safe": RankingModeConfig(name="ultra_safe"),
            "capital_efficient": RankingModeConfig(name="capital_efficient"),
        },
        universe=universe or ["AAPL", "MSFT", "SPY"],
        universe_discovery=discovery or UniverseDiscoveryConfig(enabled=False),
    )


def test_discovery_disabled_returns_configured_universe() -> None:
    """When discovery is disabled, build_universe returns configured symbols only."""
    config = _scan_config(universe=["AAPL", "MSFT"])
    result = build_universe(config)
    assert result == ["AAPL", "MSFT"]


def test_discovery_enabled_includes_configured_universe_first() -> None:
    """With use_configured_universe_first=True, configured symbols appear first."""
    disc = UniverseDiscoveryConfig(
        enabled=True,
        use_configured_universe_first=True,
        include_etfs=False,
    )
    config = _scan_config(universe=["AAPL", "MSFT"], discovery=disc)
    result = build_universe(config)
    assert result[0] == "AAPL"
    assert result[1] == "MSFT"


def test_discovery_excludes_leveraged_etfs_by_default() -> None:
    """Leveraged ETFs from known list should be excluded when exclude_leveraged_etfs=True."""
    disc = UniverseDiscoveryConfig(
        enabled=True,
        use_configured_universe_first=True,
        include_etfs=True,
        exclude_leveraged_etfs=True,
    )
    config = _scan_config(universe=["SPY", "TQQQ", "SQQQ"], discovery=disc)
    result = build_universe(config)

    for lev_etf in ["TQQQ", "SQQQ"]:
        assert lev_etf not in result, f"{lev_etf} should be excluded as leveraged ETF"


def test_discovery_keeps_leveraged_etfs_when_flag_off() -> None:
    """TQQQ should survive if exclude_leveraged_etfs=False."""
    disc = UniverseDiscoveryConfig(
        enabled=True,
        use_configured_universe_first=True,
        include_etfs=False,
        exclude_leveraged_etfs=False,
    )
    config = _scan_config(universe=["SPY", "TQQQ"], discovery=disc)
    result = build_universe(config)
    assert "TQQQ" in result


def test_discovery_deduplicates_symbols() -> None:
    """Duplicate symbols (e.g. SPY in both configured and ETF list) appear once."""
    disc = UniverseDiscoveryConfig(
        enabled=True,
        use_configured_universe_first=True,
        include_etfs=True,
        exclude_leveraged_etfs=False,
    )
    config = _scan_config(universe=["SPY", "QQQ"], discovery=disc)
    result = build_universe(config)
    assert result.count("SPY") == 1
    assert result.count("QQQ") == 1


def test_discovery_normalizes_symbols_to_upper() -> None:
    """Symbols should always be uppercased."""
    disc = UniverseDiscoveryConfig(enabled=False)
    config = _scan_config(universe=["aapl", " msft "], discovery=disc)
    result = build_universe(config)
    assert "AAPL" in result
    assert "MSFT" in result


def test_discovery_respects_max_symbols_cap() -> None:
    """max_symbols truncates the universe after dedup."""
    disc = UniverseDiscoveryConfig(
        enabled=True,
        use_configured_universe_first=True,
        include_etfs=False,
        exclude_leveraged_etfs=False,
        max_symbols=2,
    )
    config = _scan_config(universe=["AAPL", "MSFT", "SPY", "GLD"], discovery=disc)
    result = build_universe(config)
    assert len(result) == 2


def test_known_leveraged_etfs_contains_common_products() -> None:
    """Spot-check that the known list contains well-known leveraged ETFs."""
    for symbol in ["TQQQ", "SQQQ", "UPRO", "SPXU", "TNA", "TZA", "UVXY"]:
        assert symbol in KNOWN_LEVERAGED_ETFS


def test_filter_by_volume_removes_low_volume_symbols() -> None:
    """Symbols below min_volume threshold should be excluded."""
    def _quote(symbol: str, volume: int) -> UnderlyingQuote:
        return UnderlyingQuote(symbol=symbol, last_price=Decimal("100"), volume=volume)

    quotes = {
        "AAPL": _quote("AAPL", 1_000_000),
        "LOW": _quote("LOW", 50_000),
        "MED": _quote("MED", 500_000),
    }
    result = filter_by_volume(["AAPL", "LOW", "MED"], quotes, min_volume=100_000)
    assert "AAPL" in result
    assert "MED" in result
    assert "LOW" not in result


def test_filter_by_volume_keeps_symbol_not_in_quotes() -> None:
    """Symbols not present in quotes dict are kept (conservative default)."""
    result = filter_by_volume(["UNKNOWN"], {}, min_volume=1_000_000)
    assert "UNKNOWN" in result


def test_discovery_sp500_stub_returns_empty() -> None:
    """S&P 500 source should contribute symbols."""
    from data.universe_discovery import _sp500_universe
    symbols = _sp500_universe()
    assert symbols
    assert "AAPL" in symbols
    assert "MSFT" in symbols


def test_discovery_nasdaq100_stub_returns_empty() -> None:
    """Nasdaq-100 source should contribute symbols."""
    from data.universe_discovery import _nasdaq100_universe
    symbols = _nasdaq100_universe()
    assert symbols
    assert "AAPL" in symbols
    assert "NVDA" in symbols
