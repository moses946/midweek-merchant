"""Shared service layer used by the CLI, the dashboard and the scheduled job."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd

from midweek_merchant.config import Settings
from midweek_merchant.data.fpl_api import FPLClient
from midweek_merchant.data.store import read_table, write_output
from midweek_merchant.forecast import load_overrides, load_rules, next_gameweek
from midweek_merchant.optimize import planner
from midweek_merchant.optimize.milp import Plan, PlanOptions
from midweek_merchant.team.reconstruct import TeamState, apply_overrides, reconstruct

log = logging.getLogger(__name__)


def load_projections(settings: Settings) -> pd.DataFrame:
    return pd.read_parquet(settings.outputs_dir / "projections.parquet")


def team_state(settings: Settings, team_id: int, overrides: dict[str, Any] | None = None) -> TeamState:
    rules = load_rules(settings)
    players = read_table(settings, "players")
    events = read_table(settings, "events")
    with FPLClient(cache_dir=settings.raw_dir / "fpl") as client:
        state = reconstruct(
            client, team_id, players, rules, next_gameweek(events), settings.optimizer.ft_after_chip
        )
    ov = overrides if overrides is not None else load_overrides().get("team", {})
    return apply_overrides(state, players, ov) if ov else state


def last_chip(state: TeamState) -> str | None:
    used = {u["event"]: u["name"] for u in state.chips_used}
    return used.get(state.next_gw - 1)


def plan_for_team(
    settings: Settings, state: TeamState, proj: pd.DataFrame | None = None, **opt_kw: Any
) -> Plan:
    rules = load_rules(settings)
    proj = proj if proj is not None else load_projections(settings)
    opt_kw.setdefault("allow_chips", False)
    opts = PlanOptions.from_config(settings.optimizer, last_gw_chip=last_chip(state), **opt_kw)
    return planner.plan_transfers(proj, state, rules, opts)


def plan_table(plan: Plan, proj: pd.DataFrame) -> list[dict[str, Any]]:
    """Human-readable plan: names, prices and per-player xPts for every week."""
    info = proj.drop_duplicates("element").set_index("element")
    xp = proj.set_index(["element", "gw"])["xpts"]
    fx = proj.set_index(["element", "gw"])["fixtures"]

    def p(e: int, gw: int) -> dict[str, Any]:
        r = info.loc[e]
        return {
            "element": int(e),
            "name": r["name"],
            "team": r["team_short"],
            "position": r["position"],
            "price": int(r["now_cost"]) / 10,
            "xpts": round(float(xp.get((e, gw), 0.0)), 2),
            "fixture": fx.get((e, gw), "—"),
        }

    order = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
    weeks = []
    for w in plan.weeks:
        lineup = sorted((p(e, w.gw) for e in w.lineup), key=lambda d: (order[d["position"]], -d["xpts"]))
        weeks.append(
            {
                "gw": w.gw,
                "chip": w.chip,
                "xpts": round(w.xpts, 2),
                "hits": w.hits,
                "free_transfers": w.free_transfers,
                "bank": w.bank / 10,
                "transfers_in": [p(e, w.gw) for e in w.transfers_in],
                "transfers_out": [p(e, w.gw) for e in w.transfers_out],
                "lineup": lineup,
                "bench": [p(e, w.gw) for e in w.bench],
                "captain": p(w.captain, w.gw),
                "vice": p(w.vice, w.gw),
            }
        )
    return weeks


def best_squads(settings: Settings, proj: pd.DataFrame | None = None, budget: int = 1000) -> dict[str, Any]:
    rules = load_rules(settings)
    proj = proj if proj is not None else load_projections(settings)
    opts = PlanOptions.from_config(settings.optimizer)
    gws = sorted(proj["gw"].unique())
    per_gw = planner.best_squad_per_gw(proj, rules, opts, budget=budget, gws=gws)
    wc = planner.best_wildcard(
        proj, rules, replace(opts, horizon=min(opts.horizon, len(gws))), gws[0], budget
    )
    return {
        "per_gw": {int(g): plan_table(pl, proj)[0] for g, pl in per_gw.items() if pl.weeks},
        "wildcard": {"total_xpts": round(wc.total_xpts, 2), "weeks": plan_table(wc, proj)},
        "budget": budget / 10,
    }


def save_best_squads(settings: Settings, data: dict[str, Any]) -> None:
    write_output(settings, "best_squads.json", data)


def save_plan(
    settings: Settings,
    team_id: int,
    state: TeamState,
    plan: Plan,
    proj: pd.DataFrame,
    extra: dict[str, Any] | None = None,
) -> None:
    write_output(
        settings,
        f"plan_{team_id}.json",
        {
            "state": state.to_dict(),
            "status": plan.status,
            "objective": plan.objective,
            "total_xpts": plan.total_xpts,
            "weeks": plan_table(plan, proj),
            **(extra or {}),
        },
    )


# ---------------------------------------------------------------------- league & chips
def rate_params(settings: Settings):  # noqa: ANN201
    import json

    import numpy as np

    from midweek_merchant.models.player_rates import RateParams

    meta = json.loads((settings.outputs_dir / "forecast_meta.json").read_text())["params"]
    return RateParams(
        meta["goal_calib"],
        meta["assist_calib"],
        meta["assist_per_goal"],
        meta["avg_team_xg"],
        meta["nb_size"],
        {k: np.asarray(v) for k, v in meta["bonus_coef"].items()},
    )


def league_report(
    settings: Settings,
    league_id: int,
    team_id: int,
    my_state: TeamState | None = None,
    horizon: int = 3,
    k_plans: int = 3,
    n_sims: int = 2000,
    max_managers: int = 30,
) -> dict[str, Any]:
    from midweek_merchant.models.simulate import simulate
    from midweek_merchant.strategy import league as lg

    rules = load_rules(settings)
    players = read_table(settings, "players")
    events = read_table(settings, "events")
    proj = load_projections(settings)
    fx = pd.read_parquet(settings.outputs_dir / "fixture_xpts.parquet")
    nxt = next_gameweek(events)
    with FPLClient(cache_dir=settings.raw_dir / "fpl") as client:
        meta, managers = lg.load_league(
            client, league_id, players, rules, nxt, max_managers, settings.optimizer.ft_after_chip
        )
    me = next((m for m in managers if m.entry == team_id), None)
    if me is None:
        raise ValueError(f"Team {team_id} is not in league {league_id} (top {max_managers} checked)")
    if my_state is not None:
        me.state = my_state
    rivals = [m for m in managers if m.entry != team_id and m.state is not None]
    gws = [g for g in sorted(proj["gw"].unique()) if g >= nxt][:horizon]
    for r in rivals:
        lg.rival_lineups(r, proj, rules, gws)
    opts = PlanOptions.from_config(
        settings.optimizer, horizon=horizon, allow_chips=False, last_gw_chip=last_chip(me.state)
    )
    plans = planner.alternatives(proj, me.state, rules, opts, k=k_plans)
    labels = ["max xPts"] + [f"alternative {k}" for k in range(1, len(plans))]
    locks = lg.candidate_locks(lg.league_eo(rivals, gws[0]), set(me.state.elements), proj, gws)
    for kind, els in locks.items():
        for e in els:
            p = planner.plan_transfers(proj, me.state, rules, replace(opts, locked={e}))
            if p.weeks:
                plans.append(p)
                labels.append(f"{kind}: {proj.loc[proj['element'] == e, 'name'].iloc[0]}")
    needed = {e for p in plans for w in p.weeks for e in w.squad}
    for r in rivals:
        needed |= {p.element for p in r.state.squad}
    sim = simulate(fx[fx["gw"].isin(gws)], rate_params(settings), rules, n_sims=n_sims, elements=needed)
    values, half = dict(settings.optimizer.chip_option_value), rules.chip_half(gws[0])
    res = lg.analyse(
        me,
        rivals,
        plans,
        sim,
        proj,
        gws,
        weeks_left_after=38 - gws[-1],
        plan_labels=labels,
        plan_bonus=[
            lg.held_chip_value(me.state, half, values, {w.chip for w in p.weeks if w.chip}) for p in plans
        ],
        rival_bonus={r.entry: lg.held_chip_value(r.state, half, values) for r in rivals},
    )
    return {
        "league": {"id": league_id, "name": meta.get("name", "")},
        "gws": [int(g) for g in gws],
        "me": me.name,
        "advice": res.advice,
        "z": res.z,
        "standings": res.standings.to_dict("records"),
        "eo": res.eo.to_dict("records"),
        "plans": res.plans.to_dict("records"),
        "captains": res.captains.to_dict("records"),
        "head_to_head": res.head_to_head.to_dict("records"),
        "plan_weeks": [plan_table(p, proj) for p in plans],
        "best_plan": res.best_plan,
        "rival_chips": [
            {
                "manager": r.name,
                "chips_left": r.state.chips_available,
                "bank": r.state.bank / 10,
                "free_transfers": r.state.free_transfers,
            }
            for r in rivals
        ],
    }


def ceiling_report(
    settings: Settings,
    state: TeamState,
    target: float = 100,
    weeks: int = 4,
    horizon: int = 8,
    n_sims: int = 5000,
    max_workers: int = 4,
    n_plans: int = 10,
) -> dict[str, Any]:
    """Plans ranked by P(at least one week >= target) in the next ``weeks`` gameweeks."""
    import json

    from midweek_merchant.models.simulate import simulate
    from midweek_merchant.strategy import ceiling as cl

    rules = load_rules(settings)
    proj = load_projections(settings)
    fx = pd.read_parquet(settings.outputs_dir / "fixture_xpts.parquet")
    params = rate_params(settings)
    opts = PlanOptions.from_config(settings.optimizer, horizon=horizon, last_gw_chip=last_chip(state))

    def sim_fn(gws: list[int], n: int):  # noqa: ANN202
        return simulate(fx[fx["gw"].isin(gws)], params, rules, n_sims=n, seed=23)

    calib_path = settings.outputs_dir / "tail_calibration.json"
    calib = json.loads(calib_path.read_text()) if calib_path.exists() else None
    scale = float(calib["scale"]) if calib else 1.0
    res = cl.analyse(proj, state, rules, opts, sim_fn, target, weeks, n_sims, max_workers, scale=scale)
    keep = list(dict.fromkeys([*res.table["plan"].head(n_plans).astype(int), res.reference]))
    plans = {}
    for k in keep:
        e = res.evaluations[k]
        weeks_ = [
            replace(w, captain=e.lineups[w.gw].captain, vice=e.lineups[w.gw].vice) if w.gw in e.lineups else w
            for w in e.plan.weeks
        ]
        table = plan_table(replace(e.plan, weeks=weeks_), proj)
        for wk in table:
            if wk["gw"] in e.scores:
                s = e.scores[wk["gw"]]
                wk["sim"] = {
                    "mean": float(s.mean()),
                    "p_target": float((s >= target).mean()),
                    "p90": float(np.percentile(s, 90)),
                    "p99": float(np.percentile(s, 99)),
                }
        plans[str(k)] = {"label": e.schedule.label, "total_xpts": e.plan.total_xpts, "weeks": table}
    return {
        "target": target,
        "target_gws": [int(g) for g in res.target_gws],
        "horizon_gws": [int(g) for g in res.horizon_gws],
        "n_sims": n_sims,
        "table": res.table.to_dict("records"),
        "best": res.best,
        "reference": res.reference,
        "plans": plans,
        "scale": scale,
        "calibration": {k: v for k, v in calib.items() if k != "crps_by_scale"} if calib else None,
    }


def chip_report(settings: Settings, state: TeamState, horizon: int = 6, exact: bool = True) -> dict[str, Any]:
    from midweek_merchant.optimize import chips as ch

    rules = load_rules(settings)
    proj = load_projections(settings)
    opts = PlanOptions.from_config(settings.optimizer, horizon=horizon, last_gw_chip=last_chip(state))
    if exact:
        baseline, exact_df = ch.exact_values(proj, state, rules, opts)
    else:
        baseline = planner.plan_transfers(proj, state, rules, replace(opts, allow_chips=False))
        exact_df = pd.DataFrame(columns=["chip", "gw", "total_xpts", "gain", "status"])
    quick = ch.quick_values(baseline, proj, state, rules, opts)
    return {
        "baseline_xpts": baseline.total_xpts,
        "quick": quick.to_dict("records"),
        "exact": exact_df.to_dict("records"),
        "option_values": opts.chip_option_value,
        "chips_available": state.chips_available,
    }
