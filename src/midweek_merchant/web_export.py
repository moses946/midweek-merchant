"""Export the dashboard's JSON bundle for the React front end (``web/``).

The React app is static: it reads these files from the ``data`` branch (or from
``web/public/data`` in development). Everything here is a reshaping of files the
pipeline already writes, so the export is cheap and never re-runs a model.

Files (all under ``dest``):

* ``meta.json``        season, gameweeks, deadlines, team ratings and which optional files exist
* ``players.json``     one row per player: price, ownership, news and xPts for every projected GW
* ``fixtures.json``    expected goals per fixture over the horizon, plus blank/double gameweeks
* ``best_squads.json`` best XI per gameweek and the wildcard draft
* ``plan_<team>.json`` the configured team's plan and chip report
* ``ceiling_<team>.json`` plans ranked by the chance of a big week (best and reference plans only)
* ``league_<league>.json`` mini-league analysis
* ``hindcast_<season>.json`` blind picks scored on reality
* ``model.json``       backtest metrics, calibration and live tracking
"""

from __future__ import annotations

import json
import logging
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from midweek_merchant.config import Settings

log = logging.getLogger(__name__)

BREAKDOWN = {
    "app": "x_app",
    "goals": "x_goals",
    "assists": "x_assists",
    "cs": "x_cs",
    "gc": "x_gc",
    "saves": "x_saves",
    "dc": "x_dc",
    "bonus": "x_bonus",
    "cards": "x_cards",
}
PICKS_KEPT_PAST_SEASONS = ("model", "hindsight")  # older seasons: drop the comparison XIs to save space


