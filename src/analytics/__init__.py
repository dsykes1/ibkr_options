"""Analytics package."""

from analytics.liquidity import liquidity_score, spread_pct
from analytics.pop import delta_proxy_pop, model_pop_above_break_even
from analytics.returns import (
    annualized_return,
    break_even,
    distance_to_break_even_pct,
    distance_to_strike_pct,
)
from analytics.risk_flags import identify_risk_flags

__all__ = [
    "annualized_return",
    "break_even",
    "delta_proxy_pop",
    "distance_to_break_even_pct",
    "distance_to_strike_pct",
    "identify_risk_flags",
    "liquidity_score",
    "model_pop_above_break_even",
    "spread_pct",
]
