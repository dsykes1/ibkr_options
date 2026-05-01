from __future__ import annotations

from configuration import load_settings
from dashboard.app import _apply_scan_overrides, _default_scan_controls, _universe_options


def test_apply_scan_overrides_updates_target_thresholds() -> None:
    settings = load_settings()

    updated = _apply_scan_overrides(
        settings=settings,
        ranking_mode="capital_efficient",
        target_weekly_return_pct=0.75,
        target_min_pop=0.9,
        max_delta=0.22,
        active_universe="full",
    )

    assert updated.scanner.ranking_mode == "capital_efficient"
    assert updated.scanner.active_universe == "full"
    assert updated.scanner.portfolio_targets.weekly_return_target_pct == 0.75
    assert updated.scanner.portfolio_targets.min_pop == 0.9
    assert updated.scanner.ranking_modes["capital_efficient"].max_delta == 0.22
    assert settings.scanner.ranking_modes["capital_efficient"].max_delta != 0.22
    assert settings.scanner.portfolio_targets.weekly_return_target_pct != 0.75


def test_default_scan_controls_reads_current_config_values() -> None:
    settings = load_settings()

    defaults = _default_scan_controls(
        settings,
        ranking_mode_options=["ultra_safe", "capital_efficient"],
    )

    assert defaults["ranking_mode"] == settings.scanner.ranking_mode
    assert defaults["target_weekly_return_pct"] == settings.scanner.portfolio_targets.weekly_return_target_pct
    assert defaults["target_min_pop"] == settings.scanner.portfolio_targets.min_pop
    assert defaults["max_delta"] == settings.scanner.ranking_modes[settings.scanner.ranking_mode].max_delta
    assert defaults["active_universe"] == settings.scanner.active_universe


def test_universe_options_include_targeted_and_full() -> None:
    settings = load_settings()

    assert _universe_options(settings) == ["targeted", "full"]
    assert _universe_options(None) == ["targeted", "full"]