def _r(v: Any, nd: int = 2) -> float | None:
    """Round for JSON; NaN/inf become null."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, nd) if math.isfinite(f) else None


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text()) if path.exists() else None


def _write(dest: Path, name: str, data: Any) -> str:
    text = json.dumps(data, separators=(",", ":"), default=_json_default)
    # FPL sometimes truncates an emoji in a team name, leaving U+FFFD; drop it rather than show "?".
    (dest / name).write_text(text.replace("\\ufffd", ""))
    return name


def _json_default(o: Any) -> Any:
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return _r(o, 4)
    if isinstance(o, pd.Timestamp | datetime):
        return o.isoformat()
    raise TypeError(f"not JSON serialisable: {type(o)}")


def _players(proj: pd.DataFrame, players: pd.DataFrame, gws: list[int]) -> list[dict[str, Any]]:
    info = proj.drop_duplicates("element").set_index("element")
    by = proj.groupby(["element", "gw"])
    xp = by["xpts"].sum(min_count=1).unstack().reindex(columns=gws)  # min_count: missing stays NaN
    xmins = by["xmins"].sum(min_count=1).unstack().reindex(columns=gws)
    fx = by["fixtures"].first().unstack().reindex(columns=gws)
    nxt = proj[proj["gw"] == gws[0]].set_index("element")
    extra = players.set_index("element") if len(players) else pd.DataFrame()

    def proj_next(e: int, col: str) -> float | None:
        return _r(nxt[col].get(e), 3) if col in nxt else None

    def tonight(s: Any) -> float | None:
        try:
            p = json.loads(s or "[]")
        except (TypeError, ValueError):
            return None
        return _r(p[0].get("projected_percent"), 1) if p else None

    rows = []
    for e, r in info.iterrows():
        e = int(e)
        ex = extra.loc[e] if e in extra.index else None
        rows.append(
            {
                "id": e,
                "name": r["name"],
                "full": r["full_name"],
                "pos": r["position"],
                "team": r["team_short"],
                "price": int(r["now_cost"]) / 10,
                "status": r["status"],
                "news": r["news"] or "",
                "chance": _r(r["chance_next"], 0),
                "own": _r(r["selected_by_percent"], 1),
                "form": _r(r["form"], 1),
                "pts": int(r["total_points"]),
                "ep": _r(r["ep_next"], 1),
                "pcp": _r(r["price_change_percent"], 1),
                "pcn": tonight(ex["price_change_projections"]) if ex is not None else None,
                "tin": int(ex["transfers_in_event"]) if ex is not None else 0,
                "tout": int(ex["transfers_out_event"]) if ex is not None else 0,
                "xp": [_r(v) for v in xp.loc[e].tolist()],
                "fx": ["" if (isinstance(v, float) and np.isnan(v)) else str(v) for v in fx.loc[e].tolist()],
                "xmins": [_r(v, 0) for v in xmins.loc[e].tolist()],
                "next": {
                    "p_start": proj_next(e, "p_start"),
                    "xg": proj_next(e, "e_goals"),
                    "xa": proj_next(e, "e_assists"),
                    "cs": proj_next(e, "p_cs"),
                    "breakdown": {k: proj_next(e, c) for k, c in BREAKDOWN.items()},
                },
            }
        )
    rows.sort(key=lambda d: -(d["xp"][0] or 0))
    return rows


def _fixtures(settings: Settings, short: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {"fixtures": [], "calendar": [], "unscheduled": 0}
    lam_path = settings.outputs_dir / "fixture_lambdas.parquet"
    if lam_path.exists():
        fl = pd.read_parquet(lam_path)
        out["fixtures"] = [
            {
                "gw": int(r.gw),
                "home": short.get(r.home, r.home),
                "away": short.get(r.away, r.away),
                "lh": _r(r.lh, 3),
                "la": _r(r.la, 3),
                "kickoff": pd.Timestamp(r.kickoff_time).isoformat() if pd.notna(r.kickoff_time) else None,
                "market": bool(r.market),
            }
            for r in fl.itertuples()
        ]
    fx_path = settings.processed_dir / "fixtures.parquet"
    if fx_path.exists():
        fx = pd.read_parquet(fx_path)
        remaining = fx[~fx["finished"].astype(bool)]
        out["unscheduled"] = int(remaining["gw"].isna().sum())
        counts = pd.concat(
            [
                remaining[["gw", "home"]].rename(columns={"home": "team"}),
                remaining[["gw", "away"]].rename(columns={"away": "team"}),
            ]
        ).dropna(subset=["gw"])
        per = counts.groupby(["gw", "team"]).size().unstack(fill_value=0)
        per = per.reindex(columns=list(short), fill_value=0)
        for gw, row in per.iterrows():
            out["calendar"].append(
                {
                    "gw": int(gw),
                    "blank": sorted(short[t] for t, n in row.items() if n == 0),
                    "double": sorted(short[t] for t, n in row.items() if n >= 2),
                }
            )
    return out


def _teams(settings: Settings, teams: pd.DataFrame) -> list[dict[str, Any]]:
    path = settings.outputs_dir / "team_ratings.parquet"
    ratings = pd.read_parquet(path).set_index("team") if path.exists() else pd.DataFrame()
    rows = []
    for t in teams.itertuples():
        r = ratings.loc[t.team] if t.team in ratings.index else None
        rows.append(
            {
                "name": t.team,
                "short": t.short_name,
                "code": int(t.code),  # FPL team code: locates the official kit images
                "attack": _r(r["attack"], 3) if r is not None else None,
                "defence": _r(r["defence"], 3) if r is not None else None,
                "xg_for": _r(r["xg_for_vs_avg"], 3) if r is not None else None,
                "xg_against": _r(r["xg_against_vs_avg"], 3) if r is not None else None,
            }
        )
    return rows


def _events(events: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            "gw": int(r.gw),
            "deadline": pd.Timestamp(r.deadline_time).isoformat(),
            "finished": bool(r.finished),
            "average": int(r.average_entry_score) if r.finished else None,
            "highest": int(r.highest_score) if r.finished and pd.notna(r.highest_score) else None,
        }
        for r in events.itertuples()
    ]


def _trim_ceiling(c: dict[str, Any]) -> dict[str, Any]:
    keep = {str(int(c["table"][0]["plan"])), str(int(c["reference"]))} if c.get("table") else set()
    return {**c, "plans": {k: v for k, v in c.get("plans", {}).items() if k in keep}}


def _trim_hindcast(h: dict[str, Any], current: bool) -> dict[str, Any]:
    if current:
        return h
    gws = []
    for g in h.get("gameweeks", []):
        picks = {k: v for k, v in g.get("picks", {}).items() if k in PICKS_KEPT_PAST_SEASONS}
        gws.append({**g, "picks": picks})
    return {**h, "gameweeks": gws}


def _model(settings: Settings) -> dict[str, Any]:
    from midweek_merchant.backtest.run import live_tracking

    ts = _read_json(settings.outputs_dir / "team_strength_tuning.json")
    out: dict[str, Any] = {
        "backtest": _read_json(settings.outputs_dir / "backtest_summary.json"),
        "tails": _read_json(settings.outputs_dir / "tail_calibration.json"),
        "team_strength": {k: v for k, v in ts.items() if k != "table"} if ts else None,
        "live": [],
    }
    try:
        live = live_tracking(settings)
    except Exception:  # noqa: BLE001 - live tracking needs player_matches; the rest is still useful
        log.exception("live tracking failed")
        live = pd.DataFrame()
    for gw, g in live.groupby("gw") if len(live) else []:
        err = g["xpts"] - g["points"]
        out["live"].append(
            {
                "gw": int(gw),
                "players": len(g),
                "rmse": _r((err**2).mean() ** 0.5, 3),
                "mae": _r(err.abs().mean(), 3),
                "predicted": _r(g["xpts"].sum(), 1),
                "actual": _r(g["points"].sum(), 1),
            }
        )
    return out


def export_web(settings: Settings, dest: Path) -> dict[str, Any]:
    """Write the React dashboard bundle into ``dest`` and return its index."""
    dest.mkdir(parents=True, exist_ok=True)
    out = settings.outputs_dir
    meta_in = json.loads((out / "forecast_meta.json").read_text())
    proj = pd.read_parquet(out / "projections.parquet")
    teams = pd.read_parquet(settings.processed_dir / "teams.parquet")
    events = pd.read_parquet(settings.processed_dir / "events.parquet")
    players_path = settings.processed_dir / "players.parquet"
    players = pd.read_parquet(players_path) if players_path.exists() else pd.DataFrame()
    short = dict(zip(teams["team"], teams["short_name"], strict=True))
    gws = [int(g) for g in meta_in["gws"]]

    files: dict[str, Any] = {}
    files["players"] = _write(dest, "players.json", _players(proj, players, gws))
    files["fixtures"] = _write(dest, "fixtures.json", _fixtures(settings, short))

    if (bs := _read_json(out / "best_squads.json")) is not None:
        files["best_squads"] = _write(dest, "best_squads.json", bs)
    if settings.team_id:
        if (plan := _read_json(out / f"plan_{settings.team_id}.json")) is not None:
            files["plan"] = _write(dest, f"plan_{settings.team_id}.json", plan)
        if (ceil := _read_json(out / f"ceiling_{settings.team_id}.json")) is not None:
            files["ceiling"] = _write(dest, f"ceiling_{settings.team_id}.json", _trim_ceiling(ceil))
    if settings.league_id and (lg := _read_json(out / f"league_{settings.league_id}.json")) is not None:
        files["league"] = _write(dest, f"league_{settings.league_id}.json", lg)

    files["hindcast"] = {}
    for path in sorted(out.glob("hindcast_*.json"), reverse=True):
        season = path.stem.removeprefix("hindcast_")
        if season.startswith("team_"):
            continue
        h = _trim_hindcast(json.loads(path.read_text()), current=season == settings.season)
        files["hindcast"][season] = _write(dest, path.name, h)
    files["model"] = _write(dest, "model.json", _model(settings))

    next_gw = int(meta_in["next_gw"])
    ev = _events(events)
    deadline = next((e["deadline"] for e in ev if e["gw"] == next_gw), None)
    meta = {
        "version": 1,
        "season": settings.season,
        "generated_at": meta_in["generated_at"],
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "next_gw": next_gw,
        "deadline": deadline,
        "gws": gws,
        "team_id": settings.team_id,
        "league_id": settings.league_id,
        "players": int(proj["element"].nunique()),
        "events": ev,
        "teams": _teams(settings, teams),
        "files": files,
    }
    _write(dest, "meta.json", meta)
    log.info("web bundle: %d files in %s", len(list(dest.glob("*.json"))), dest)
    return meta
