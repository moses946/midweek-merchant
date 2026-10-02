"""Historical FPL seasons from the vaastav/Fantasy-Premier-League dataset."""

from __future__ import annotations

import logging

import pandas as pd

from midweek_merchant.config import Settings
from midweek_merchant.data.store import PM_COLS, TM_COLS, download
from midweek_merchant.data.teams import team_from_code

log = logging.getLogger(__name__)

VAASTAV = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"

RENAME = {
    "GW": "gw",
    "goals_scored": "goals",
    "expected_goals": "xg",
    "expected_assists": "xa",
    "expected_goals_conceded": "xgc",
    "clean_sheets": "cs",
    "goals_conceded": "gc",
    "yellow_cards": "yc",
    "red_cards": "rc",
    "own_goals": "og",
    "penalties_saved": "pen_saved",
    "penalties_missed": "pen_missed",
    "defensive_contribution": "dc",
    "clearances_blocks_interceptions": "cbi",
    "total_points": "points",
    "xP": "fpl_xp",
}


def _fetch(settings: Settings, season: str, rel: str, max_age: float | None) -> pd.DataFrame:
    dest = settings.raw_dir / "vaastav" / season / rel
    download(f"{VAASTAV}/{season}/{rel}", dest, max_age=max_age)
    return pd.read_csv(dest, encoding="utf-8", low_memory=False)


def load_season(
    settings: Settings, season: str, max_age: float | None = 30 * 86400
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (player_matches, team_matches) for a past season in standard columns."""
    gw = _fetch(settings, season, "gws/merged_gw.csv", max_age)
    players = _fetch(settings, season, "players_raw.csv", max_age)
    teams = _fetch(settings, season, "teams.csv", max_age)
    fixtures = _fetch(settings, season, "fixtures.csv", max_age)

    team_by_id = {int(r.id): team_from_code(int(r.code), r.name) for r in teams.itertuples()}
    team_by_name = {r.name: team_from_code(int(r.code), r.name) for r in teams.itertuples()}
    code_by_element = dict(zip(players["id"].astype(int), players["code"].astype(int), strict=False))

    df = gw.rename(columns=RENAME)
    df = df[df["position"].isin(["GK", "GKP", "DEF", "MID", "FWD"])].copy()
    df["position"] = df["position"].replace({"GK": "GKP"})
    df["season"] = season
    df["code"] = df["element"].astype(int).map(code_by_element)
    df["team"] = df["team"].map(team_by_name)
    df["opponent"] = df["opponent_team"].astype(int).map(team_by_id)
    df["was_home"] = df["was_home"].astype(str).str.lower().eq("true")
    for col in PM_COLS:
        if col not in df.columns:
            df[col] = pd.NA
    df["kickoff_time"] = pd.to_datetime(df["kickoff_time"], utc=True)
    pm = df[PM_COLS].copy()
    num = [
        c
        for c in PM_COLS
        if c not in ("season", "kickoff_time", "name", "position", "team", "opponent", "was_home")
    ]
    pm[num] = pm[num].apply(pd.to_numeric, errors="coerce")

    # Team-level match table; team xG = sum of player xG per side.
    fx = fixtures.copy()
    fx["kickoff_time"] = pd.to_datetime(fx["kickoff_time"], utc=True)
    side_xg = (
        pm.groupby(["fixture", "was_home"])["xg"]
        .sum()
        .unstack("was_home")
        .rename(columns={True: "hxg", False: "axg"})
    )
    tm = pd.DataFrame(
        {
            "season": season,
            "league": "E0",
            "gw": fx["event"],
            "fixture": fx["id"],
            "kickoff_time": fx["kickoff_time"],
            "home": fx["team_h"].astype(int).map(team_by_id),
            "away": fx["team_a"].astype(int).map(team_by_id),
            "hg": pd.to_numeric(fx["team_h_score"], errors="coerce"),
            "ag": pd.to_numeric(fx["team_a_score"], errors="coerce"),
            "finished": fx["finished"].astype(str).str.lower().eq("true"),
        }
    )
    tm = tm.join(side_xg, on="fixture")
    tm["date"] = tm["kickoff_time"].dt.tz_convert("Europe/London").dt.date.astype(str)
    return pm, tm[TM_COLS]


def load_history(settings: Settings) -> tuple[pd.DataFrame, pd.DataFrame]:
    pms, tms = [], []
    for season in settings.history_seasons:
        try:
            pm, tm = load_season(settings, season)
        except Exception as exc:  # noqa: BLE001 - keep going with other seasons
            log.warning("Skipping vaastav season %s: %s", season, exc)
            continue
        pms.append(pm)
        tms.append(tm)
    return pd.concat(pms, ignore_index=True), pd.concat(tms, ignore_index=True)
