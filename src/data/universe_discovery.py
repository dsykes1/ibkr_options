"""Universe discovery: build the list of symbols to scan from config and optional sources."""
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


# Curated liquid names from S&P 500; maintained in-repo to avoid runtime web calls.
SP500_LIQUID_UNIVERSE: tuple[str, ...] = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK.B", "TSLA", "JPM", "V",
    "UNH", "XOM", "MA", "LLY", "AVGO", "COST", "PG", "HD", "WMT", "MRK",
    "ABBV", "PEP", "KO", "BAC", "ADBE", "CRM", "CVX", "AMD", "ACN", "MCD",
    "CSCO", "NFLX", "TMO", "PFE", "ABT", "INTC", "DIS", "VZ", "CMCSA", "ORCL",
    "QCOM", "NKE", "DHR", "TXN", "PM", "LIN", "WFC", "UPS", "RTX", "HON",
    "SPGI", "BMY", "IBM", "LOW", "AMGN", "GS", "CAT", "SBUX", "INTU", "BLK",
    "SYK", "AMAT", "DE", "GE", "BKNG", "T", "MDT", "LMT", "GILD", "AXP",
    "ADP", "NOW", "ISRG", "PLD", "VRTX", "TJX", "SCHW", "CI", "MU", "MMC",
    "CB", "REGN", "ELV", "SO", "DUK", "COP", "BDX", "ZTS", "PANW", "CME",
    "ICE", "MO", "CL", "EOG", "EQIX", "AON", "NSC", "APD", "ITW", "ETN",
    "MS", "CSX", "FDX", "MAR", "GM", "F", "PYPL", "USB", "PNC", "APTV",
    "TGT", "EMR", "SHW", "MCK", "MPC", "AEP", "PSX", "CCI", "AFL", "ROP",
)


NASDAQ100_UNIVERSE: tuple[str, ...] = (
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "AVGO", "TSLA", "COST",
    "NFLX", "AMD", "ADBE", "PEP", "CSCO", "TMUS", "INTC", "QCOM", "CMCSA", "TXN",
    "AMGN", "INTU", "AMAT", "ISRG", "BKNG", "LRCX", "ADI", "GILD", "MU", "PANW",
    "VRTX", "MELI", "CRWD", "SNPS", "KLAC", "CDNS", "ORLY", "ASML", "MDLZ", "MAR",
    "ADP", "REGN", "ABNB", "CTAS", "SBUX", "CSX", "MNST", "CHTR", "NXPI", "MCHP",
    "WDAY", "PAYX", "KDP", "ROST", "AEP", "PCAR", "MRVL", "EXC", "XEL", "ODFL",
    "IDXX", "FTNT", "FAST", "EA", "VRSK", "BIIB", "TEAM", "LULU", "GEHC", "DLTR",
    "BKR", "KHC", "DDOG", "DASH", "CTSH", "ANSS", "WBD", "ON", "ILMN", "ZS",
    "SIRI", "GFS", "CDW", "FANG", "TTWO", "MDB", "CPRT", "ALGN", "CEG", "PYPL",
    "HON", "DXCM", "MRNA", "SPLK", "WBA", "RIVN", "JD", "PDD", "BIDU", "NTES",
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
# Source lists
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
    """Liquid S&P 500 symbol list bundled with the project."""
    return list(SP500_LIQUID_UNIVERSE)


def _nasdaq100_universe() -> list[str]:
    """Nasdaq-100 symbol list bundled with the project."""
    return list(NASDAQ100_UNIVERSE)


def _normalize(symbols: list[str]) -> list[str]:
    return list(
        dict.fromkeys(
            s.strip().upper()
            for s in symbols
            if s and s.strip()
        )
    )
