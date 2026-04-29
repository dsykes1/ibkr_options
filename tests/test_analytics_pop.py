from math import isclose

from analytics.pop import delta_proxy_pop, model_pop_above_break_even


def test_delta_proxy_pop_uses_one_minus_absolute_delta() -> None:
    assert delta_proxy_pop(-0.3) == 0.7
    assert delta_proxy_pop(0.2) == 0.8


def test_delta_proxy_pop_fails_safely_for_invalid_delta() -> None:
    assert delta_proxy_pop(None) is None
    assert delta_proxy_pop(1.5) is None


def test_model_pop_above_break_even_uses_lognormal_assumption() -> None:
    result = model_pop_above_break_even(
        underlying_price=100,
        break_even_price=95,
        implied_volatility=0.25,
        days_to_expiry=30,
    )

    assert result is not None
    assert isclose(result, 0.7517, rel_tol=0.001)


def test_model_pop_above_break_even_decreases_as_break_even_rises() -> None:
    lower_break_even = model_pop_above_break_even(100, 95, 0.25, 30)
    higher_break_even = model_pop_above_break_even(100, 99, 0.25, 30)

    assert lower_break_even is not None
    assert higher_break_even is not None
    assert lower_break_even > higher_break_even


def test_model_pop_above_break_even_fails_safely_for_invalid_inputs() -> None:
    assert model_pop_above_break_even(100, 95, 0, 30) is None
    assert model_pop_above_break_even(100, 95, 0.25, 0) is None
    assert model_pop_above_break_even("bad", 95, 0.25, 30) is None
