"""Shared service layer used by the CLI, the dashboard and the scheduled job."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

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
