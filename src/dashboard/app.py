from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from broker.ibkr_client import IbkrClient, IbkrClientConfig
from broker.contracts import same_week_friday
from configuration import load_settings
from strategy.csp_scanner import run_mock_scan


DEFAULT_JSON_PATH = Path("logs/ranked_trades.json")
DEFAULT_CSV_PATH = Path("logs/ranked_trades.csv")
DEFAULT_SETTINGS_PATH = Path("config/settings.yaml")
MIN_PREMIUM_VS_RISKED_PCT_DISPLAY = 0.5
DEFAULT_TARGET_WEEKLY_RETURN_PCT = 0.5
DEFAULT_TARGET_MIN_POP = 0.95
DEFAULT_MAX_DELTA = 0.25

SCAN_RANKING_MODE_KEY = "scan_ranking_mode"
SCAN_TARGET_WEEKLY_RETURN_KEY = "scan_target_weekly_return_pct"
SCAN_TARGET_MIN_POP_KEY = "scan_target_min_pop"
SCAN_MAX_DELTA_KEY = "scan_max_delta"
LAST_SCAN_CONTROLS_KEY = "last_scan_controls"


DISPLAY_COLUMNS = [
    "rank",
    "symbol",
    "expiration_date",
    "strike",
    "market_premium_total",
    "premium_vs_cash_risked_pct",
    "probability_of_profit",
    "annualized_return",
    "final_score",
    "eligibility_status",
    "risk_flags_display",
    "suggested_contracts",
    "capital_required",
    "target_eligible",
]


def main() -> None:
    st.set_page_config(page_title="IBKR Options Dashboard", layout="wide")
    st.title("IBKR Options")
    st.caption("Cash-secured put scan results")

    source_path = _source_selector()
    settings_path = _scan_controls()
    data, target_summary, scan_parameters = _load_results(source_path)
    if data.empty:
        last_console = st.session_state.get("last_scan_console_output")
        last_broker = st.session_state.get("last_scan_broker")
        last_count = st.session_state.get("last_scan_trade_count")
        if last_console is not None:
            st.warning("Last scan completed but returned zero candidates.")
            if last_broker == "ibkr":
                st.info(
                    "IBKR returned no candidates for current filters/expiry/universe. "
                    "Try widening filters (price range, DTE) or confirm market data permissions."
                )
            st.code(last_console)
            if last_count == 0:
                st.caption("No candidate contracts were ranked for this run.")
        else:
            st.warning("No scan results found. Run `python main.py scan` first.")
        return

    filtered = _filters(data)
    sorted_data = _sort_controls(filtered)

    _target_cards(target_summary)
    _summary_cards(sorted_data, settings_path, target_summary, scan_parameters)
    _ranked_table(sorted_data)
    _score_breakdown_chart(sorted_data)


def _source_selector() -> Path:
    if "results_file" not in st.session_state:
        st.session_state["results_file"] = ""

    available_paths = [
        path for path in [DEFAULT_JSON_PATH, DEFAULT_CSV_PATH] if path.exists()
    ]
    default_path = available_paths[0] if available_paths else DEFAULT_JSON_PATH
    current_path = st.session_state["results_file"] or str(default_path)

    with st.sidebar:
        st.header("Results")
        selected_path = st.text_input("File", value=current_path)

    st.session_state["results_file"] = selected_path

    return Path(selected_path)


