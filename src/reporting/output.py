from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

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

    ranked_rows = [_decision_to_row(decision) for decision in sizing_result.decisions]
    rejected_rows = [
        row
        for row in ranked_rows
        if row["eligibility_status"] == EligibilityStatus.REJECTED.value
        or row["suggested_contracts"] == 0
    ]

    target_summary = {
        "target_weekly_premium": float(sizing_result.target_weekly_premium),
        "premium_captured": float(sizing_result.premium_captured),
        "target_achieved_pct": sizing_result.target_achieved_pct,
        "target_met": sizing_result.target_met,
        "unused_cash": float(sizing_result.unused_cash),
    }

    ranked_output = {
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


def _decision_to_row(decision: PositionSizingDecision) -> dict[str, Any]:
    trade = decision.ranked_trade
    candidate = trade.candidate
    option = candidate.option
    underlying = candidate.underlying
    return {
        "rank": trade.rank,
        "symbol": underlying.symbol,
        "option_symbol": option.symbol,
        "expiration_date": option.expiration_date.date().isoformat(),
        "strike": _json_value(option.strike),
        "bid": _json_value(option.bid),
        "ask": _json_value(option.ask),
        "delta": _json_value(option.delta),
        "implied_volatility": _json_value(option.implied_volatility),
        "open_interest": option.open_interest,
        "volume": option.volume,
        "portfolio_value": _json_value(_portfolio_value(decision)),
        "free_cash": _json_value(_free_cash(decision)),
        "probability_of_profit": _note_float(candidate.notes, "modeled_pop"),
        "annualized_return": _note_float(candidate.notes, "annualized_return"),
        "break_even": _note_float(candidate.notes, "break_even"),
        "ranking_mode_used": trade.ranking_mode_used,
        "pop_score": _json_value(trade.pop_score),
        "return_score": _json_value(trade.return_score),
        "liquidity_score": _json_value(trade.liquidity_score),
        "premium_score": _json_value(trade.premium_score),
        "final_score": _json_value(trade.final_score),
        "eligibility_status": trade.eligibility_status.value,
        "risk_flags": [flag.value for flag in candidate.risk_flags],
        "collateral_per_contract": _json_value(decision.collateral_per_contract),
        "max_allowed_contracts_by_ticker": decision.max_allowed_contracts_by_ticker,
        "suggested_contracts": decision.suggested_contracts,
        "capital_required": _json_value(decision.capital_required),
        "skipped": decision.skipped,
        "skip_reason": decision.skip_reason,
        "rationale": trade.rationale,
        # Target fields
        "target_eligible": decision.target_eligible,
        "target_skip_reason": decision.target_skip_reason,
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
