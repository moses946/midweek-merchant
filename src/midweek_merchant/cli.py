"""`mm` command-line interface."""

from __future__ import annotations

import json
import logging

import typer

from midweek_merchant.config import get_settings

app = typer.Typer(add_completion=False, help="Midweek Merchant: FPL forecaster and optimiser")


@app.callback()
def _main(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


@app.command()
def ingest(
    no_history: bool = typer.Option(False, help="Reuse cached historical tables"),
    no_odds_api: bool = typer.Option(False, help="Skip the-odds-api even if a key is set"),
) -> None:
    """Refresh FPL, historical and odds data."""
    from midweek_merchant.data.ingest import ingest as run

    counts = run(get_settings(), history_refresh=not no_history, use_odds_api=not no_odds_api)
    typer.echo(json.dumps(counts, indent=1))


if __name__ == "__main__":
    app()
