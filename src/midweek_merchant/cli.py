"""`mm` command-line interface."""

from __future__ import annotations

import json
import logging

import typer

from midweek_merchant.config import get_settings

app = typer.Typer(add_completion=False, help="Midweek Merchant: FPL forecaster and optimiser")
diagnose_app = typer.Typer(help="Diagnostics")
app.add_typer(diagnose_app, name="diagnose")


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


@app.command()
def forecast(horizon: int = typer.Option(None, help="Gameweeks to project")) -> None:
    """Project expected points for every player over the horizon."""
    from midweek_merchant.forecast import run_forecast

    fc = run_forecast(get_settings(), horizon=horizon)
    g = fc.projections[fc.projections["gw"] == fc.next_gw].nlargest(15, "xpts")
    typer.echo(f"GW{fc.next_gw} top projections:")
    for r in g.itertuples():
        typer.echo(
            f"  {r.name:<18} {r.team_short:<4} {r.position}  £{r.now_cost / 10:.1f}  {r.fixtures:<14} "
            f"{r.xpts:5.2f}"
        )


@app.command("best-squad")
def best_squad(budget: float = typer.Option(100.0, help="Budget in £m")) -> None:
    """Best squad for each gameweek and the best wildcard squad over the horizon."""
    from midweek_merchant import service

    s = get_settings()
    data = service.best_squads(s, budget=int(round(budget * 10)))
    service.save_best_squads(s, data)
    for gw, wk in data["per_gw"].items():
        names = ", ".join(f"{p['name']}" for p in wk["lineup"])
        typer.echo(f"GW{gw}: {wk['xpts']:.1f} xPts  (C) {wk['captain']['name']}  | {names}")
    typer.echo(f"Wildcard squad over horizon: {data['wildcard']['total_xpts']:.1f} xPts")


@app.command()
def plan(
    team_id: int = typer.Option(None, help="FPL entry id (defaults to config/env)"),
    horizon: int = typer.Option(None),
    chips: bool = typer.Option(False, help="Let the solver decide chip usage too (slower)"),
) -> None:
    """Transfer, captaincy and lineup plan for your team."""
    from midweek_merchant import service

    s = get_settings()
    tid = team_id or s.team_id
    if not tid:
        raise typer.BadParameter("Provide --team-id or set FPL_TEAM_ID / team_id in config.yaml")
    state = service.team_state(s, tid)
    proj = service.load_projections(s)
    kw = {"allow_chips": chips}
    if horizon:
        kw["horizon"] = horizon
    pl = service.plan_for_team(s, state, proj, **kw)
    service.save_plan(s, tid, state, pl, proj)
    typer.echo(
        f"{state.name}: bank £{state.bank / 10:.1f}m, FTs {state.free_transfers}, chips {state.chips_available}"
    )
    for n in state.notes:
        typer.echo(f"  note: {n}")
    for wk in service.plan_table(pl, proj):
        moves = (
            ", ".join(
                f"{o['name']} -> {i['name']}"
                for o, i in zip(wk["transfers_out"], wk["transfers_in"], strict=False)
            )
            or "roll"
        )
        typer.echo(
            f"GW{wk['gw']}: {wk['xpts']:.1f} xPts | {moves} | (C) {wk['captain']['name']} "
            f"| chip {wk['chip'] or '-'} | hits {wk['hits']}"
        )


@diagnose_app.command("ft-rule")
def ft_rule(league_id: int = typer.Option(314), pages: int = typer.Option(3)) -> None:
    """Check whether FTs freeze or accrue through Wildcard/Free Hit weeks using real managers."""
    from midweek_merchant.data.fpl_api import FPLClient
    from midweek_merchant.forecast import load_rules
    from midweek_merchant.team.reconstruct import replay_free_transfers

    s = get_settings()
    rules = load_rules(s)
    res = {"accrue": 0, "freeze": 0}
    informative = 0
    with FPLClient(cache_dir=s.raw_dir / "fpl") as c:
        for page in range(1, pages + 1):
            for r in c.league_classic(league_id, page)["standings"]["results"]:
                h = c.entry_history(r["entry"])
                if not any(x["name"] in ("wildcard", "freehit") for x in h["chips"]):
                    continue
                start = min(x["event"] for x in h["current"])
                mm = {
                    k: len(replay_free_transfers(h["current"], h["chips"], start, rules, k)[1]["mismatches"])
                    for k in res
                }
                for k in res:
                    res[k] += mm[k]
                informative += mm["accrue"] != mm["freeze"]
    typer.echo(f"hit-charge mismatches: {res} (managers distinguishing the rules: {informative})")


if __name__ == "__main__":
    app()
