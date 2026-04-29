from __future__ import annotations


def break_even(strike: float | int, premium: float | int) -> float | None:
    """Return put break-even using: break_even = strike - premium.

    Assumes premium is expressed per share, matching the strike unit. Returns
    None when inputs are missing, non-numeric, or negative.
    """
    try:
        strike_value = float(strike)
        premium_value = float(premium)
    except (TypeError, ValueError):
        return None

    if strike_value <= 0 or premium_value < 0:
        return None

    return strike_value - premium_value


def annualized_return(
    premium: float | int,
    collateral: float | int,
    days_to_expiry: float | int,
) -> float | None:
    """Return annualized cash yield using: (premium / collateral) * (365 / DTE).

    Assumes premium and collateral are in the same currency basis. For one
    options contract, both should usually be total dollars, not per-share strike.
    Returns None for missing values, non-positive collateral, or non-positive DTE.
    """
    try:
        premium_value = float(premium)
        collateral_value = float(collateral)
        dte_value = float(days_to_expiry)
    except (TypeError, ValueError):
        return None

    if premium_value < 0 or collateral_value <= 0 or dte_value <= 0:
        return None

    return (premium_value / collateral_value) * (365 / dte_value)


def distance_to_strike_pct(
    underlying_price: float | int,
    strike: float | int,
) -> float | None:
    """Return percent distance from spot to strike: ((spot - strike) / spot) * 100.

    Positive values indicate an out-of-the-money put strike below the underlying.
    Returns None when inputs are missing, non-numeric, or non-positive.
    """
    try:
        spot_value = float(underlying_price)
        strike_value = float(strike)
    except (TypeError, ValueError):
        return None

    if spot_value <= 0 or strike_value <= 0:
        return None

    return ((spot_value - strike_value) / spot_value) * 100


def distance_to_break_even_pct(
    underlying_price: float | int,
    break_even_price: float | int,
) -> float | None:
    """Return percent distance from spot to break-even: ((spot - BE) / spot) * 100.

    Positive values indicate the break-even is below the underlying. Returns None
    when inputs are missing, non-numeric, or non-positive.
    """
    try:
        spot_value = float(underlying_price)
        break_even_value = float(break_even_price)
    except (TypeError, ValueError):
        return None

    if spot_value <= 0 or break_even_value <= 0:
        return None

    return ((spot_value - break_even_value) / spot_value) * 100
