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


# ---------------------------------------------------------------------- your own team, blind
def _week_from_lineup(lu: Lineup, proj: pd.DataFrame, gw: int, xp: pd.Series) -> dict[str, Any]:
    info = proj.drop_duplicates("element").set_index("element")

    def p(e: int) -> dict[str, Any]:
        r = info.loc[e]
        return {
            "element": int(e),
            "name": r["name"],
            "team": r["team_short"],
            "position": r["position"],
            "price": int(r["now_cost"]) / 10,
            "xpts": round(float(xp.get(e, 0.0)), 2),
            "fixture": r["fixtures"],
        }

    order = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
    lineup = sorted((p(e) for e in lu.starters), key=lambda d: (order[d["position"]], -d["xpts"]))
    mult = 3 if lu.triple else 2
    pred = sum(d["xpts"] for d in lineup) + (mult - 1) * float(xp.get(lu.captain, 0.0)) - 4 * lu.hits
    if lu.bench_boost:
        pred += sum(float(xp.get(e, 0.0)) for e in lu.bench)
    return {
        "gw": gw,
        "chip": "3xc" if lu.triple else ("bboost" if lu.bench_boost else None),
        "lineup": lineup,
        "bench": [p(e) for e in lu.bench],
        "captain": p(lu.captain),
        "vice": p(lu.vice),
        "hits": lu.hits,
        "xpts": round(pred, 2),
        "transfers_in": [],
        "transfers_out": [],
    }


def _score_lineup(lu: Lineup, positions: dict[int, str], actual: pd.DataFrame, gw: int) -> float:
    els = np.array(sorted(set(actual.index) | set(lu.starters) | set(lu.bench)))
    act = actual.reindex(els).fillna(0.0)
    sim = SimResult(
        [gw],
        els,
        {gw: act["points"].to_numpy(np.float32)[None, :]},
        {gw: (act["minutes"].to_numpy() > 0)[None, :]},
        positions,
    )
    return float(score_lineup(sim, gw, lu)[0])


