"""`mm forecast`: team ratings -> minutes -> event rates -> expected points over the horizon."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from midweek_merchant.config import ROOT, Settings
from midweek_merchant.data import odds
from midweek_merchant.data.ingest import previous_seasons
from midweek_merchant.data.store import read_table, write_output
from midweek_merchant.features.panel import build_panel
from midweek_merchant.models import minutes as minutes_model
from midweek_merchant.models.player_rates import RateParams, fit_rates
from midweek_merchant.models.team_strength import fit_ratings, project_fixtures, team_fixture_rows
from midweek_merchant.models.xpts import calibrate_points, fixture_xpts, gameweek_xpts
from midweek_merchant.rules import Rules, rules_from_bootstrap

log = logging.getLogger(__name__)


@dataclass
class Forecast:
    next_gw: int
    gws: list[int]
    projections: pd.DataFrame  # one row per (element, gw)
    fixture_rows: pd.DataFrame  # one row per (element, fixture)
    fixtures: pd.DataFrame  # one row per fixture with λs
    ratings: pd.DataFrame
    params: RateParams
    players: pd.DataFrame
    generated_at: str


def load_overrides(path: Path | None = None) -> dict[str, Any]:
    path = path or ROOT / "override.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def load_rules(settings: Settings) -> Rules:
    import json

    bs = settings.raw_dir / "fpl" / "bootstrap.json"
    return rules_from_bootstrap(json.loads(bs.read_text()) if bs.exists() else None)


def next_gameweek(events: pd.DataFrame) -> int | None:
    nxt = events.loc[events["is_next"] == True, "gw"]  # noqa: E712
    return int(nxt.iloc[0]) if len(nxt) else None


def run_forecast(
    settings: Settings,
    horizon: int | None = None,
    minutes_overrides: dict[int, dict] | None = None,
    start_gw: int | None = None,
    save: bool = True,
) -> Forecast:
    cfg = settings.forecast
    events = read_table(settings, "events")
    fixtures = read_table(settings, "fixtures")
    next_gw = start_gw or next_gameweek(events)
    if next_gw is None:
        raise RuntimeError("No upcoming gameweek: season finished?")
    horizon = horizon or cfg.horizon
    gws = list(range(next_gw, min(38, next_gw + horizon - 1) + 1))
    now = datetime.now(UTC)
    upcoming = fixtures[fixtures["gw"].isin(gws) & ~fixtures["started"]].copy()
    tm = odds.ensure_market_lambdas(read_table(settings, "team_matches"), settings)
    e1 = odds.ensure_market_lambdas(read_table(settings, "fd_e1"), settings)
    cols = ["date", "league", "home", "away", "hg", "ag", "hxg", "axg", "hmk", "amk"]
    hist = pd.concat(
        [tm.loc[tm["finished"].fillna(False).astype(bool), cols], e1.loc[e1["finished"].astype(bool), cols]],
        ignore_index=True,
    )
    teams = read_table(settings, "teams")
    overrides = minutes_overrides if minutes_overrides is not None else load_overrides().get("minutes", {})
    fc = forecast_core(
        settings,
        players=read_table(settings, "players"),
        upcoming=upcoming,
        pm=read_table(settings, "player_matches"),
        tm=tm,
        team_hist=hist,
        market=read_table(settings, "market_odds"),
        season=settings.season,
        next_gw=next_gw,
        gws=gws,
        now=now,
        short=dict(zip(teams["team"], teams["short_name"], strict=True)),
        rules=load_rules(settings),
        minutes_overrides=overrides,
    )
    if save:
        save_forecast(settings, fc)
    return fc


INFO_COLS = [
    "element",
    "name",
    "full_name",
    "position",
    "team",
    "team_short",
    "now_cost",
    "status",
    "news",
    "chance_next",
    "selected_by_percent",
    "ep_next",
    "form",
    "total_points",
    "price_change_percent",
]


def forecast_core(
    settings: Settings,
    players: pd.DataFrame,
    upcoming: pd.DataFrame,
    pm: pd.DataFrame,
    tm: pd.DataFrame,
    team_hist: pd.DataFrame,
    market: pd.DataFrame | None,
    season: str,
    next_gw: int,
    gws: list[int],
    now: datetime,
    short: dict[str, str],
    rules: Rules,
    minutes_overrides: dict[int, dict] | None = None,
) -> Forecast:
    """Forecast from explicit inputs (used live and, with point-in-time inputs, by the backtest)."""
    cfg = settings.forecast
    pseudo = (
        market.merge(upcoming[["home", "away"]], on=["home", "away"])
        if market is not None and len(market)
        else None
    )
    ratings = fit_ratings(
        team_hist,
        pd.Timestamp(now.date()),
        xi=cfg.team_decay_per_day,
        xg_weight=cfg.xg_weight,
        ridge=cfg.ridge,
        pseudo=pseudo,
        market_weight=cfg.market_target_weight,
        spread=cfg.team_spread,
    )
    proj = project_fixtures(
        ratings, upcoming, market, next_gw, cfg.market_weight_next, cfg.market_weight_decay
    )
    tf = team_fixture_rows(proj)

    seasons = previous_seasons(season, 2) + [season]
    panel = build_panel(pm, tm, seasons, season, next_gw)
    profiles = minutes_model.minutes_profiles(panel, players, season)
    rates, params = fit_rates(panel, players, season, cfg.player_half_life_matches, cfg.prior_matches)

    rows = players[["element", "code", "name", "position", "team", "team_short", "now_cost"]].merge(
        tf, on="team", how="inner"
    )
    rows = minutes_model.fixture_minutes(
        profiles.drop(columns=["code"]),
        players,
        rows,
        next_gw,
        now,
        minutes_overrides or {},
        calibration=cfg.minutes_calibration,
        attrition=cfg.attrition_per_gw,
    )
    rows = rows.merge(rates.drop(columns=["code"]), on="element", how="left")
    fx_x = fixture_xpts(rows, params, rules)
    fx_x = calibrate_points(fx_x, cfg.next_gw_points_calibration, fx_x["gw"].to_numpy() == next_gw)
    gw_x = gameweek_xpts(fx_x, players["element"], gws, short)
    info = players[[c for c in INFO_COLS if c in players.columns]]
    gw_x = info.merge(gw_x, on="element", how="right")
    return Forecast(
        next_gw=next_gw,
        gws=gws,
        projections=gw_x,
        fixture_rows=fx_x,
        fixtures=proj,
        ratings=ratings.table(),
        params=params,
        players=players,
        generated_at=now.isoformat(timespec="seconds"),
    )


def save_forecast(settings: Settings, fc: Forecast) -> None:
    write_output(settings, "projections.parquet", fc.projections)
    # keep the latest pre-deadline projection of each gameweek for live accuracy tracking
    hist_dir = settings.outputs_dir / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    first = fc.projections[fc.projections["gw"] == fc.next_gw][["element", "gw", "xpts", "xmins", "p_start"]]
    first.to_parquet(hist_dir / f"projections_gw{fc.next_gw:02d}.parquet", index=False)
    fx_cols = [
        "gw",
        "fixture",
        "kickoff_time",
        "home",
        "away",
        "lh",
        "la",
        "lh_model",
        "la_model",
        "market",
        "rho",
    ]
    write_output(settings, "fixture_lambdas.parquet", fc.fixtures[fx_cols])
    write_output(settings, "team_ratings.parquet", fc.ratings)
    keep = [
        "element",
        "gw",
        "fixture",
        "team",
        "opp",
        "is_home",
        "lam_for",
        "lam_against",
        "p_start",
        "p_s60",
        "p_slt",
        "p_sub_app",
        "m_start60",
        "m_start_lt",
        "m_sub",
        "s_g",
        "s_a",
        "f_g",
        "f_a",
        "dc90",
        "save_k",
        "yc90",
        "rc90",
        "xpts",
        "xpts_raw",
        "pts_scale",
        "position",
        "rho",
    ]
    write_output(settings, "fixture_xpts.parquet", fc.fixture_rows[keep])
    write_output(
        settings,
        "forecast_meta.json",
        {
            "next_gw": fc.next_gw,
            "gws": fc.gws,
            "generated_at": fc.generated_at,
            "params": {
                "goal_calib": fc.params.goal_calib,
                "assist_calib": fc.params.assist_calib,
                "assist_per_goal": fc.params.assist_per_goal,
                "avg_team_xg": fc.params.avg_team_xg,
                "nb_size": fc.params.nb_size,
                "bonus_coef": {k: v.tolist() for k, v in fc.params.bonus_coef.items()},
            },
        },
    )
