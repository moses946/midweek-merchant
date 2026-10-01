"""Point-in-time FPL player snapshots from olbauday/FPL-Elo-Insights.

``data/{season}/playerstats.csv`` holds one FPL bootstrap snapshot per gameweek. The row
labelled ``gw = k`` is taken *after* GW k was played (its ``event_points`` equal GW k's
points), so snapshot ``k - 1`` is the last state known before the GW k deadline: injury
news, chance of playing, price and FPL's own pre-deadline ``ep_next``.
"""

from __future__ import annotations

import logging

import pandas as pd

from midweek_merchant.config import Settings
from midweek_merchant.data.store import download

log = logging.getLogger(__name__)

BASE = "https://raw.githubusercontent.com/olbauday/FPL-Elo-Insights/main/data"
SNAPSHOT_COLS = [
    "season",
    "snapshot_gw",
    "element",
    "web_name",
    "status",
    "chance_next",
    "news",
    "now_cost",
    "ep_next",
    "penalties_order",
    "selected_by_percent",
]


def _repo_season(season: str) -> str:
    """'2026-27' -> '2026-2027'."""
    start = int(season[:4])
    return f"{start}-{start + 1}"


def load_snapshots(settings: Settings, season: str) -> pd.DataFrame:
    dest = settings.raw_dir / "elo_insights" / f"{season}.csv"
    max_age = 6 * 3600 if season == settings.season else 30 * 86400
    download(f"{BASE}/{_repo_season(season)}/playerstats.csv", dest, max_age=max_age, timeout=120)
    raw = pd.read_csv(dest, low_memory=False)
    out = pd.DataFrame(
        {
            "season": season,
            "snapshot_gw": pd.to_numeric(raw["gw"], errors="coerce"),
            "element": pd.to_numeric(raw["id"], errors="coerce"),
            "web_name": raw.get("web_name"),
            "status": raw["status"].fillna("a"),
            "chance_next": pd.to_numeric(raw["chance_of_playing_next_round"], errors="coerce"),
            "news": raw["news"].fillna(""),
            "now_cost": (pd.to_numeric(raw["now_cost"], errors="coerce") * 10).round(),
            "ep_next": pd.to_numeric(raw["ep_next"], errors="coerce"),
            "penalties_order": pd.to_numeric(raw.get("penalties_order"), errors="coerce"),
            "selected_by_percent": pd.to_numeric(raw.get("selected_by_percent"), errors="coerce"),
        }
    )
    # Some snapshots export a missing chance-of-playing as 0 for fully available players;
    # FPL never pairs status "a" with 0%, so treat it as "no flag".
    out.loc[(out["status"] == "a") & (out["chance_next"] == 0), "chance_next"] = float("nan")
    out = out.dropna(subset=["snapshot_gw", "element", "now_cost"])
    out[["snapshot_gw", "element", "now_cost"]] = out[["snapshot_gw", "element", "now_cost"]].astype(int)
    return out.drop_duplicates(["season", "snapshot_gw", "element"], keep="last")[SNAPSHOT_COLS]


def load_all(settings: Settings, seasons: list[str]) -> pd.DataFrame:
    frames = []
    for s in seasons:
        try:
            frames.append(load_snapshots(settings, s))
        except Exception as exc:  # noqa: BLE001 - optional source
            log.warning("FPL-Elo-Insights snapshots for %s unavailable: %s", s, exc)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SNAPSHOT_COLS)
