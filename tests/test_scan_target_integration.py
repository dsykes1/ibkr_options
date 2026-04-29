"""Integration tests for scan + target-progress report fields."""
from __future__ import annotations

import json

from configuration import load_settings
from strategy.csp_scanner import run_mock_scan


def test_scan_report_includes_target_summary_fields(tmp_path) -> None:
    """ranked_trades.json should include target_summary with all required fields."""
    settings = load_settings()
    result = run_mock_scan(settings, output_dir=tmp_path)

    ranked_output = json.loads(result.report_paths.ranked_json.read_text(encoding="utf-8"))
    summary = ranked_output["target_summary"]

    assert "target_weekly_premium" in summary
    assert "premium_captured" in summary
    assert "target_achieved_pct" in summary
    assert "target_met" in summary
    assert "unused_cash" in summary
    assert "portfolio_value" in summary
    assert "free_cash" in summary
    assert isinstance(summary["target_weekly_premium"], (int, float))
    assert isinstance(summary["premium_captured"], (int, float))
    assert summary["target_achieved_pct"] >= 0.0


def test_scan_report_includes_scan_parameters(tmp_path) -> None:
    settings = load_settings()
    result = run_mock_scan(settings, output_dir=tmp_path)

    ranked_output = json.loads(result.report_paths.ranked_json.read_text(encoding="utf-8"))
    scan_parameters = ranked_output["scan_parameters"]

    assert scan_parameters["ranking_mode"] == settings.scanner.ranking_mode
    assert scan_parameters["target_weekly_return_pct"] == settings.scanner.portfolio_targets.weekly_return_target_pct
    assert scan_parameters["target_min_pop"] == settings.scanner.portfolio_targets.min_pop
    assert scan_parameters["max_delta"] == settings.scanner.ranking_modes[settings.scanner.ranking_mode].max_delta


def test_scan_report_trades_include_target_eligible_field(tmp_path) -> None:
    """Each trade row in ranked_trades.json should include target_eligible."""
    settings = load_settings()
    result = run_mock_scan(settings, output_dir=tmp_path)

    ranked_output = json.loads(result.report_paths.ranked_json.read_text(encoding="utf-8"))
    for row in ranked_output["trades"]:
        assert "target_eligible" in row
        assert "market_premium_total" in row
        assert "premium_vs_cash_risked_pct" in row


def test_scan_sizing_result_has_target_fields(tmp_path) -> None:
    """ScanResult.sizing_result should expose all target tracking fields."""
    settings = load_settings()
    result = run_mock_scan(settings, output_dir=tmp_path)

    sr = result.sizing_result
    assert hasattr(sr, "target_weekly_premium")
    assert hasattr(sr, "premium_captured")
    assert hasattr(sr, "target_achieved_pct")
    assert hasattr(sr, "target_met")
    assert hasattr(sr, "unused_cash")
    assert sr.target_weekly_premium >= 0
    assert sr.premium_captured >= 0
    assert sr.unused_cash >= 0


def test_scan_target_weekly_premium_uses_portfolio_value(tmp_path) -> None:
    """target_weekly_premium should be derived from portfolio net_liquidation."""
    settings = load_settings()
    result = run_mock_scan(settings, output_dir=tmp_path)

    sr = result.sizing_result
    snapshot = sr.portfolio_snapshot
    if snapshot is not None:
        expected_target = float(snapshot.net_liquidation) * settings.scanner.portfolio_targets.weekly_return_target_pct / 100
        assert abs(float(sr.target_weekly_premium) - expected_target) < 0.01
