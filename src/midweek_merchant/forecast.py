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
from midweek_merchant.data.ingest import previous_seasons
from midweek_merchant.data.store import read_table, write_output
from midweek_merchant.features.panel import build_panel
from midweek_merchant.models import minutes as minutes_model
from midweek_merchant.models.player_rates import RateParams, fit_rates
from midweek_merchant.models.team_strength import fit_ratings, project_fixtures, team_fixture_rows
from midweek_merchant.models.xpts import fixture_xpts, gameweek_xpts
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
    horizon = horizon or cfg.horizon
    rules = load_rules(settings)
    players = read_table(settings, "players")
    teams = read_table(settings, "teams")
    events = read_table(settings, "events")
    fixtures = read_table(settings, "fixtures")
    pm = read_table(settings, "player_matches")
    tm = read_table(settings, "team_matches")
    e1 = read_table(settings, "fd_e1")
    market = read_table(settings, "market_odds")

    next_gw = start_gw or next_gameweek(events)
    if next_gw is None:
        raise RuntimeError("No upcoming gameweek: season finished?")
    gws = list(range(next_gw, min(38, next_gw + horizon - 1) + 1))
    now = datetime.now(UTC)

    # ---- team strength
    cols = ["date", "league", "home", "away", "hg", "ag", "hxg", "axg"]
    hist = pd.concat(
        [tm.loc[tm["finished"].fillna(False).astype(bool), cols], e1.loc[e1["finished"].astype(bool), cols]],
        ignore_index=True,
    )
    upcoming = fixtures[fixtures["gw"].isin(gws) & ~fixtures["started"]].copy()
    pseudo = market.merge(upcoming[["home", "away"]], on=["home", "away"]) if len(market) else None
    ratings = fit_ratings(
        hist, pd.Timestamp(now.date()), xi=cfg.team_decay_per_day, xg_weight=cfg.xg_weight, pseudo=pseudo
    )
    proj = project_fixtures(
        ratings, upcoming, market, next_gw, cfg.market_weight_next, cfg.market_weight_decay
    )
    tf = team_fixture_rows(proj)

    # ---- player panel & models
    seasons = previous_seasons(settings.season, 2) + [settings.season]
    panel = build_panel(pm, tm, seasons, settings.season, next_gw)
    profiles = minutes_model.minutes_profiles(panel, players, settings.season)
    rates, params = fit_rates(
        panel, players, settings.season, cfg.player_half_life_matches, cfg.prior_matches
    )

    rows = players[["element", "code", "name", "position", "team", "team_short", "now_cost"]].merge(
        tf, on="team", how="inner"
    )
    overrides = minutes_overrides if minutes_overrides is not None else load_overrides().get("minutes", {})
    rows = minutes_model.fixture_minutes(
        profiles.drop(columns=["code"]), players, rows, next_gw, now, overrides
    )
    rows = rows.merge(rates.drop(columns=["code"]), on="element", how="left")
    fx_x = fixture_xpts(rows, params, rules)

    short = dict(zip(teams["team"], teams["short_name"], strict=True))
    gw_x = gameweek_xpts(fx_x, players["element"], gws, short)
    info = players[
        [
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
    ]
    gw_x = info.merge(gw_x, on="element", how="right")

    fc = Forecast(
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
    if save:
        save_forecast(settings, fc)
    return fc


def save_forecast(settings: Settings, fc: Forecast) -> None:
    write_output(settings, "projections.parquet", fc.projections)
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
