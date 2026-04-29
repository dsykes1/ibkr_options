from __future__ import annotations


def spread_pct(bid: float | int, ask: float | int) -> float | None:
    """Return bid/ask spread percent using: ((ask - bid) / midpoint) * 100.

    The midpoint is (bid + ask) / 2. Returns None when prices are missing,
    non-numeric, negative, crossed, or have a zero midpoint.
    """
    try:
        bid_value = float(bid)
        ask_value = float(ask)
    except (TypeError, ValueError):
        return None

    midpoint = (bid_value + ask_value) / 2
    if bid_value < 0 or ask_value < 0 or ask_value < bid_value or midpoint <= 0:
        return None

    return ((ask_value - bid_value) / midpoint) * 100


def liquidity_score(
    bid: float | int,
    ask: float | int,
    volume: int | None,
    open_interest: int | None,
    target_volume: int = 100,
    target_open_interest: int = 500,
    max_spread_pct: float = 20,
) -> float:
    """Return a 0-100 liquidity score from spread, volume, and open interest.

    Formula:
        score = 100 * (
            0.40 * spread_component
            + 0.30 * volume_component
            + 0.30 * open_interest_component
        )

    Assumes tighter spreads are better, while volume and open interest are better
    up to configurable targets. Missing volume or open interest is treated as 0.
    Invalid prices or thresholds return 0.
    """
    if target_volume <= 0 or target_open_interest <= 0 or max_spread_pct <= 0:
        return 0

    current_spread_pct = spread_pct(bid, ask)
    if current_spread_pct is None:
        return 0

    safe_volume = max(volume or 0, 0)
    safe_open_interest = max(open_interest or 0, 0)

    spread_component = max(0, 1 - (current_spread_pct / max_spread_pct))
    volume_component = min(safe_volume / target_volume, 1)
    open_interest_component = min(safe_open_interest / target_open_interest, 1)

    return 100 * (
        0.40 * spread_component
        + 0.30 * volume_component
        + 0.30 * open_interest_component
    )
