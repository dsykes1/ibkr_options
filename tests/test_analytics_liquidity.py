from math import isclose

from analytics.liquidity import liquidity_score, spread_pct


def test_spread_pct_uses_midpoint_as_denominator() -> None:
    assert isclose(spread_pct(1.0, 1.2), 18.18181818)


def test_spread_pct_fails_safely_for_invalid_prices() -> None:
    assert spread_pct(1.2, 1.0) is None
    assert spread_pct(0, 0) is None
    assert spread_pct("bad", 1.0) is None


def test_liquidity_score_combines_spread_volume_and_open_interest() -> None:
    result = liquidity_score(
        bid=1.0,
        ask=1.1,
        volume=50,
        open_interest=250,
        target_volume=100,
        target_open_interest=500,
        max_spread_pct=20,
    )

    assert isclose(result, 50.95238095)


def test_liquidity_score_caps_volume_and_open_interest_components() -> None:
    assert liquidity_score(1.0, 1.0, 10_000, 10_000) == 100


def test_liquidity_score_fails_safely_for_invalid_inputs() -> None:
    assert liquidity_score(1.2, 1.0, 100, 500) == 0
    assert liquidity_score(1.0, 1.1, 100, 500, target_volume=0) == 0
