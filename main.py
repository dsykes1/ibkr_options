from pathlib import Path
from typing import Literal

import typer

from broker.ibkr_client import IbkrClient, IbkrClientConfig
from configuration import load_settings
from strategy.csp_scanner import run_mock_scan


app = typer.Typer(
    help="IBKR weekly options scanner MVP."
)


@app.callback()
def main() -> None:
    """Run IBKR options scanner commands."""


@app.command()
def scan(
    settings_file: Path = typer.Option(
        Path("config/settings.yaml"),
        "--settings-file",
        "-s",
        help="Path to the YAML settings file.",
    ),
    broker_name: Literal["mock", "ibkr"] = typer.Option(
        "mock",
        "--broker",
        "-b",
        help="Broker adapter to use.",
    ),
) -> None:
    """Run the cash-secured put scanner."""
    settings = load_settings(settings_file)
    typer.echo(
        f"{settings.app.name} scan starting "
        f"({settings.app.environment}, log level {settings.app.log_level})."
    )
    typer.echo(f"Ranking mode: {settings.scanner.ranking_mode}.")
    typer.echo(f"Broker: {broker_name}.")
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
    result = run_mock_scan(settings, broker=broker)
    typer.echo(result.console_output)


if __name__ == "__main__":
    app()
