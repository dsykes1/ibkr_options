# IBKR Options MVP

Initial Python scaffold for an MVP that will scan IBKR weekly options and recommend cash-secured puts.

Business logic is intentionally not implemented yet. The current project only provides package structure, configuration placeholders, a CLI entry point, a Streamlit placeholder app, and a smoke test.

## Requirements

- Python 3.11+
- IBKR account and API/TWS or IB Gateway setup for future broker integration

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

## CLI

```bash
ibkr-options --help
python main.py scan
```

## Dashboard

```bash
streamlit run src/dashboard/app.py
```

## Tests

```bash
pytest
```

## Project Layout

- `src/broker`: future IBKR connectivity and broker adapters
- `src/data`: market data loading, normalization, and persistence boundaries
- `src/analytics`: option metrics and derived analytics
- `src/strategy`: recommendation rules and screening workflow
- `src/portfolio`: cash, positions, and allocation constraints
- `src/reporting`: summaries and export/report generation
- `src/dashboard`: Streamlit dashboard entry point
- `config`: environment-specific YAML settings
- `logs`: runtime logs
- `tests`: pytest suite