def hindcast_team(
    settings: Settings, entry_id: int, season: str, gw: int, t: Tables | None = None
) -> dict[str, Any]:
    """The best GW ``gw`` team *this manager* could have fielded, picked with pre-deadline predictions only."""
    from midweek_merchant.data.fpl_api import FPLClient
    from midweek_merchant.data.store import read_table
    from midweek_merchant.optimize.planner import plan_transfers
    from midweek_merchant.strategy.league import best_xi
    from midweek_merchant.team.reconstruct import reconstruct_as_of

    t = t or load_tables(settings)
    rules = load_rules(settings)
    inp = point_in_time_inputs(settings, t, season, gw)
    if inp is None:
        raise ValueError(f"No data for {season} GW{gw}")
    proj = point_in_time_forecast(settings, t, inp, rules)
    proj = proj[proj["gw"] == gw].copy()
    xp = proj.set_index("element")["xpts"]
    actual = _actual(t, season, gw)
    act_pts = proj["element"].map(actual["points"]).fillna(0.0)
    prices = dict(zip(inp.players["element"].astype(int), inp.players["now_cost"].astype(int), strict=True))
    positions = dict(zip(proj["element"].astype(int), proj["position"], strict=True))
    with FPLClient(cache_dir=settings.raw_dir / "fpl") as c:
        state = reconstruct_as_of(
            c, entry_id, read_table(settings, "players"), rules, gw, prices, settings.optimizer.ft_after_chip
        )
        fielded = c.entry_picks(entry_id, gw)
    base = replace(
        PlanOptions.from_config(settings.optimizer),
        horizon=1,
        allow_chips=False,
        ft_terminal={},
        transfer_penalty=0.0,
        chip_option_value={},
        itb_value=0.0,
        time_limit=60,
        mip_gap=0.0,
    )
    rows: list[dict[str, Any]] = []
    weeks: dict[str, dict[str, Any]] = {}

    def add(key: str, label: str, week: dict[str, Any], score: float, moves: str) -> None:
        week = _annotate(week, actual)
        weeks[key] = week
        rows.append(
            {
                "option": key,
                "label": label,
                "moves": moves,
                "captain": week["captain"]["name"],
                "predicted": round(float(week["xpts"]), 1),
                "actual": score,
            }
        )

    # 0. what was actually fielded
    pk = sorted(fielded["picks"], key=lambda p: p["position"])
    chip = fielded.get("active_chip")
    lu0 = Lineup(
        [p["element"] for p in pk[:11]],
        [p["element"] for p in pk[11:]],
        next(p["element"] for p in pk if p["is_captain"]),
        next(p["element"] for p in pk if p["is_vice_captain"]),
        triple=chip == "3xc",
        bench_boost=chip == "bboost",
        hits=int(fielded["entry_history"].get("event_transfers_cost", 0)) // rules.hit_cost,
    )
    if lu0.bench_boost:
        lu0 = replace(lu0, starters=[p["element"] for p in pk], bench=[])
    s0 = _score_lineup(lu0, positions, actual, gw)
    made = [(x["element_out"], x["element_in"]) for x in c_transfers(settings, entry_id) if x["event"] == gw]
    name = proj.drop_duplicates("element").set_index("element")["name"]
    moves0 = ", ".join(f"{name.get(o, o)} → {name.get(i, i)}" for o, i in made) or "no transfer"
    add("actual", "What you fielded", _week_from_lineup(lu0, proj, gw, xp), s0, moves0)
    fpl_points = int(fielded["entry_history"]["points"]) - int(
        fielded["entry_history"].get("event_transfers_cost", 0)
    )

    # 1. same 15, model's XI / captain / bench
    sq15 = [(p["element"], positions.get(p["element"], "MID")) for p in fielded["picks"]]
    lu1 = best_xi(sq15, xp.to_dict(), rules)
    add(
        "same15",
        "Same 15, model's XI and captain",
        _week_from_lineup(lu1, proj, gw, xp),
        _score_lineup(lu1, positions, actual, gw),
        moves0,
    )

    # 2-3. from the pre-deadline squad with your free transfer(s), with and without hits
    def from_state(key: str, label: str, max_hits: int, scores: pd.Series | None = None) -> None:
        variant = proj if scores is None else proj.assign(xpts=scores.to_numpy())
        plan = plan_transfers(variant, state, rules, replace(base, max_hits_per_gw=max_hits))
        week = plan_table(plan, variant)[0]
        if scores is not None:
            for p in week["lineup"] + week["bench"]:
                p["xpts"] = round(float(xp.get(p["element"], 0.0)), 2)
            week["xpts"] = round(
                sum(p["xpts"] for p in week["lineup"])
                + float(xp.get(week["captain"]["element"], 0))
                - 4 * week["hits"],
                2,
            )
        sc = _score(week, gw, actual)["points"] - 4 * week["hits"]
        moves = (
            ", ".join(
                f"{o['name']} → {i['name']}"
                for o, i in zip(week["transfers_out"], week["transfers_in"], strict=False)
            )
            or "roll the transfer"
        )
        add(key, label, week, sc, moves + (f" (−{4 * week['hits']})" if week["hits"] else ""))

    from_state("ft", f"Your squad + {state.free_transfers} free transfer(s), no hits", 0)
    from_state("hits", "Your squad, hits allowed (max 2)", 2)

    # 4. free hit with your budget
    budget = state.squad_value + state.bank
    fh = best_squad_per_gw(proj, rules, base, budget=budget, gws=[gw])[gw]
    wk = plan_table(fh, proj)[0]
    add(
        "freehit",
        f"Free Hit (your £{budget / 10:.1f}m budget)",
        wk,
        _score(wk, gw, actual)["points"],
        "new 15",
    )

    # references: perfect hindsight under the same constraints
    lu_r = best_xi(sq15, actual["points"].to_dict(), rules)
    add(
        "ref_same15",
        "Hindsight: best XI from your 15",
        _week_from_lineup(lu_r, proj, gw, xp),
        _score_lineup(lu_r, positions, actual, gw),
        moves0,
    )
    from_state("ref_ft", "Hindsight: your squad + free transfer(s)", 0, scores=act_pts)
    fh_r = best_squad_per_gw(proj.assign(xpts=act_pts.to_numpy()), rules, base, budget=budget, gws=[gw])[gw]
    wk_r = plan_table(fh_r, proj.assign(xpts=act_pts.to_numpy()))[0]
    for p in wk_r["lineup"] + wk_r["bench"]:
        p["xpts"] = round(float(xp.get(p["element"], 0.0)), 2)
    wk_r["xpts"] = round(
        sum(p["xpts"] for p in wk_r["lineup"]) + float(xp.get(wk_r["captain"]["element"], 0.0)), 2
    )
    add(
        "ref_freehit", "Hindsight: best possible Free Hit", wk_r, _score(wk_r, gw, actual)["points"], "new 15"
    )

    out = {
        "entry": entry_id,
        "team": state.name,
        "season": season,
        "gw": gw,
        "deadline": inp.deadline.isoformat(),
        "state": {
            "bank": state.bank / 10,
            "free_transfers": state.free_transfers,
            "squad_value": state.squad_value / 10,
            "chips": state.chips_available,
        },
        "fpl_points": fpl_points,
        "rows": rows,
        "weeks": weeks,
    }
    write_output(settings, f"hindcast_team_{entry_id}_gw{gw}.json", out)
    return out


def c_transfers(settings: Settings, entry_id: int) -> list[dict[str, Any]]:
    from midweek_merchant.data.fpl_api import FPLClient

    with FPLClient(cache_dir=settings.raw_dir / "fpl") as c:
        return c.entry_transfers(entry_id)