def _scan_controls() -> Path:
    settings_preview = None
    ranking_mode_options = ["ultra_safe", "capital_efficient"]

    with st.sidebar:
        st.header("Scan")
        settings_path = Path(
            st.text_input("Settings", value=str(DEFAULT_SETTINGS_PATH))
        )
        try:
            settings_preview = load_settings(settings_path)
            ranking_mode_options = _enabled_ranking_modes(settings_preview)
        except Exception:
            settings_preview = None

        default_controls = _default_scan_controls(
            settings_preview,
            ranking_mode_options=ranking_mode_options,
        )
        reset_controls = st.button("Reset to config defaults", use_container_width=True)
        if reset_controls:
            _set_scan_control_state(default_controls)

        _ensure_scan_control_state(default_controls)

        selected_ranking_mode = st.selectbox(
            "Ranking Mode",
            options=ranking_mode_options,
            index=ranking_mode_options.index(st.session_state[SCAN_RANKING_MODE_KEY])
            if st.session_state[SCAN_RANKING_MODE_KEY] in ranking_mode_options
            else 0,
            key=SCAN_RANKING_MODE_KEY,
        )
        if settings_preview is not None:
            mode_default_delta = _default_max_delta_for_mode(
                settings_preview,
                selected_ranking_mode,
            )
            if st.session_state.get(SCAN_MAX_DELTA_KEY) is None:
                st.session_state[SCAN_MAX_DELTA_KEY] = mode_default_delta

        target_weekly_return_pct = st.number_input(
            "Target premium vs strike (%)",
            min_value=0.0,
            max_value=10.0,
            step=0.05,
            key=SCAN_TARGET_WEEKLY_RETURN_KEY,
            help=(
                "Minimum premium as a percent of strike/cash risked for a trade to count "
                "toward the weekly target."
            ),
        )
        target_min_pop = st.slider(
            "Target minimum POP",
            min_value=0.0,
            max_value=1.0,
            step=0.01,
            key=SCAN_TARGET_MIN_POP_KEY,
            help="Minimum probability of profit for a trade to count toward the weekly target.",
        )
        max_delta = st.slider(
            "Max delta",
            min_value=0.01,
            max_value=1.0,
            step=0.01,
            key=SCAN_MAX_DELTA_KEY,
            help="Maximum absolute short-put delta allowed during candidate evaluation.",
        )
        broker_name = st.selectbox("Broker", options=["ibkr", "mock"], index=0)
        expiration_date = st.date_input(
            "Expiration",
            value=same_week_friday(date.today()),
        )
        run_scan = st.button("Run Scan", type="primary", use_container_width=True)

    if not run_scan:
        return settings_path

    try:
        with st.spinner(f"Running {broker_name} scan..."):
            settings = load_settings(settings_path)
            settings = _apply_scan_overrides(
                settings=settings,
                ranking_mode=selected_ranking_mode,
                target_weekly_return_pct=target_weekly_return_pct,
                target_min_pop=target_min_pop,
                max_delta=max_delta,
            )
            broker = (
                IbkrClient(
                    IbkrClientConfig(
                        host=settings.ibkr.host,
                        port=settings.ibkr.port,
                        client_id=settings.ibkr.client_id,
                        market_data_type=settings.market_data.default_type,
                    )
                )
                if broker_name == "ibkr"
                else None
            )
            result = run_mock_scan(
                settings,
                broker=broker,
                expiration_date=expiration_date,
            )
    except Exception as exc:
        st.session_state["last_scan_console_output"] = None
        st.session_state["last_scan_broker"] = broker_name
        st.session_state["last_scan_trade_count"] = 0
        st.error(f"Scan failed: {exc}")
        st.stop()

    st.session_state["last_scan_console_output"] = result.console_output
    st.session_state["last_scan_broker"] = broker_name
    st.session_state["last_scan_trade_count"] = len(result.sizing_result.decisions)
    st.session_state["results_file"] = str(result.report_paths.ranked_json)
    st.session_state[LAST_SCAN_CONTROLS_KEY] = {
        "ranking_mode": selected_ranking_mode,
        "target_weekly_return_pct": target_weekly_return_pct,
        "target_min_pop": target_min_pop,
        "max_delta": max_delta,
    }

    st.success("Scan complete.")
    st.code(result.console_output)
    st.rerun()
    return settings_path


def _apply_scan_overrides(
    *,
    settings,
    ranking_mode: str,
    target_weekly_return_pct: float,
    target_min_pop: float,
    max_delta: float,
):
    selected_mode = settings.scanner.ranking_modes[ranking_mode]
    return settings.model_copy(
        update={
            "scanner": settings.scanner.model_copy(
                update={
                    "ranking_mode": ranking_mode,
                    "ranking_modes": {
                        **settings.scanner.ranking_modes,
                        ranking_mode: selected_mode.model_copy(
                            update={"max_delta": max_delta}
                        ),
                    },
                    "portfolio_targets": settings.scanner.portfolio_targets.model_copy(
                        update={
                            "weekly_return_target_pct": target_weekly_return_pct,
                            "min_pop": target_min_pop,
                        }
                    ),
                }
            )
        }
    )


