from __future__ import annotations

from configuration import ScanConfig


DEFAULT_MOCK_UNIVERSE = ["AAPL", "MSFT", "SPY", "TQQQ"]


def load_universe(scan_config: ScanConfig) -> list[str]:
    """Return normalized ticker symbols for the current scan."""
    symbols = scan_config.universe or DEFAULT_MOCK_UNIVERSE
    return list(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip()))
