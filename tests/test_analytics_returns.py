from math import isclose

from analytics.returns import (
    annualized_return,
    break_even,
    distance_to_break_even_pct,
    distance_to_strike_pct,
)


def test_break_even_subtracts_premium_from_strike() -> None:
    assert break_even(100, 2.5) == 97.5


def test_break_even_fails_safely_for_invalid_inputs() -> None:
    assert break_even(0, 1) is None
    assert break_even(100, -1) is None
    assert break_even("bad", 1) is None


def test_annualized_return_uses_collateral_and_dte() -> None:
    result = annualized_return(premium=250, collateral=10000, days_to_expiry=30)

    assert result is not None
    assert isclose(result, 0.3041666667)


def test_annualized_return_fails_safely_for_invalid_inputs() -> None:
    assert annualized_return(250, 0, 30) is None
    assert annualized_return(250, 10000, 0) is None
    assert annualized_return(-1, 10000, 30) is None


def test_distance_to_strike_pct_uses_spot_as_denominator() -> None:
    assert distance_to_strike_pct(100, 95) == 5


def test_distance_to_break_even_pct_uses_spot_as_denominator() -> None:
    assert distance_to_break_even_pct(100, 92.5) == 7.5


def test_distance_functions_fail_safely_for_invalid_inputs() -> None:
    assert distance_to_strike_pct(0, 95) is None
    assert distance_to_break_even_pct(100, 0) is None