def _default_scan_controls(settings_preview, *, ranking_mode_options: list[str]) -> dict[str, float | str]:
    if settings_preview is None:
        return {
            "ranking_mode": ranking_mode_options[0],
            "target_weekly_return_pct": DEFAULT_TARGET_WEEKLY_RETURN_PCT,
            "target_min_pop": DEFAULT_TARGET_MIN_POP,
            "max_delta": DEFAULT_MAX_DELTA,
        }

    ranking_mode = settings_preview.scanner.ranking_mode
    if ranking_mode not in ranking_mode_options:
        ranking_mode = ranking_mode_options[0]

    return {
        "ranking_mode": ranking_mode,
        "target_weekly_return_pct": float(
            settings_preview.scanner.portfolio_targets.weekly_return_target_pct
        ),
        "target_min_pop": float(settings_preview.scanner.portfolio_targets.min_pop),
        "max_delta": _default_max_delta_for_mode(settings_preview, ranking_mode),
    }


def _default_max_delta_for_mode(settings_preview, ranking_mode: str) -> float:
    mode = settings_preview.scanner.ranking_modes.get(ranking_mode)
    if mode is None or mode.max_delta is None:
        return DEFAULT_MAX_DELTA
    return float(mode.max_delta)


def _ensure_scan_control_state(default_controls: dict[str, float | str]) -> None:
    st.session_state.setdefault(SCAN_RANKING_MODE_KEY, default_controls["ranking_mode"])
    st.session_state.setdefault(
        SCAN_TARGET_WEEKLY_RETURN_KEY,
        default_controls["target_weekly_return_pct"],
    )
    st.session_state.setdefault(SCAN_TARGET_MIN_POP_KEY, default_controls["target_min_pop"])
    st.session_state.setdefault(SCAN_MAX_DELTA_KEY, default_controls["max_delta"])


def _set_scan_control_state(default_controls: dict[str, float | str]) -> None:
    st.session_state[SCAN_RANKING_MODE_KEY] = default_controls["ranking_mode"]
    st.session_state[SCAN_TARGET_WEEKLY_RETURN_KEY] = default_controls["target_weekly_return_pct"]
    st.session_state[SCAN_TARGET_MIN_POP_KEY] = default_controls["target_min_pop"]
    st.session_state[SCAN_MAX_DELTA_KEY] = default_controls["max_delta"]


def _active_scan_controls(
    settings_path: Path,
    scan_parameters: dict,
) -> dict[str, float | str]:
    controls = st.session_state.get(LAST_SCAN_CONTROLS_KEY)
    if controls is not None:
        return controls

    if scan_parameters:
        return {
            "ranking_mode": scan_parameters.get("ranking_mode", "ultra_safe"),
            "target_weekly_return_pct": scan_parameters.get(
                "target_weekly_return_pct",
                DEFAULT_TARGET_WEEKLY_RETURN_PCT,
            ),
            "target_min_pop": scan_parameters.get(
                "target_min_pop",
                DEFAULT_TARGET_MIN_POP,
            ),
            "max_delta": scan_parameters.get("max_delta", DEFAULT_MAX_DELTA),
        }

    try:
        settings = load_settings(settings_path)
    except Exception:
        return {
            "ranking_mode": "ultra_safe",
            "target_weekly_return_pct": DEFAULT_TARGET_WEEKLY_RETURN_PCT,
            "target_min_pop": DEFAULT_TARGET_MIN_POP,
            "max_delta": DEFAULT_MAX_DELTA,
        }

    return _default_scan_controls(
        settings,
        ranking_mode_options=_enabled_ranking_modes(settings),
    )


def _enabled_ranking_modes(settings) -> list[str]:
    enabled_modes = [
        name
        for name, mode_config in settings.scanner.ranking_modes.items()
        if mode_config.enabled
    ]
    return enabled_modes or [settings.scanner.ranking_mode]


def _load_results(path: Path) -> tuple[pd.DataFrame, dict, dict]:
    if not path.exists():
        return pd.DataFrame(), {}, {}

    if path.suffix.lower() == ".csv":
        data = pd.read_csv(path)
        target_summary: dict = {}
        scan_parameters: dict = {}
    else:
        import json as _json
        raw_dict = _json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw_dict, dict) and "trades" in raw_dict:
            data = pd.DataFrame(raw_dict["trades"])
            target_summary = raw_dict.get("target_summary", {})
            scan_parameters = raw_dict.get("scan_parameters", {})
        else:
            data = pd.DataFrame(raw_dict)
            target_summary = {}
            scan_parameters = {}

    if data.empty:
        return data, target_summary, scan_parameters

    data = data.copy()
    data["risk_flags"] = data["risk_flags"].apply(_parse_flags)
    data["risk_flags_display"] = data["risk_flags"].apply(
        lambda flags: ", ".join(flags) if flags else ""
    )
    for column in [
        "probability_of_profit",
        "annualized_return",
        "final_score",
        "pop_score",
        "return_score",
        "liquidity_score",
        "premium_score",
        "market_premium_per_contract",
        "market_premium_total",
        "premium_vs_cash_risked_pct",
        "capital_required",
        "suggested_contracts",
    ]:
        if column in data:
            data[column] = pd.to_numeric(data[column], errors="coerce")

    if "target_eligible" not in data:
        data["target_eligible"] = True

    return data, target_summary, scan_parameters


