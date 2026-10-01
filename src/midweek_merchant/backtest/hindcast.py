"""Hindcast: pick a past gameweek's best XI blind, then score it on what actually happened.

For gameweek k the model only sees pre-deadline information (see ``run.point_in_time_inputs``).
The same squad optimiser then picks a Free-Hit-style 15 (XI, captain, ordered bench, £100m,
max 3 per club) from four different scores:

* **model**      - our expected points
* **FPL ep**     - FPL's own pre-deadline expected points (``ep_next`` from the snapshot)
* **form**       - each player's average over his previous four appearances
* **hindsight**  - the points players actually scored (the best possible XI; an upper bound)

Every pick is scored on GW k's real points with bench auto-subs and the vice-captain rule.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from midweek_merchant.backtest.run import (
    Tables,
    _form_baseline,
    load_tables,
    point_in_time_forecast,
    point_in_time_inputs,
)
from midweek_merchant.config import Settings
from midweek_merchant.data.store import write_output
from midweek_merchant.forecast import load_rules
from midweek_merchant.models.simulate import SimResult
from midweek_merchant.optimize.milp import PlanOptions
from midweek_merchant.optimize.planner import best_squad_per_gw
from midweek_merchant.service import plan_table
from midweek_merchant.strategy.league import Lineup, score_lineup

log = logging.getLogger(__name__)

PICKS = ("model", "fpl_ep", "form", "hindsight")
LABELS = {"model": "Model", "fpl_ep": "FPL ep", "form": "Form (last 4)", "hindsight": "Hindsight best"}


def _actual(t: Tables, season: str, gw: int) -> pd.DataFrame:
    rows = t.pm[(t.pm["season"] == season) & (t.pm["gw"] == gw)]
    return rows.groupby("element").agg(points=("points", "sum"), minutes=("minutes", "sum"))


def _score(week: dict[str, Any], gw: int, actual: pd.DataFrame) -> dict[str, Any]:
    els = np.array(sorted(actual.index))
    positions = {p["element"]: p["position"] for p in week["lineup"] + week["bench"] if "position" in p}
    sim = SimResult(
        gws=[gw],
        elements=els,
        points={gw: actual.loc[els, "points"].to_numpy(np.float32)[None, :]},
        played={gw: (actual.loc[els, "minutes"].to_numpy() > 0)[None, :]},
        positions=positions or None,
    )
    lu = Lineup(
        starters=[p["element"] for p in week["lineup"]],
        bench=[p["element"] for p in week["bench"]],
        captain=week["captain"]["element"],
        vice=week["vice"]["element"],
    )
    cap = week["captain"]["element"]
    cap_played = bool(actual.loc[cap, "minutes"] > 0) if cap in actual.index else False
    armband = cap if cap_played else week["vice"]["element"]
    return {
        "points": float(score_lineup(sim, gw, lu)[0]),
        "captain": week["captain"]["name"],
        "captain_points": float(actual["points"].get(armband, 0.0)),
        "captain_played": cap_played,
    }


def _annotate(week: dict[str, Any], actual: pd.DataFrame) -> dict[str, Any]:
    for group in ("lineup", "bench"):
        for p in week[group]:
            p["actual"] = float(actual["points"].get(p["element"], 0.0))
            p["minutes"] = float(actual["minutes"].get(p["element"], 0.0))
    for key in ("captain", "vice"):
        week[key]["actual"] = float(actual["points"].get(week[key]["element"], 0.0))
    return week


def hindcast_gw(
    settings: Settings, season: str, gw: int, t: Tables | None = None, opts: PlanOptions | None = None
) -> dict[str, Any] | None:
    t = t or load_tables(settings)
    rules = load_rules(settings)
    inp = point_in_time_inputs(settings, t, season, gw)
    if inp is None:
        return None
    proj = point_in_time_forecast(settings, t, inp, rules)
    proj = proj[proj["gw"] == gw].copy()
    actual = _actual(t, season, gw)
    form = _form_baseline(t.pm[t.pm["season"] == season])
    form = form[form["gw"] == gw].set_index("element")["form"]
    scores = {
        "model": proj["xpts"],
        "fpl_ep": proj["element"].map(inp.fpl_ep) if inp.snapshot_used else None,
        "form": proj["element"].map(form),
        "hindsight": proj["element"].map(actual["points"]),
    }
    opts = opts or PlanOptions.from_config(settings.optimizer)
    opts = replace(opts, time_limit=min(opts.time_limit, 30))
    picks: dict[str, Any] = {}
    for name, values in scores.items():
        if values is None:
            continue
        variant = proj.assign(xpts=pd.to_numeric(values, errors="coerce").fillna(0.0).to_numpy())
        plan = best_squad_per_gw(variant, rules, opts, budget=rules.budget, gws=[gw])[gw]
        if not plan.weeks:
            continue
        week = _annotate(plan_table(plan, variant)[0], actual)
        if name == "hindsight":  # show what the model expected from the players who actually delivered
            model_x = proj.set_index("element")["xpts"]
            for p in week["lineup"] + week["bench"]:
                p["xpts"] = round(float(model_x.get(p["element"], 0.0)), 2)
        week["score"] = _score(week, gw, actual)
        week["predicted"] = round(float(week["xpts"]), 2)
        picks[name] = week
    ev = t.events[t.events["gw"] == gw] if season == settings.season and len(t.events) else pd.DataFrame()
    avg = float(ev["average_entry_score"].iloc[0]) if len(ev) and "average_entry_score" in ev else None
    high = (
        float(ev["highest_score"].iloc[0])
        if len(ev) and "highest_score" in ev and ev["highest_score"].notna().iloc[0]
        else None
    )
    return {
        "season": season,
        "gw": gw,
        "deadline": inp.deadline.isoformat(),
        "snapshot_used": inp.snapshot_used,
        "average_manager": avg,
        "highest_manager": high,
        "picks": picks,
        "scores": {k: v["score"]["points"] for k, v in picks.items()},
    }


def hindcast_season(settings: Settings, season: str, gws: list[int], save: bool = True) -> dict[str, Any]:
    t = load_tables(settings)
    results = []
    for gw in gws:
        r = hindcast_gw(settings, season, gw, t)
        if r is None:
            continue
        results.append(r)
        log.info("hindcast %s GW%d: %s", season, gw, {k: round(v, 1) for k, v in r["scores"].items()})
    out = {
        "season": season,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "gameweeks": results,
        "summary": summarise(results),
    }
    if save:
        write_output(settings, f"hindcast_{season}.json", out)
    return out


def summarise(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for name in PICKS:
        pts = [r["scores"][name] for r in results if name in r["scores"]]
        if not pts:
            continue
        caps = [r["picks"][name]["score"]["captain_points"] for r in results if name in r["picks"]]
        row = {
            "pick": LABELS[name],
            "gameweeks": len(pts),
            "mean_points": float(np.mean(pts)),
            "total_points": float(np.sum(pts)),
            "mean_captain_points": float(np.mean(caps)),
        }
        with_avg = [r for r in results if r["average_manager"] is not None and name in r["scores"]]
        row["beats_average_manager"] = (
            float(np.mean([r["scores"][name] > r["average_manager"] for r in with_avg])) if with_avg else None
        )
        with_fpl = [r for r in results if "fpl_ep" in r["scores"] and name in r["scores"]]
        row["beats_fpl_ep_pick"] = (
            float(np.mean([r["scores"][name] > r["scores"]["fpl_ep"] for r in with_fpl]))
            if with_fpl and name != "fpl_ep"
            else None
        )
        hs = [
            r["scores"][name] / r["scores"]["hindsight"]
            for r in results
            if "hindsight" in r["scores"] and name in r["scores"] and r["scores"]["hindsight"] > 0
        ]
        row["share_of_hindsight"] = float(np.mean(hs)) if hs else None
        rows.append(row)
    avg = [r["average_manager"] for r in results if r["average_manager"] is not None]
    if avg:
        rows.append(
            {
                "pick": "Average manager",
                "gameweeks": len(avg),
                "mean_points": float(np.mean(avg)),
                "total_points": float(np.sum(avg)),
            }
        )
    return rows
