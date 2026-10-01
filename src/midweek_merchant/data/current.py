"""Current-season tables from the live FPL API."""

from __future__ import annotations

import json
import logging
import math
from typing import Any

import pandas as pd

from midweek_merchant.data.fpl_api import FPLClient
from midweek_merchant.data.store import PM_COLS, TM_COLS
from midweek_merchant.data.teams import team_from_code
from midweek_merchant.rules import POSITIONS

log = logging.getLogger(__name__)

# event/live stat -> standard column
LIVE_MAP = {
    "minutes": "minutes", "starts": "starts", "goals_scored": "goals", "assists": "assists",
    "expected_goals": "xg", "expected_assists": "xa", "expected_goals_conceded": "xgc",
    "clean_sheets": "cs", "goals_conceded": "gc", "saves": "saves", "bonus": "bonus", "bps": "bps",
    "yellow_cards": "yc", "red_cards": "rc", "own_goals": "og", "penalties_saved": "pen_saved",
    "penalties_missed": "pen_missed", "defensive_contribution": "dc",
    "clearances_blocks_interceptions": "cbi", "tackles": "tackles", "recoveries": "recoveries",
}
# Stats whose per-fixture value is exact in ``explain`` (when present); others are split by minutes.
EXPLAIN_EXACT = {"minutes", "goals_scored", "assists", "clean_sheets", "saves", "bonus", "yellow_cards",
                 "red_cards", "own_goals", "penalties_saved", "penalties_missed"}