def _filters(data: pd.DataFrame) -> pd.DataFrame:
    with st.sidebar:
        st.header("Filters")
        ranking_modes = sorted(data["ranking_mode_used"].dropna().unique())
        selected_modes = st.multiselect(
            "Ranking mode",
            options=ranking_modes,
            default=ranking_modes,
        )

        eligibility_values = sorted(data["eligibility_status"].dropna().unique())
        selected_statuses = st.multiselect(
            "Eligibility",
            options=eligibility_values,
            default=eligibility_values,
        )

        all_flags = sorted(
            {
                flag
                for flags in data["risk_flags"]
                for flag in flags
            }
        )
        selected_flags = st.multiselect("Flags", options=all_flags)

        target_eligible_only = st.checkbox("Target-eligible trades only", value=False)
        min_pop = st.slider("Minimum POP", 0.0, 1.0, 0.0, 0.01)
        min_return = st.slider("Minimum annualized return", 0.0, 3.0, 0.0, 0.01)

    filtered = data[
        data["ranking_mode_used"].isin(selected_modes)
        & data["eligibility_status"].isin(selected_statuses)
        & (data["probability_of_profit"].fillna(0) >= min_pop)
        & (data["annualized_return"].fillna(0) >= min_return)
    ]

    # Hard display rule: hide trades that do not meet minimum premium vs risked cash.
    if "premium_vs_cash_risked_pct" in filtered.columns:
        filtered = filtered[
            filtered["premium_vs_cash_risked_pct"].fillna(0)
            >= MIN_PREMIUM_VS_RISKED_PCT_DISPLAY
        ]

    if target_eligible_only and "target_eligible" in filtered.columns:
        filtered = filtered[filtered["target_eligible"].fillna(True)]

    if selected_flags:
        filtered = filtered[
            filtered["risk_flags"].apply(
                lambda flags: any(flag in flags for flag in selected_flags)
            )
        ]

    return filtered


def _sort_controls(data: pd.DataFrame) -> pd.DataFrame:
    with st.sidebar:
        st.header("Sort")
        sort_column = st.selectbox(
            "Column",
            options=[
                "rank",
                "final_score",
                "probability_of_profit",
                "annualized_return",
                "capital_required",
            ],
            index=0,
        )
        descending = st.toggle("Descending", value=False)

    return data.sort_values(sort_column, ascending=not descending, na_position="last")


def _target_cards(target_summary: dict) -> None:
    if not target_summary:
        return
    st.subheader("Weekly Premium Target")
    weekly_target = target_summary.get("target_weekly_premium", 0)
    captured = target_summary.get("premium_captured", 0)
    achieved_pct = target_summary.get("target_achieved_pct", 0)
    target_met = target_summary.get("target_met", False)
    unused_cash = target_summary.get("unused_cash", 0)

    cols = st.columns(4)
    cols[0].metric("Weekly Target", f"${weekly_target:,.2f}")
    cols[1].metric(
        "Premium Captured",
        f"${captured:,.2f}",
        delta=f"{achieved_pct:.1f}% of target",
        delta_color="normal" if target_met else "off",
    )
    cols[2].metric("Target Achieved", f"{achieved_pct:.1f}%", delta="Met" if target_met else "Not met")
    cols[3].metric("Unused Cash", f"${unused_cash:,.2f}")


