"""Universe discovery: build the list of symbols to scan from config and optional sources.

Structure allows S&P 500 / Nasdaq-100 sources to be plugged in later;
those stubs return empty lists for now.
"""
from __future__ import annotations

from configuration import ScanConfig, UniverseDiscoveryConfig

# Well-known leveraged/inverse ETFs that should be excluded by default.
# This list covers common 2x/3x products; it is intentionally conservative.
KNOWN_LEVERAGED_ETFS: frozenset[str] = frozenset(
    {
        # 3x equity
        "TQQQ", "SQQQ", "UPRO", "SPXU", "SPXS", "UDOW", "SDOW",
        "MIDU", "MIDZ", "TNA", "TZA",
        # 2x equity
        "SSO", "SDS", "QLD", "QID", "DDM", "DXD", "MVV", "MZZ",
        "SAA", "SDD", "ROM", "REW", "UYG", "SKF",
        # Leveraged sector / thematic
        "LABU", "LABD", "FAS", "FAZ", "NUGT", "DUST", "JNUG", "JDST",
        "ERX", "ERY", "GUSH", "DRIP", "NAIL", "CURE", "DFEN",
        "WANT", "PILL", "BULZ", "BERZ", "FNGU", "FNGD",
        "TECL", "TECS", "DPST", "BNKU", "HIBL", "HIBS",
        "SOXL", "SOXS", "UBOT",
        # Leveraged volatility / commodity
        "UVXY", "SVXY", "UCO", "SCO", "BOIL", "KOLD",
    }
)


def build_universe(scan_config: ScanConfig) -> list[str]:
    """Return the deduplicated list of symbols to scan.

    Resolution order (when universe_discovery is enabled):
    1. Configured universe (if use_configured_universe_first=True).
    2. ETF list (if include_etfs=True) — placeholder, returns empty for now.
    3. S&P 500 (if include_sp500=True) — stub, returns empty for now.
    4. Nasdaq-100 (if include_nasdaq100=True) — stub, returns empty for now.

    When universe_discovery is disabled, falls back to configured universe only.
    """
    disc = scan_config.universe_discovery
    symbols: list[str] = []

    configured = _normalize(scan_config.universe)

    if not disc.enabled:
        return configured

    if disc.use_configured_universe_first:
        symbols.extend(configured)

    if disc.include_etfs:
        symbols.extend(_etf_universe())

    if disc.include_sp500:
        symbols.extend(_sp500_universe())

    if disc.include_nasdaq100:
        symbols.extend(_nasdaq100_universe())

    if not disc.use_configured_universe_first:
        # Append configured universe at end if not already first
        symbols.extend(configured)

    unique = list(dict.fromkeys(symbols))

    if disc.exclude_leveraged_etfs:
        unique = [s for s in unique if s not in KNOWN_LEVERAGED_ETFS]

    if disc.max_symbols is not None:
        unique = unique[: disc.max_symbols]

    return unique


def filter_by_volume(
    symbols: list[str],
    quotes: dict,
    min_volume: int,
) -> list[str]:
    """Return symbols whose underlying volume meets the minimum threshold.

    ``quotes`` is expected to be a dict mapping symbol -> UnderlyingQuote.
    Symbols not present in quotes are kept (conservative default).
    """
    result: list[str] = []
    for symbol in symbols:
        quote = quotes.get(symbol)
        if quote is None:
            result.append(symbol)
            continue
        vol = getattr(quote, "volume", None) or getattr(quote, "average_volume", None)
        if vol is None or vol >= min_volume:
            result.append(symbol)
    return result


# ---------------------------------------------------------------------------
# Source stubs — replace with real implementations when ready
# ---------------------------------------------------------------------------


def _etf_universe() -> list[str]:
    """Broad, non-leveraged ETF symbols available for CSP scanning.

    Stub: returns a curated shortlist. Replace with a dynamic feed later.
    """
    return [
        "SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "XLF", "XLE", "XLV",
        "XLK", "XLI", "XLB", "XLU", "XLRE", "XLP", "XLY", "XLC",
        "EEM", "EFA", "VNQ", "AGG", "LQD", "HYG",
    ]


def _sp500_universe() -> list[str]:
    """S&P 500 constituent symbols.

    Stub: returns empty list. Plug in a data source (e.g., Wikipedia scrape,
    broker screener, or static CSV) when ready.
    """
    return []


def _nasdaq100_universe() -> list[str]:
    """Nasdaq-100 constituent symbols.

    Stub: returns empty list. Replace with a live feed when ready.
    """
    return []


def _normalize(symbols: list[str]) -> list[str]:
    return list(
        dict.fromkeys(
            s.strip().upper()
            for s in symbols
            if s and s.strip()
        )
    )
