from __future__ import annotations

from math import erf, log, sqrt


def _normal_cdf(value: float) -> float:
    return 0.5 * (1 + erf(value / sqrt(2)))


def delta_proxy_pop(delta: float | int | None) -> float | None:
    """Return a delta proxy probability of profit using: POP = 1 - abs(delta).

    Assumes option delta is expressed as a decimal between -1 and 1. This is a
    rough heuristic, not a distribution model. Returns None for missing or
    out-of-range deltas.
    """
    try:
        delta_value = float(delta)
    except (TypeError, ValueError):
        return None

    if abs(delta_value) > 1:
        return None

    return 1 - abs(delta_value)


def model_pop_above_break_even(
    underlying_price: float | int,
    break_even_price: float | int,
    implied_volatility: float | int,
    days_to_expiry: float | int,
    risk_free_rate: float | int = 0,
) -> float | None:
    """Return P(S_T > break-even) under a lognormal Black-Scholes assumption.

    Formula:
        z = [ln(S / BE) + (r - 0.5 * sigma^2) * T] / [sigma * sqrt(T)]
        POP = N(z)

    Assumes implied volatility and risk-free rate are annualized decimals, time is
    days / 365, and the underlying follows a lognormal terminal distribution.
    Returns None for missing or non-positive spot, break-even, IV, or DTE.
    """
    try:
        spot_value = float(underlying_price)
        break_even_value = float(break_even_price)
        iv_value = float(implied_volatility)
        dte_value = float(days_to_expiry)
        rate_value = float(risk_free_rate)
    except (TypeError, ValueError):
        return None

    if spot_value <= 0 or break_even_value <= 0 or iv_value <= 0 or dte_value <= 0:
        return None

    years_to_expiry = dte_value / 365
    denominator = iv_value * sqrt(years_to_expiry)
    if denominator <= 0:
        return None

    z_score = (
        log(spot_value / break_even_value)
        + (rate_value - 0.5 * iv_value**2) * years_to_expiry
    ) / denominator
    return _normal_cdf(z_score)