def _summary_cards(
    data: pd.DataFrame,
    settings_path: Path,
    target_summary: dict,
    scan_parameters: dict,
) -> None:
    portfolio_value, free_cash = _load_portfolio_values(data, settings_path, target_summary)
    recommended = data[data["suggested_contracts"].fillna(0) > 0]
    avg_pop = recommended["probability_of_profit"].mean()
    avg_return = recommended["annualized_return"].mean()
    total_capital = recommended["capital_required"].sum()
    unused_cash = max(free_cash - total_capital, 0)
    capital_used_pct = total_capital / free_cash if free_cash else 0
    active_controls = _active_scan_controls(settings_path, scan_parameters)

    cols = st.columns(4)
    cols[0].metric("Portfolio Value", f"${portfolio_value:,.0f}")
    cols[1].metric("Free Cash", f"${free_cash:,.0f}")
    cols[2].metric("Capital Used", f"${total_capital:,.0f}", _format_pct(capital_used_pct))
    cols[3].metric("Unused Cash", f"${unused_cash:,.0f}")

    cols = st.columns(3)
    cols[0].metric("Recommended Trades", f"{len(recommended)}")
    cols[1].metric("Avg POP", _format_pct(avg_pop))
    cols[2].metric("Avg Annualized Return", _format_pct(avg_return))

    st.caption(
        "Active scan thresholds: "
        f"mode={active_controls['ranking_mode']}, "
        f"premium vs strike >= {float(active_controls['target_weekly_return_pct']):.2f}%, "
        f"POP >= {float(active_controls['target_min_pop']):.0%}, "
        f"max delta <= {float(active_controls['max_delta']):.2f}."
    )


def _ranked_table(data: pd.DataFrame) -> None:
    st.subheader("Ranked Trades")
    if data.empty:
        st.info("No trades match the current filters.")
        return

    display_data = data[[column for column in DISPLAY_COLUMNS if column in data]].copy()
    styled = display_data.style.apply(_highlight_flagged_rows, axis=1)
    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        column_config={
            "probability_of_profit": st.column_config.NumberColumn(
                "POP",
                format="%.1%%",
            ),
            "annualized_return": st.column_config.NumberColumn(
                "Annualized Return",
                format="%.1%%",
            ),
            "final_score": st.column_config.NumberColumn("Score", format="%.1f"),
            "capital_required": st.column_config.NumberColumn(
                "Capital",
                format="$%.0f",
            ),
            "market_premium_total": st.column_config.NumberColumn(
                "Premium ($)",
                format="$%.2f",
            ),
            "premium_vs_cash_risked_pct": st.column_config.NumberColumn(
                "Premium vs Risk",
                format="%.2f%%",
            ),
        },
    )


def _score_breakdown_chart(data: pd.DataFrame) -> None:
    st.subheader("Score Breakdown")
    chart_columns = ["pop_score", "return_score", "liquidity_score", "premium_score"]
    if data.empty or not all(column in data for column in chart_columns):
        st.info("No score data available.")
        return

    top_candidates = data.head(5).copy()
    top_candidates["candidate"] = (
        "#"
        + top_candidates["rank"].astype(str)
        + " "
        + top_candidates["symbol"].astype(str)
        + " "
        + top_candidates["strike"].astype(str)
        + "P"
    )
    chart_data = top_candidates.set_index("candidate")[chart_columns]
    st.bar_chart(chart_data, horizontal=True)


def _highlight_flagged_rows(row: pd.Series) -> list[str]:
    flags = row.get("risk_flags_display", "")
    status = row.get("eligibility_status", "")
    if status == "rejected":
        return ["background-color: #fdecec"] * len(row)
    if flags:
        return ["background-color: #fff7dc"] * len(row)
    return [""] * len(row)


def _load_portfolio_values(
    data: pd.DataFrame,
    settings_path: Path,
    target_summary: dict,
) -> tuple[float, float]:
    if "portfolio_value" in target_summary and "free_cash" in target_summary:
        return float(target_summary["portfolio_value"]), float(target_summary["free_cash"])

    if "portfolio_value" in data and data["portfolio_value"].notna().any():
        portfolio_value = float(data["portfolio_value"].dropna().iloc[0])
        free_cash = (
            float(data["free_cash"].dropna().iloc[0])
            if "free_cash" in data and data["free_cash"].notna().any()
            else portfolio_value
        )
        return portfolio_value, free_cash

    try:
        settings = load_settings(settings_path)
    except Exception:
        return 0, 0

    account_size = float(settings.scanner.account_size)
    return account_size, account_size


def _parse_flags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(flag) for flag in value]

    if pd.isna(value) or value == "":
        return []

    if isinstance(value, str):
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return [flag.strip() for flag in value.split(",") if flag.strip()]

        if isinstance(parsed, list):
            return [str(flag) for flag in parsed]

    return []


def _format_pct(value: float) -> str:
    if pd.isna(value):
        return "0.0%"

    return f"{value:.1%}"


if __name__ == "__main__":
    main()
