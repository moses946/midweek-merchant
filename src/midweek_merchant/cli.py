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
    ceiling: bool = typer.Option(True, help="Also rank plans by the chance of a 100+ week"),
) -> None:
    """Scheduled pipeline: ingest -> forecast -> best squads -> team plan -> league -> publish."""
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
    from midweek_merchant.backtest.tails import fit_scale, tail_calibration
    from midweek_merchant.data.ingest import previous_seasons
    from midweek_merchant.data.store import read_table

    # Hindcast every finished gameweek of this season (blind pick vs reality; a few seconds each)
    try:
        events = read_table(s, "events")
        done = sorted(int(g) for g in events.loc[events["finished"].astype(bool), "gw"] if g >= 2)
        if done:
            hindcast_season(s, s.season, done)
            tail_calibration(s, s.season)
    except Exception:  # noqa: BLE001
        log.exception("hindcast failed")
    if _age_days(s.outputs_dir / "backtest_summary.json") > backtest_max_age_days:
        prev = previous_seasons(s.season, 1)[0]
        try:
            run_and_save(s, prev, gws=list(range(4, 39)))
            hindcast_season(s, prev, list(range(2, 39)))
            tail_calibration(s, prev)
        except Exception:  # noqa: BLE001
            log.exception("backtest/hindcast of %s failed", prev)
    fit_scale(s, (*previous_seasons(s.season, 1), s.season))
    if ceiling and s.team_id:  # after the tail calibration it relies on
        try:
            state = service.team_state(s, s.team_id)
            write_output(s, f"ceiling_{s.team_id}.json", service.ceiling_report(s, state))
            log.info("ceiling plans for %s saved", s.team_id)
        except Exception:  # noqa: BLE001
            log.exception("ceiling step failed")
    if publish_dir:
        man = publish.build_bundle(s, Path(publish_dir))
        typer.echo(f"bundle: {len(man['files'])} files -> {publish_dir}")


@app.command()
def sync() -> None:
    """Download the latest published data bundle (data branch) into the data directory."""
    from midweek_merchant.publish import sync_from_remote

    s = get_settings()
    man = sync_from_remote(s)
    typer.echo(f"synced {len(man['files'])} files ({man['generated_at']}) -> {s.data_dir}")


@app.command("export-web")
def export_web(
    out: str = typer.Option("web/public/data", help="Directory for the React dashboard's JSON bundle"),
) -> None:
    """Write the JSON bundle the React dashboard reads (from existing outputs; no model runs)."""
    from pathlib import Path

    from midweek_merchant.web_export import export_web as run_export

    meta = run_export(get_settings(), Path(out))
    typer.echo(f"web bundle for GW{meta['next_gw']} ({meta['players']} players) -> {out}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
) -> None:
    """HTTP API for the React dashboard's live planner (needs the ``api`` extra)."""
    import uvicorn

    uvicorn.run("midweek_merchant.api:app", host=host, port=port)


