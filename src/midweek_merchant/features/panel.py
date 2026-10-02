"""Player-match panel with team context and recency weights."""

from __future__ import annotations

import numpy as np
import pandas as pd

GWS_PER_SEASON = 38


def season_ord(season: str) -> int:
    return int(season[:4])


def time_index(season: str | pd.Series, gw: int | pd.Series) -> int | pd.Series:
    """Global gameweek index: consecutive across seasons (GW38 of 2025-26 is 1 before GW1 of 2026-27)."""
    if isinstance(season, pd.Series):
        return season.str[:4].astype(int) * GWS_PER_SEASON + gw.astype(int)
    return season_ord(season) * GWS_PER_SEASON + int(gw)


def build_panel(
    pm: pd.DataFrame,
    tm: pd.DataFrame,
    seasons: list[str],
    now_season: str,
    now_gw: int,
) -> pd.DataFrame:
    """Rows for the given seasons with team xG/goals for and against and a match age.

    ``now_gw`` is the gameweek being forecast; a row's ``age`` is how many gameweeks
    before it the match happened (1 = the most recent gameweek).
    """
    df = pm[pm["season"].isin(seasons)].copy()
    df = df.dropna(subset=["code", "gw"])
    t = tm[["season", "fixture", "hg", "ag", "hxg", "axg"]].drop_duplicates(["season", "fixture"])
    df = df.merge(t, on=["season", "fixture"], how="left")
    home = df["was_home"].astype(bool)
    df["team_xg"] = np.where(home, df["hxg"], df["axg"])
    df["team_xga"] = np.where(home, df["axg"], df["hxg"])
    df["team_goals"] = np.where(home, df["hg"], df["ag"])
    df["team_conc"] = np.where(home, df["ag"], df["hg"])
    df = df.drop(columns=["hg", "ag", "hxg", "axg"])
    df["t"] = time_index(df["season"], df["gw"])
    df["age"] = time_index(now_season, now_gw) - df["t"]
    df = df[df["age"] > 0]
    num = [
        "minutes",
        "starts",
        "goals",
        "assists",
        "xg",
        "xa",
        "xgc",
        "cs",
        "gc",
        "saves",
        "bonus",
        "bps",
        "yc",
        "rc",
        "og",
        "dc",
        "points",
        "team_xg",
        "team_xga",
    ]
    df[num] = df[num].astype(float)
    df["code"] = df["code"].astype(int)
    return df.sort_values(["code", "t", "kickoff_time"]).reset_index(drop=True)
