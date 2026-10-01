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


@app.command()
def league(
    league_id: int = typer.Option(None, help="Classic league id (defaults to config/env)"),
    team_id: int = typer.Option(None, help="Your FPL entry id (defaults to config/env)"),
    horizon: int = typer.Option(3),
) -> None:
    """Mini-league analysis: rivals, EO, and plans ranked by chance of winning the league."""
    from midweek_merchant import service
    from midweek_merchant.data.store import write_output

    s = get_settings()
    lid, tid = league_id or s.league_id, team_id or s.team_id
    if not (lid and tid):
        raise typer.BadParameter("Provide --league-id and --team-id (or FPL_LEAGUE_ID / FPL_TEAM_ID)")
    rep = service.league_report(s, lid, tid, horizon=horizon)
    write_output(s, f"league_{lid}.json", rep)
    typer.echo(f"{rep['league']['name']}: {rep['advice']}")
    for p in sorted(rep["plans"], key=lambda r: -r["p_first_season"]):
        typer.echo(
            f"  {p['type']:<24} {p['this_week']:<45} (C) {p['captain']:<14} "
            f"P(win league) {p['p_first_season']:.1%}"
        )


@app.command()
def backtest(
    season: str = typer.Option("2025-26"), every: int = typer.Option(1, help="Use every Nth GW")
) -> None:
    """Rolling-origin backtest of the xPts model on a past season."""
    from midweek_merchant.backtest.run import run_and_save

    summ = run_and_save(get_settings(), season, gws=list(range(4, 39, every)))
    for m in summ["metrics"]:
        typer.echo(
            f"{m['subset']:<32} {m['predictor']:<14} RMSE {m['rmse']:.3f}  MAE {m['mae']:.3f}  "
            f"Spearman {m['spearman_within_pos']:.3f}"
        )


@app.command()
def refresh(
    publish_dir: str = typer.Option(None, help="Write the publishable bundle here (for the data branch)"),
    backtest_max_age_days: float = typer.Option(7.0, help="Re-run the backtest when older than this"),
    chips: bool = typer.Option(True, help="Also evaluate chip timing for the configured team"),
) -> None:
    """Scheduled pipeline: ingest -> forecast -> best squads -> team plan -> league -> publish."""
    import time
    from pathlib import Path

    from midweek_merchant import publish, service
    from midweek_merchant.backtest.run import run_and_save
    from midweek_merchant.data.ingest import ingest as run_ingest
    from midweek_merchant.data.store import write_output
    from midweek_merchant.forecast import run_forecast

    s = get_settings()
    log = logging.getLogger("refresh")
    run_ingest(s, history_refresh=True)
    fc = run_forecast(s)
    log.info("forecast GW%d done", fc.next_gw)
    service.save_best_squads(s, service.best_squads(s, fc.projections))
    if s.team_id:
        try:
            state = service.team_state(s, s.team_id)
            pl = service.plan_for_team(s, state, fc.projections)
            extra = {}
            if chips and state.chips_available:
                extra["chips"] = service.chip_report(s, state, horizon=6, exact=True)
            service.save_plan(s, s.team_id, state, pl, fc.projections, extra)
            log.info("plan for %s saved", s.team_id)
            if s.league_id:
                write_output(
                    s,
                    f"league_{s.league_id}.json",
                    service.league_report(s, s.league_id, s.team_id, my_state=state),
                )
                log.info("league %s saved", s.league_id)
        except Exception:  # noqa: BLE001 - keep publishing the rest
            log.exception("team/league step failed")
    from midweek_merchant.backtest.hindcast import hindcast_season
    from midweek_merchant.data.ingest import previous_seasons
    from midweek_merchant.data.store import read_table

    # Hindcast every finished gameweek of this season (blind pick vs reality; a few seconds each)
    try:
        events = read_table(s, "events")
        done = sorted(int(g) for g in events.loc[events["finished"].astype(bool), "gw"] if g >= 2)
        if done:
            hindcast_season(s, s.season, done)
    except Exception:  # noqa: BLE001
        log.exception("hindcast failed")
    bt = s.outputs_dir / "backtest_summary.json"
    if not bt.exists() or (time.time() - bt.stat().st_mtime) / 86400 > backtest_max_age_days:
        prev = previous_seasons(s.season, 1)[0]
        try:
            run_and_save(s, prev, gws=list(range(4, 39)))
            hindcast_season(s, prev, list(range(2, 39)))
        except Exception:  # noqa: BLE001
            log.exception("backtest/hindcast of %s failed", prev)
    if publish_dir:
        man = publish.build_bundle(s, Path(publish_dir))
        typer.echo(f"bundle: {len(man['files'])} files -> {publish_dir}")


def _parse_gws(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


@app.command()
def hindcast(
    season: str = typer.Option(None, help="Season, e.g. 2026-27 (default) or 2025-26"),
    gw: int = typer.Option(None, help="One gameweek (default: last finished GW of the season)"),
    gws: str = typer.Option(None, help="Range/list, e.g. 2-38 or 2,5,9"),
) -> None:
    """Pick a past gameweek's best XI blind (pre-deadline data only), then score it on reality."""
    from midweek_merchant.backtest.hindcast import LABELS, hindcast_gw, hindcast_season
    from midweek_merchant.data.store import read_table

    s = get_settings()
    season = season or s.season
    if gws:
        out = hindcast_season(s, season, _parse_gws(gws))
        typer.echo(f"Hindcast {season}, {len(out['gameweeks'])} gameweeks (saved hindcast_{season}.json)")
        for r in out["summary"]:
            extra = ""
            if r.get("beats_average_manager") is not None:
                extra += f"  beats avg manager {r['beats_average_manager']:.0%}"
            if r.get("beats_fpl_ep_pick") is not None:
                extra += f"  beats FPL-ep pick {r['beats_fpl_ep_pick']:.0%}"
            typer.echo(
                f"  {r['pick']:<16} mean {r['mean_points']:6.1f}  total {r['total_points']:7.0f}{extra}"
            )
        return
    if gw is None:
        pm = read_table(s, "player_matches")
        gw = int(pm.loc[pm["season"] == season, "gw"].max())
    r = hindcast_gw(s, season, gw)
    if r is None:
        raise typer.BadParameter(f"No data for {season} GW{gw}")
    m = r["picks"]["model"]
    typer.echo(
        f"{season} GW{gw}: model's pick, made with data up to the deadline {r['deadline'][:16]} "
        f"(team news snapshot: {'yes' if r['snapshot_used'] else 'no'})"
    )
    for p in m["lineup"]:
        tag = (
            " (C)"
            if p["element"] == m["captain"]["element"]
            else (" (V)" if p["element"] == m["vice"]["element"] else "")
        )
        typer.echo(
            f"  {p['position']}  {p['name'] + tag:<22} {p['team']:<15} £{p['price']:.1f}m  "
            f"predicted {p['xpts']:4.1f}  actual {p['actual']:4.0f}  ({p['minutes']:.0f}')"
        )
    typer.echo("  bench: " + ", ".join(f"{p['name']} {p['actual']:.0f}" for p in m["bench"]))
    typer.echo("Scores (actual points incl. captain and auto-subs):")
    for k, v in r["scores"].items():
        typer.echo(f"  {LABELS[k]:<16} {v:5.0f}   captain {r['picks'][k]['score']['captain']}")
    if r["average_manager"] is not None:
        typer.echo(
            f"  {'Average manager':<16} {r['average_manager']:5.0f}   (highest {r['highest_manager']:.0f})"
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
