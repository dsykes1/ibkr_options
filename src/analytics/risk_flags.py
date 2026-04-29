from __future__ import annotations

from strategy.models import RiskFlag


DEFAULT_LEVERAGED_ETF_SYMBOLS = frozenset(
    {
        "BOIL",
        "FAS",
        "LABU",
        "NUGT",
        "SDS",
        "SOXL",
        "SPXL",
        "SPXS",
        "SQQQ",
        "TNA",
        "TQQQ",
        "UDOW",
        "UPRO",
        "UVXY",
        "YINN",
    }
)


def identify_risk_flags(
    *,
    symbol: str,
    liquidity_score: float | int | None,
    spread_pct: float | int | None,
    underlying_price: float | int | None,
    implied_volatility: float | int | None,
    ticker_exposure: float | int | None,
    max_per_ticker_exposure: float | int | None,
    min_liquidity_score: float = 50,
    max_spread_pct: float = 20,
    min_underlying_price: float = 10,
    high_iv_threshold: float = 0.8,
    leveraged_etf_symbols: set[str] | frozenset[str] = DEFAULT_LEVERAGED_ETF_SYMBOLS,
) -> list[RiskFlag]:
    """Return deterministic risk flags from primitive screening inputs.

    Assumptions:
        LOW_LIQUIDITY when score is below min_liquidity_score or missing.
        WIDE_SPREAD when spread percent is above max_spread_pct or missing.
        LOW_PRICE_STOCK when spot is below min_underlying_price or missing.
        LEVERAGED_ETF when symbol is in a configurable leveraged ETF list.
        HIGH_IV when annualized IV is above high_iv_threshold.
        CONCENTRATION_RISK when ticker exposure exceeds max allowed exposure.

    Missing values are treated conservatively for liquidity, spread, and price.
    Missing IV or exposure do not trigger their flags because the risk cannot be
    confirmed from the supplied inputs.
    """
    flags: list[RiskFlag] = []

    if _as_float(liquidity_score) is None or _as_float(liquidity_score) < min_liquidity_score:
        flags.append(RiskFlag.LOW_LIQUIDITY)

    spread_value = _as_float(spread_pct)
    if spread_value is None or spread_value > max_spread_pct:
        flags.append(RiskFlag.WIDE_SPREAD)

    price_value = _as_float(underlying_price)
    if price_value is None or price_value < min_underlying_price:
        flags.append(RiskFlag.LOW_PRICE_STOCK)

    if symbol.upper() in leveraged_etf_symbols:
        flags.append(RiskFlag.LEVERAGED_ETF)

    iv_value = _as_float(implied_volatility)
    if iv_value is not None and iv_value > high_iv_threshold:
        flags.append(RiskFlag.HIGH_IV)

    exposure_value = _as_float(ticker_exposure)
    max_exposure_value = _as_float(max_per_ticker_exposure)
    if (
        exposure_value is not None
        and max_exposure_value is not None
        and max_exposure_value >= 0
        and exposure_value > max_exposure_value
    ):
        flags.append(RiskFlag.CONCENTRATION_RISK)

    return flags


def _as_float(value: float | int | None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
