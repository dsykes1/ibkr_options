from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from configuration import ScanConfig
from portfolio.sizing import PositionSizingDecision, PositionSizingResult
from strategy.models import EligibilityStatus, RankedTrade


@dataclass(frozen=True)
class ReportPaths:
    ranked_json: Path
    ranked_csv: Path
    rejected_json: Path
    decision_log: Path


def write_scan_outputs(
    sizing_result: PositionSizingResult,
    decision_log_path: Path,
    scan_config: ScanConfig,
    premium_drop_counts: dict[str, int] | None = None,
    output_dir: Path = Path("logs"),
) -> ReportPaths:
    """Write ranked trade CSV/JSON, rejected JSON, and decision log path metadata."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = ReportPaths(
        ranked_json=output_dir / "ranked_trades.json",
        ranked_csv=output_dir / "ranked_trades.csv",
        rejected_json=output_dir / "rejected_trades.json",
        decision_log=decision_log_path,
    )

    all_rows = [_decision_to_row(decision) for decision in sizing_result.decisions]
    ranked_rows = [row for row in all_rows if row["suggested_contracts"] > 0]
    rejected_rows = [
        row
        for decision, row in zip(sizing_result.decisions, all_rows)
        if decision.ranked_trade.eligibility_status == EligibilityStatus.REJECTED
        or row["suggested_contracts"] == 0
    ]

    target_summary = {
        "target_weekly_premium": float(sizing_result.target_weekly_premium),
        "premium_captured": float(sizing_result.premium_captured),
        "target_achieved_pct": sizing_result.target_achieved_pct,
        "target_met": sizing_result.target_met,
        "unused_cash": float(sizing_result.unused_cash),
        "portfolio_value": float(_portfolio_value(sizing_result)),
        "free_cash": float(_free_cash(sizing_result)),
        "sector_concentration": _capital_concentration(ranked_rows, key="sector"),
        "theme_concentration": _theme_concentration(ranked_rows),
        "premium_drop_counts": premium_drop_counts or {},
    }

    ranked_output = {
        "scan_parameters": _scan_parameters(scan_config),
        "target_summary": target_summary,
        "trades": ranked_rows,
    }

    paths.ranked_json.write_text(
        json.dumps(ranked_output, indent=2),
        encoding="utf-8",
    )
    paths.rejected_json.write_text(
        json.dumps(rejected_rows, indent=2),
        encoding="utf-8",
    )
    _write_csv(paths.ranked_csv, ranked_rows)

    return paths


def summarize_console(
    sizing_result: PositionSizingResult,
    paths: ReportPaths,
    broker_name: str = "broker",
) -> str:
    allocated = [
        decision
        for decision in sizing_result.decisions
        if decision.suggested_contracts > 0
    ]
    rejected = [
        decision
        for decision in sizing_result.decisions
        if decision.ranked_trade.eligibility_status == EligibilityStatus.REJECTED
        or decision.suggested_contracts == 0
    ]
    lines = [
        f"{broker_name} scan complete.",
        f"Portfolio value: ${_portfolio_value(sizing_result):,.2f}",
        f"Free cash: ${_free_cash(sizing_result):,.2f}",
        f"Ranked trades: {len(sizing_result.decisions)}",
        f"Suggested positions: {len(allocated)}",
        f"Rejected/skipped trades: {len(rejected)}",
        f"Total allocated capital: ${sizing_result.total_allocated:,.2f}",
        # Target summary
        f"Weekly premium target: ${sizing_result.target_weekly_premium:,.2f}",
        f"Premium captured: ${sizing_result.premium_captured:,.2f}",
        f"Target achieved: {sizing_result.target_achieved_pct:.1f}%"
        + (" ✓" if sizing_result.target_met else ""),
        f"Unused cash: ${sizing_result.unused_cash:,.2f}",
        f"JSON: {paths.ranked_json}",
        f"CSV: {paths.ranked_csv}",
        f"Rejected JSON: {paths.rejected_json}",
        f"Decision log: {paths.decision_log}",
    ]

    if not sizing_result.target_met and sizing_result.target_weekly_premium > 0:
        lines.append(
            "Target not met: insufficient high-quality candidates to reach weekly premium goal."
        )

    if allocated:
        lines.append("Top suggestions:")
        for decision in allocated[:5]:
            trade = decision.ranked_trade
            candidate = trade.candidate
            lines.append(
                f"  #{trade.rank} {candidate.underlying.symbol} "
                f"{candidate.option.strike}P x{decision.suggested_contracts} "
                f"score={trade.final_score} capital=${decision.capital_required:,.2f}"
            )

    return "\n".join(lines)


def _decision_to_row(
    decision: PositionSizingDecision,
) -> dict[str, Any]:
    trade = decision.ranked_trade
    candidate = trade.candidate
    option = candidate.option
    underlying = candidate.underlying
    suggested_contracts = decision.suggested_contracts
    capital_required = decision.capital_required
    premium_captured = _market_premium_per_contract(decision) * Decimal(suggested_contracts)

    return {
        "rank": trade.rank,
        "symbol": underlying.symbol,
        "option_symbol": option.symbol,
        "expiration_date": option.expiration_date.date().isoformat(),
        "strike": _json_value(option.strike),
        "underlying_price": _json_value(underlying.last_price),
        "bid": _json_value(option.bid),
        "ask": _json_value(option.ask),
        "mid_price": _note_float(candidate.notes, "mid_price"),
        "bid_ask_spread_pct": _note_float(candidate.notes, "bid_ask_spread_pct"),
        "return_premium_basis": _note_string(candidate.notes, "return_premium_basis"),
        "delta": _json_value(option.delta),
        "implied_volatility": _json_value(option.implied_volatility),
        "iv_rank": _note_float(candidate.notes, "iv_rank"),
        "iv_percentile": _note_float(candidate.notes, "iv_percentile"),
        "open_interest": option.open_interest,
        "volume": option.volume,
        "sector": _note_string(candidate.notes, "sector"),
        "themes": _note_list(candidate.notes, "themes"),
        "next_earnings_date": _note_string(candidate.notes, "next_earnings_date"),
        "next_known_event_date": _note_string(candidate.notes, "next_known_event_date"),
        "next_known_event_name": _note_string(candidate.notes, "next_known_event_name"),
        "portfolio_value": _json_value(_portfolio_value(decision)),
        "free_cash": _json_value(_free_cash(decision)),
        "probability_of_profit": _note_float(
            candidate.notes,
            "probability_of_profit",
        )
        or _note_float(candidate.notes, "modeled_pop"),
        "pop_method": _note_string(candidate.notes, "pop_source"),
        "annualized_return": _note_float(candidate.notes, "annualized_return"),
        "break_even": _note_float(candidate.notes, "break_even"),
        "distance_to_strike_pct": _note_float(candidate.notes, "distance_to_strike_pct"),
        "distance_to_break_even_pct": _note_float(
            candidate.notes,
            "distance_to_break_even_pct",
        ),
        "assignment_cost_basis": _note_float(candidate.notes, "assignment_cost_basis"),
        "max_loss_at_assignment_per_contract": _note_float(
            candidate.notes,
            "max_loss_at_assignment",
        ),
        "assignment_plan": _note_string(candidate.notes, "assignment_plan"),
        "ranking_mode_used": trade.ranking_mode_used,
        "pop_score": _json_value(trade.pop_score),
        "return_score": _json_value(trade.return_score),
        "liquidity_score": _json_value(trade.liquidity_score),
        "premium_score": _json_value(trade.premium_score),
        "final_score": _json_value(trade.final_score),
        "risk_flags": [flag.value for flag in candidate.risk_flags],
        "collateral_per_contract": _json_value(decision.collateral_per_contract),
        "max_allowed_contracts_by_ticker": decision.max_allowed_contracts_by_ticker,
        "suggested_contracts": suggested_contracts,
        "capital_required": _json_value(capital_required),
        "portfolio_concentration_pct": _json_value(
            _pct_of_value(capital_required, _portfolio_value(decision))
        ),
        "market_premium_per_contract": _json_value(
            _market_premium_per_contract(decision)
        ),
        "market_premium_total": _json_value(premium_captured),
        "premium_captured": _json_value(premium_captured),
        "premium_vs_cash_risked_pct": _json_value(
            _premium_vs_cash_risked_pct(capital_required, premium_captured)
        ),
        "skipped": decision.skipped,
        "skip_reason": decision.skip_reason,
        "rationale": trade.rationale,
        # Target fields
        "target_eligible": decision.target_eligible,
        "target_skip_reason": decision.target_skip_reason,
    }


def _scan_parameters(scan_config: ScanConfig) -> dict[str, Any]:
    mode_config = scan_config.ranking_modes[scan_config.ranking_mode]
    return {
        "ranking_mode": scan_config.ranking_mode,
        "active_universe": scan_config.active_universe,
        "target_weekly_return_pct": scan_config.portfolio_targets.weekly_return_target_pct,
        "target_min_pop": scan_config.portfolio_targets.min_pop,
        "max_delta": mode_config.max_delta,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)

    return value


def _portfolio_value(value: PositionSizingResult | PositionSizingDecision) -> Decimal:
    snapshot = _snapshot(value)
    if snapshot is None:
        return Decimal("0")

    return snapshot.net_liquidation


def _free_cash(value: PositionSizingResult | PositionSizingDecision) -> Decimal:
    snapshot = _snapshot(value)
    if snapshot is None:
        return Decimal("0")

    return snapshot.free_cash


def _snapshot(value: PositionSizingResult | PositionSizingDecision):
    if isinstance(value, PositionSizingResult):
        return value.portfolio_snapshot

    return value.portfolio_snapshot


def _note_float(notes: list[str], key: str) -> float | None:
    prefix = f"{key}="
    for note in notes:
        if not note.startswith(prefix):
            continue

        raw_value = note.removeprefix(prefix)
        if raw_value in {"None", ""}:
            return None

        try:
            return float(raw_value)
        except ValueError:
            return None

    return None


def _note_string(notes: list[str], key: str) -> str | None:
    prefix = f"{key}="
    for note in notes:
        if not note.startswith(prefix):
            continue

        raw_value = note.removeprefix(prefix)
        if raw_value in {"None", ""}:
            return None

        return raw_value

    return None


def _note_list(notes: list[str], key: str) -> list[str]:
    raw_value = _note_string(notes, key)
    if raw_value is None:
        return []

    return [value for value in (item.strip() for item in raw_value.split(",")) if value]


def _market_premium_per_contract(decision: PositionSizingDecision) -> Decimal:
    option = decision.ranked_trade.candidate.option
    return option.bid * Decimal("100")


def _premium_vs_cash_risked_pct(
    capital_required: Decimal,
    premium_captured: Decimal,
) -> Decimal | None:
    if capital_required <= 0:
        return None

    return (premium_captured / capital_required) * Decimal("100")


def _pct_of_value(value: Decimal, total: Decimal) -> Decimal | None:
    if total <= 0:
        return None

    return (value / total) * Decimal("100")


def _capital_concentration(rows: list[dict[str, Any]], *, key: str) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        label = row.get(key) or "Unknown"
        capital = row.get("capital_required") or 0
        totals[str(label)] = totals.get(str(label), 0.0) + float(capital)

    portfolio_value = _portfolio_value_from_rows(rows)
    if portfolio_value <= 0:
        return totals

    return {
        label: round((capital / portfolio_value) * 100, 2)
        for label, capital in sorted(totals.items())
    }


def _theme_concentration(rows: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        themes = row.get("themes") or ["Unknown"]
        capital = row.get("capital_required") or 0
        for theme in themes:
            totals[str(theme)] = totals.get(str(theme), 0.0) + float(capital)

    portfolio_value = _portfolio_value_from_rows(rows)
    if portfolio_value <= 0:
        return totals

    return {
        label: round((capital / portfolio_value) * 100, 2)
        for label, capital in sorted(totals.items())
    }


def _portfolio_value_from_rows(rows: list[dict[str, Any]]) -> float:
    for row in rows:
        value = row.get("portfolio_value")
        if value:
            return float(value)

    return 0.0