def teams_table(bootstrap: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for t in bootstrap["teams"]:
        rows.append({
            "team_id": t["id"], "code": t["code"], "team": team_from_code(t["code"], t["name"]),
            "fpl_name": t["name"], "short_name": t["short_name"],
        })
    return pd.DataFrame(rows)


def players_table(bootstrap: dict[str, Any]) -> pd.DataFrame:
    teams = {t["id"]: t for t in bootstrap["teams"]}
    rows = []
    for e in bootstrap["elements"]:
        t = teams[e["team"]]
        rows.append({
            "element": e["id"], "code": e["code"], "name": e["web_name"],
            "full_name": f'{e["first_name"]} {e["second_name"]}'.strip(),
            "position": POSITIONS[e["element_type"]], "team_id": e["team"],
            "team": team_from_code(t["code"], t["name"]), "team_short": t["short_name"],
            "now_cost": e["now_cost"], "cost_change_start": e["cost_change_start"],
            "cost_change_event": e["cost_change_event"],
            "status": e["status"], "news": e["news"] or "", "news_added": e["news_added"],
            "chance_next": e["chance_of_playing_next_round"], "chance_this": e["chance_of_playing_this_round"],
            "selected_by_percent": float(e["selected_by_percent"] or 0),
            "penalties_order": e["penalties_order"], "corners_order": e["corners_and_indirect_freekicks_order"],
            "freekicks_order": e["direct_freekicks_order"],
            "ep_next": float(e["ep_next"] or 0), "form": float(e["form"] or 0),
            "total_points": e["total_points"], "minutes_season": e["minutes"],
            "transfers_in_event": e["transfers_in_event"], "transfers_out_event": e["transfers_out_event"],
            "price_change_percent": _to_float(e.get("price_change_percent")),
            "price_change_hourly_rate": e.get("price_change_hourly_rate"),
            "price_change_projections": json.dumps(e.get("price_change_projections") or []),
            "price_change_locked_until": e.get("price_change_locked_until"),
            "price_change_calibrating": bool(e.get("price_change_calibrating")),
            "scout_risk_gws": json.dumps(sorted({r.get("gameweek") for r in (e.get("scout_risks") or [])
                                                 if r.get("gameweek")})),
            "can_select": bool(e.get("can_select", True)), "removed": bool(e.get("removed", False)),
        })
    return pd.DataFrame(rows)


def events_table(bootstrap: dict[str, Any]) -> pd.DataFrame:
    cols = ["id", "name", "deadline_time", "finished", "data_checked", "is_current", "is_next", "is_previous"]
    df = pd.DataFrame([{c: e.get(c) for c in cols} for e in bootstrap["events"]])
    df["deadline_time"] = pd.to_datetime(df["deadline_time"], utc=True)
    return df.rename(columns={"id": "gw"})


def fixtures_table(fixtures: list[dict[str, Any]], teams: pd.DataFrame, season: str) -> pd.DataFrame:
    tmap = dict(zip(teams["team_id"], teams["team"], strict=True))
    df = pd.DataFrame(fixtures)
    out = pd.DataFrame({
        "season": season, "league": "E0", "gw": df["event"], "fixture": df["id"],
        "kickoff_time": pd.to_datetime(df["kickoff_time"], utc=True),
        "home": df["team_h"].map(tmap), "away": df["team_a"].map(tmap),
        "home_id": df["team_h"], "away_id": df["team_a"],
        "hg": pd.to_numeric(df["team_h_score"], errors="coerce"),
        "ag": pd.to_numeric(df["team_a_score"], errors="coerce"),
        "finished": df["finished"].astype(bool) | df["finished_provisional"].astype(bool),
        "started": df["started"].fillna(False).astype(bool),
        "home_fdr": df["team_h_difficulty"], "away_fdr": df["team_a_difficulty"],
    })
    out["date"] = out["kickoff_time"].dt.tz_convert("Europe/London").dt.date.astype(str)
    return out


def player_matches(
    client: FPLClient,
    bootstrap: dict[str, Any],
    fixtures: pd.DataFrame,
    season: str,
) -> pd.DataFrame:
    """One row per player per fixture for every gameweek that has kicked off."""
    players = players_table(bootstrap)
    pinfo = players.set_index("element")
    fx = fixtures.set_index("fixture")
    events = events_table(bootstrap)
    started_gws = sorted(fixtures.loc[fixtures["started"], "gw"].dropna().astype(int).unique())
    rows: list[dict[str, Any]] = []
    for gw in started_gws:
        ev = events.loc[events["gw"] == gw].iloc[0]
        final = bool(ev["finished"]) and bool(ev["data_checked"])
        live = client.event_live(gw, max_age=math.inf if final else 600)
        for el in live["elements"]:
            eid = el["id"]
            if eid not in pinfo.index:
                continue
            p = pinfo.loc[eid]
            explain = [f for f in el.get("explain", []) if f["fixture"] in fx.index]
            if not explain:
                continue
            agg = el["stats"]
            per_fix = []
            for f in explain:
                st = {s["identifier"]: s for s in f["stats"]}
                per_fix.append((f["fixture"], st))
            tot_min = sum(st.get("minutes", {}).get("value", 0) for _, st in per_fix)
            for fid, st in per_fix:
                fxr = fx.loc[fid]
                row: dict[str, Any] = {
                    "season": season, "gw": gw, "fixture": fid, "kickoff_time": fxr["kickoff_time"],
                    "code": p["code"], "element": eid, "name": p["name"], "position": p["position"],
                }
                team_id = int(p["team_id"])
                if team_id == fxr["home_id"]:
                    home = True
                elif team_id == fxr["away_id"]:
                    home = False
                else:  # moved club mid-season: resolve from the player's own history
                    home = _was_home_from_summary(client, eid, fid)
                    if home is None:
                        continue
                row["was_home"] = home
                row["team"] = fxr["home"] if home else fxr["away"]
                row["opponent"] = fxr["away"] if home else fxr["home"]
                if len(per_fix) == 1:
                    for k, col in LIVE_MAP.items():
                        row[col] = _to_float(agg.get(k))
                else:
                    mins = st.get("minutes", {}).get("value", 0)
                    share = mins / tot_min if tot_min else 1 / len(per_fix)
                    for k, col in LIVE_MAP.items():
                        if k in EXPLAIN_EXACT:
                            row[col] = float(st.get(k, {}).get("value", 0))
                        else:
                            row[col] = (_to_float(agg.get(k)) or 0.0) * share
                row["points"] = sum(s["points"] for s in st.values())
                row["value"] = math.nan
                row["selected"] = math.nan
                rows.append(row)
    df = pd.DataFrame(rows)
    for col in PM_COLS:
        if col not in df.columns:
            df[col] = pd.NA
    return df[PM_COLS]


def team_matches(fixtures: pd.DataFrame, pm: pd.DataFrame) -> pd.DataFrame:
    side_xg = pm.groupby(["fixture", "was_home"])["xg"].sum().unstack("was_home")
    side_xg = side_xg.rename(columns={True: "hxg", False: "axg"})
    tm = fixtures.join(side_xg, on="fixture")
    tm.loc[~tm["finished"], ["hxg", "axg"]] = math.nan
    return tm[TM_COLS + ["home_id", "away_id", "started", "home_fdr", "away_fdr"]]


def _was_home_from_summary(client: FPLClient, element: int, fixture: int) -> bool | None:
    try:
        hist = client.element_summary(element)["history"]
    except Exception:  # noqa: BLE001
        return None
    for h in hist:
        if h["fixture"] == fixture:
            return bool(h["was_home"])
    return None


def _to_float(v: Any) -> float:
    if v is None or v == "":
        return math.nan
    try:
        return float(v)
    except (TypeError, ValueError):
        return math.nan