def _age_days(path) -> float:  # noqa: ANN001
    """Age of a JSON output from its ``generated_at`` stamp.

    File mtimes are useless here: the workflow restores outputs from the data branch with
    fresh timestamps on every run.
    """
    from datetime import UTC, datetime

    try:
        stamp = datetime.fromisoformat(json.loads(path.read_text())["generated_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return float("inf")
    return (datetime.now(UTC) - stamp).total_seconds() / 86400


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
    team_id: int = typer.Option(None, help="Use YOUR squad, bank and FTs as they were at that deadline"),
) -> None:
    """Pick a past gameweek's best XI blind (pre-deadline data only), then score it on reality."""
    from midweek_merchant.backtest.hindcast import LABELS, hindcast_gw, hindcast_season
    from midweek_merchant.data.store import read_table

    s = get_settings()
    season = season or s.season
    if team_id:
        from midweek_merchant.backtest.hindcast import hindcast_team

        if gw is None:
            pm = read_table(s, "player_matches")
            gw = int(pm.loc[pm["season"] == season, "gw"].max())
        r = hindcast_team(s, team_id, season, gw)
        st = r["state"]
        typer.echo(
            f"{r['team']} at the GW{gw} deadline: bank £{st['bank']:.1f}m, {st['free_transfers']} FT, "
            f"squad value £{st['squad_value']:.1f}m. FPL scored you {r['fpl_points']}."
        )
        typer.echo(
            "Picked with pre-deadline predictions only, scored on real GW points (auto-subs, captain):"
        )
        for row in r["rows"]:
            typer.echo(
                f"  {row['label']:<44} {row['moves'][:46]:<46} (C) {row['captain']:<14} "
                f"predicted {row['predicted']:5.1f}  actual {row['actual']:5.0f}"
            )
        best = r["weeks"]["ft"]
        typer.echo("Model's pick with your free transfer:")
        for p in best["lineup"]:
            tag = " (C)" if p["element"] == best["captain"]["element"] else ""
            typer.echo(
                f"  {p['position']}  {p['name'] + tag:<20} predicted {p['xpts']:4.1f}  actual {p['actual']:4.0f}"
            )
        typer.echo("  bench: " + ", ".join(f"{p['name']} {p['actual']:.0f}" for p in best["bench"]))
        return
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


@app.command()
def ceiling(
    team_id: int = typer.Option(None, help="FPL entry id (defaults to config/env)"),
    target: float = typer.Option(100, help="Points target for one gameweek"),
    weeks: int = typer.Option(4, help="Chase the target within the next N gameweeks"),
    horizon: int = typer.Option(8, help="Plan horizon (later weeks still count for expected points)"),
    sims: int = typer.Option(5000, help="Monte Carlo simulations"),
    workers: int = typer.Option(4, help="Parallel solves"),
) -> None:
    """Plans ranked by the chance of at least one gameweek above the target."""
    from midweek_merchant import service
    from midweek_merchant.data.store import write_output

    s = get_settings()
    tid = team_id or s.team_id
    if not tid:
        raise typer.BadParameter("Give --team-id or set team_id in config.yaml / FPL_TEAM_ID")
    state = service.team_state(s, tid)
    rep = service.ceiling_report(s, state, target, weeks, horizon, sims, workers)
    write_output(s, f"ceiling_{tid}.json", rep)
    gws = rep["target_gws"]
    typer.echo(
        f"{state.name}: P(at least one week >= {target:g}) in GW{gws[0]}–{gws[-1]}, "
        f"{sims} simulations; captains re-chosen for the target; tail-calibrated with spread factor "
        f"k={rep['scale']:g} (raw = uncalibrated). Saved ceiling_{tid}.json"
    )
    head = f"  {'plan':<62} {'P(any)':>7} {'raw':>6} " + " ".join(f"{'GW' + str(g):>6}" for g in gws)
    typer.echo(
        head + f" {'E[best]':>8} {'p99':>5} {'E[GW' + str(gws[0]) + '–' + str(gws[-1]) + ']':>10} {'cost':>6}"
    )
    for r in rep["table"]:
        typer.echo(
            f"  {r['label'][:62]:<62} {r['p_any']:7.1%} {r['p_any_raw']:6.1%} "
            + " ".join(f"{r[f'p_gw{g}']:6.1%}" for g in gws)
            + f" {r['e_best_week']:8.1f} {r['p99_best_week']:5.0f} {r['e_total']:10.1f} {r['cost_vs_best']:6.1f}"
        )
    typer.echo(
        f"  cost = expected points given up over GW{rep['horizon_gws'][0]}–{rep['horizon_gws'][-1]} "
        "(incl. value of chips kept) vs the best expected-points plan tested"
    )
    best = rep["plans"][str(rep["best"])]
    typer.echo(f"\nBest chance: {best['label']}")
    for w in best["weeks"]:
        if "sim" not in w:
            continue
        moves = ", ".join(
            f"{o['name']} → {i['name']}" for o, i in zip(w["transfers_out"], w["transfers_in"], strict=False)
        )
        if w["chip"] == "wildcard":
            moves = "Wildcard: " + ", ".join(i["name"] for i in w["transfers_in"])
        typer.echo(
            f"  GW{w['gw']} {('[' + w['chip'] + ']') if w['chip'] else '':<11} "
            f"C {w['captain']['name']:<14} mean {w['sim']['mean']:5.1f}  P(>={target:g}) {w['sim']['p_target']:5.1%}  "
            f"p99 {w['sim']['p99']:4.0f}  hits {w['hits']}  {moves or 'no transfers'}"
        )
        typer.echo(
            "      XI: "
            + ", ".join(p["name"] for p in w["lineup"])
            + " | bench: "
            + ", ".join(p["name"] for p in w["bench"])
        )


@diagnose_app.command("tails")
def tails(
    seasons: str = typer.Option("2025-26,2026-27", help="Seasons with saved hindcasts"),
    every: int = typer.Option(1, help="Use every Nth hindcast gameweek"),
    sims: int = typer.Option(4000),
    refit_only: bool = typer.Option(False, help="Only refit the spread factor from saved calibrations"),
) -> None:
    """Check the simulator's score distribution on blind hindcast XIs and fit its spread factor."""
    from midweek_merchant.backtest.tails import fit_scale, tail_calibration

    s = get_settings()
    names = tuple(x.strip() for x in seasons.split(","))

    def show(tag: str, r: dict) -> None:
        typer.echo(
            f"[{tag}] {r['gameweeks']} GWs | actual mean {r['actual_mean']:.1f} vs simulated "
            f"{r['sim_mean']:.1f} | simulated SD {r['sim_sd']:.1f} vs realised {r['realised_sd']:.1f}"
        )
        typer.echo(
            f"   80+: expected {r['n80_expected']:.1f} weeks, observed {r['n80_observed']} | "
            f"100+: expected {r['n100_expected']:.1f}, observed {r['n100_observed']} | PIT {r['pit_hist']}"
        )

    if not refit_only:
        for season in names:
            for r in tail_calibration(s, season, every, sims, picks=("model", "fpl_ep"))["summary"]:
                show(f"{season} {r['pick']}", r)
    fit = fit_scale(s, names)
    typer.echo(f"Fitted spread factor k = {fit['scale']} over {fit['gameweeks']} model-pick gameweeks (CRPS)")
    if fit["gameweeks"]:
        show("pooled, raw", fit["raw"])
        show(f"pooled, k={fit['scale']}", fit["fitted"])


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
