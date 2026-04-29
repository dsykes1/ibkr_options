from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


DEFAULT_JSON_PATH = Path("logs/ranked_trades.json")
DEFAULT_CSV_PATH = Path("logs/ranked_trades.csv")


DISPLAY_COLUMNS = [
    "rank",
    "symbol",
    "expiration_date",
    "strike",
    "probability_of_profit",
    "annualized_return",
    "final_score",
    "eligibility_status",
    "risk_flags_display",
    "suggested_contracts",
    "capital_required",
]


def main() -> None:
    st.set_page_config(page_title="IBKR Options Dashboard", layout="wide")
    st.title("IBKR Options")
    st.caption("Cash-secured put scan results")

    source_path = _source_selector()
    data = _load_results(source_path)
    if data.empty:
        st.warning("No scan results found. Run `python main.py scan` first.")
        return

    filtered = _filters(data)
    sorted_data = _sort_controls(filtered)

    _summary_cards(sorted_data)
    _ranked_table(sorted_data)
    _score_breakdown_chart(sorted_data)


def _source_selector() -> Path:
    available_paths = [
        path for path in [DEFAULT_JSON_PATH, DEFAULT_CSV_PATH] if path.exists()
    ]
    default_path = available_paths[0] if available_paths else DEFAULT_JSON_PATH

    with st.sidebar:
        st.header("Results")
        selected_path = st.text_input("File", value=str(default_path))

    return Path(selected_path)


@st.cache_data(show_spinner=False)
def _load_results(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    if path.suffix.lower() == ".csv":
        data = pd.read_csv(path)
    else:
        data = pd.read_json(path)

    if data.empty:
        return data

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
        "capital_required",
        "suggested_contracts",
    ]:
        if column in data:
            data[column] = pd.to_numeric(data[column], errors="coerce")

    return data


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

        min_pop = st.slider("Minimum POP", 0.0, 1.0, 0.0, 0.01)
        min_return = st.slider("Minimum annualized return", 0.0, 3.0, 0.0, 0.01)

    filtered = data[
        data["ranking_mode_used"].isin(selected_modes)
        & data["eligibility_status"].isin(selected_statuses)
        & (data["probability_of_profit"].fillna(0) >= min_pop)
        & (data["annualized_return"].fillna(0) >= min_return)
    ]

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


def _summary_cards(data: pd.DataFrame) -> None:
    recommended = data[data["suggested_contracts"].fillna(0) > 0]
    avg_pop = data["probability_of_profit"].mean()
    avg_return = data["annualized_return"].mean()
    total_capital = recommended["capital_required"].sum()

    cols = st.columns(4)
    cols[0].metric("Avg POP", _format_pct(avg_pop))
    cols[1].metric("Avg Annualized Return", _format_pct(avg_return))
    cols[2].metric("Total Capital Used", f"${total_capital:,.0f}")
    cols[3].metric("Recommended Trades", f"{len(recommended)}")


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
