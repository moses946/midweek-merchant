"""Chase a big gameweek: plans ranked by the chance of at least one score above a target.

Expected points are the right objective over a season, but a 100-point week is a tail
event. It needs a chip (Bench Boost or Triple Captain), a squad built for that week, and a
captain picked for upside rather than for the mean. Each candidate chip schedule is solved
for expected points over the full horizon, so later weeks are not wrecked to get there.
Each plan is then scored on correlated simulations of the target weeks. In every week the
captain (or Triple Captain) is re-chosen to maximise P(week >= target).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from midweek_merchant.models.simulate import SimResult, rescale
from midweek_merchant.optimize.chips import chip_gws
from midweek_merchant.optimize.milp import Plan, PlanOptions
from midweek_merchant.optimize.planner import horizon_gws, plan_transfers
from midweek_merchant.rules import Rules
from midweek_merchant.strategy.league import Lineup, held_chip_value, plan_lineups, score_lineup
from midweek_merchant.team.reconstruct import TeamState

log = logging.getLogger(__name__)

CHIPS = ("wildcard", "freehit", "bboost", "3xc")
NAMES = {"wildcard": "Wildcard", "freehit": "Free Hit", "bboost": "Bench Boost", "3xc": "Triple Captain"}


@dataclass(frozen=True)
class Schedule:
    """Chips forced into given gameweeks; all other chips are held."""

    chips: tuple[tuple[int, str], ...] = ()
    locked: frozenset[int] = frozenset()
    note: str = ""

    @property
    def chip_map(self) -> dict[int, str]:
        return dict(self.chips)

    @property
    def label(self) -> str:
        base = " + ".join(f"{NAMES[c]} GW{g}" for g, c in sorted(self.chips)) or "No chip"
        return f"{base} {self.note}".strip()


def schedule(chips: dict[int, str], **kw: object) -> Schedule:
    return Schedule(tuple(sorted(chips.items())), **kw)  # type: ignore[arg-type]


def schedules(state: TeamState, rules: Rules, gws: list[int]) -> list[Schedule]:
    """Chip schedules over the target weeks that the remaining chips and the rules allow.

    One chip per gameweek is guaranteed by construction. A Wildcard is only tried in the
    first target week, since it is what builds the squad for a later Bench Boost or Triple
    Captain week.
    """
    ok = {c: set(chip_gws(state, rules, c, gws)) for c in CHIPS}
    first = gws[0]
    wc = first in ok["wildcard"]
    out = [schedule({})]
    if wc:
        out.append(schedule({first: "wildcard"}))
    for chip in ("bboost", "3xc"):
        for g in gws:
            if g in ok[chip]:
                out.append(schedule({g: chip}))
                if wc and g != first:
                    out.append(schedule({first: "wildcard", g: chip}))
    if wc:
        for j in gws[1:]:
            for k in gws[1:]:
                if j != k and j in ok["bboost"] and k in ok["3xc"]:
                    out.append(schedule({first: "wildcard", j: "bboost", k: "3xc"}))
    out += [schedule({g: "freehit"}) for g in gws if g in ok["freehit"]]
    return out


def reference_schedules(state: TeamState, rules: Rules, gws: list[int], horizon: list[int]) -> list[Schedule]:
    """Expected-points references that keep the big-week chips for after the target weeks.

    A free chip solve over the whole horizon is the hardest model and often fails to converge
    in time, so the usual expected-points shape (an early Wildcard, then a Bench Boost once
    the new squad has settled) is enumerated instead.
    """
    later = [g for g in horizon if g not in gws]
    if not later or gws[0] not in chip_gws(state, rules, "wildcard", gws):
        return []
    ok = set(chip_gws(state, rules, "bboost", later))
    return [schedule({gws[0]: "wildcard", g: "bboost"}) for g in later if g in ok]


def solve(proj: pd.DataFrame, state: TeamState, rules: Rules, opts: PlanOptions, s: Schedule) -> Plan:
    chips = s.chip_map
    o = replace(
        opts,
        allow_chips=bool(chips),
        forced_chips=chips,
        banned_chips={c for c in CHIPS if c not in chips.values()},
        locked=set(opts.locked) | set(s.locked),
    )
    return plan_transfers(proj, state, rules, o)


def ceiling_captain(
    sim: SimResult, gw: int, lu: Lineup, target: float, scale: float = 1.0, z: float = 2.0
) -> tuple[Lineup, np.ndarray]:
    """Re-pick the captain among the starters to maximise P(score >= target).

    Hitting a high target is a rare event, so the plan's own captain is kept unless another
    starter beats it by more than ``z`` standard errors of the paired difference (all
    candidates share the same simulations). ``scale`` is the fitted tail-calibration spread
    factor. Returns the chosen lineup and its (rescaled) simulated scores.
    """
    base = rescale(score_lineup(sim, gw, lu), scale)
    hit0 = base >= target
    best: tuple[float, Lineup, np.ndarray] = (0.0, lu, base)
    for c in lu.starters:
        if c == lu.captain:
            continue
        alt = replace(lu, captain=c, vice=lu.captain)
        s = rescale(score_lineup(sim, gw, alt), scale)
        diff = (s >= target).astype(float) - hit0
        gain, se = float(diff.mean()), float(diff.std() / np.sqrt(len(diff)))
        if gain > z * se and gain > best[0]:
            best = (gain, alt, s)
    return best[1], best[2]


def tail_metrics(scores: dict[int, np.ndarray], target: float) -> dict[str, object]:
    """Tail summary of weekly score distributions that share simulations."""
    gws = sorted(scores)
    m = np.column_stack([scores[g] for g in gws])
    top = m.max(axis=1)
    return {
        "p_any": float((top >= target).mean()),
        "p_week": {int(g): float((scores[g] >= target).mean()) for g in gws},
        "e_best_week": float(top.mean()),
        "p90_best_week": float(np.percentile(top, 90)),
        "p99_best_week": float(np.percentile(top, 99)),
        "e_total": float(m.sum(axis=1).mean()),
    }


@dataclass
class Evaluation:
    schedule: Schedule
    plan: Plan
    lineups: dict[int, Lineup]  # target weeks, ceiling captains
    scores: dict[int, np.ndarray]  # target weeks, simulated points (tail-calibrated)
    metrics: dict[str, object]
    p_any_plan_captains: float  # same plan with the solver's (mean) captains, calibrated
    p_any_raw: float  # ceiling captains, before tail calibration


def evaluate(
    s: Schedule,
    plan: Plan,
    sim: SimResult,
    gws: list[int],
    target: float,
    scale: float = 1.0,
    ceiling: bool = True,
) -> Evaluation:
    lus = plan_lineups(plan)
    base = {g: rescale(score_lineup(sim, g, lus[g]), scale) for g in gws}
    chosen, scores = {}, {}
    for g in gws:
        if ceiling:
            chosen[g], scores[g] = ceiling_captain(sim, g, lus[g], target, scale)
        else:
            chosen[g], scores[g] = lus[g], base[g]
    raw = {g: score_lineup(sim, g, chosen[g]) for g in gws}
    return Evaluation(
        s,
        plan,
        chosen,
        scores,
        tail_metrics(scores, target),
        float(tail_metrics(base, target)["p_any"]),  # type: ignore[arg-type]
        float(tail_metrics(raw, target)["p_any"]),  # type: ignore[arg-type]
    )


def stack_for(proj: pd.DataFrame, gw: int, k: int = 3) -> tuple[str, list[int]]:
    """The top-k attackers (MID/FWD by xPts) of the team expected to score the most in ``gw``.

    Same-team attackers rise and fall together, which fattens a lineup's upper tail.
    """
    pv = proj[proj["gw"] == gw]
    lam = pv.drop_duplicates("team").set_index("team")["lam_for"]
    team = str(lam.idxmax())
    att = pv[(pv["team"] == team) & pv["position"].isin(["MID", "FWD"])].nlargest(k, "xpts")
    return team, [int(e) for e in att["element"]]


def kept_chip_value(plan: Plan, state: TeamState, rules: Rules, values: dict[str, float]) -> float:
    """Option value of the current-window chips this plan does not spend."""
    half = rules.chip_half(plan.weeks[0].gw) if plan.weeks else 1
    return held_chip_value(state, half, values, {w.chip for w in plan.weeks if w.chip})


@dataclass
class CeilingResult:
    target: float
    target_gws: list[int]
    horizon_gws: list[int]
    table: pd.DataFrame
    evaluations: list[Evaluation] = field(default_factory=list)
    best: int = 0
    reference: int = 0
    scale: float = 1.0


def analyse(
    proj: pd.DataFrame,
    state: TeamState,
    rules: Rules,
    opts: PlanOptions,
    simulate_fn,  # noqa: ANN001  (gws, n_sims) -> SimResult
    target: float = 100,
    weeks: int = 4,
    n_sims: int = 5000,
    max_workers: int = 4,
    n_stacks: int = 2,
    scale: float = 1.0,
) -> CeilingResult:
    gws_h = horizon_gws(proj, state, opts)
    gws = gws_h[:weeks]
    scheds = schedules(state, rules, gws) + reference_schedules(state, rules, gws, gws_h)
    o = replace(opts, time_limit=min(opts.time_limit, 40), mip_gap=max(opts.mip_gap, 0.01))

    def run(s: Schedule) -> tuple[Schedule, Plan]:
        return s, solve(proj, state, rules, o, s)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        solved = [(s, p) for s, p in ex.map(run, scheds) if p.weeks]
    log.info("ceiling: %d/%d schedules solved", len(solved), len(scheds))
    sim = simulate_fn(gws, n_sims)
    evals = [evaluate(s, p, sim, gws, target, scale) for s, p in solved]

    # stack variants of the best chip schedules: lock the strongest attack for the chip week
    chip_evals = [
        e
        for e in sorted(evals, key=lambda e: -e.metrics["p_any"])  # type: ignore[operator]
        if any(c in ("bboost", "3xc") and g in gws for g, c in e.schedule.chips)
    ][:n_stacks]
    stacks = []
    for e in chip_evals:
        chip_week = max(
            (g for g, c in e.schedule.chips if c in ("bboost", "3xc") and g in gws),
            key=lambda g: e.metrics["p_week"][g],  # type: ignore[index]
        )
        team, els = stack_for(proj, chip_week)
        if set(els) <= set(e.plan.weeks[gws_h.index(chip_week)].squad):
            continue
        names = proj.drop_duplicates("element").set_index("element").loc[els, "name"]
        stacks.append(replace(e.schedule, locked=frozenset(els), note=f"+ {team} stack ({', '.join(names)})"))
    if stacks:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            extra = [(s, p) for s, p in ex.map(run, stacks) if p.weeks]
        evals += [evaluate(s, p, sim, gws, target, scale) for s, p in extra]

    values = dict(opts.chip_option_value)
    adj = [e.plan.total_xpts + kept_chip_value(e.plan, state, rules, values) for e in evals]
    ref = int(np.argmax(adj))
    rows = []
    for k, e in enumerate(evals):
        m = e.metrics
        rows.append(
            {
                "plan": k,
                "label": e.schedule.label,
                "p_any": m["p_any"],
                "p_any_raw": e.p_any_raw,
                "p_any_plan_captains": e.p_any_plan_captains,
                **{f"p_gw{g}": v for g, v in m["p_week"].items()},  # type: ignore[union-attr]
                "e_best_week": m["e_best_week"],
                "p90_best_week": m["p90_best_week"],
                "p99_best_week": m["p99_best_week"],
                "e_total": m["e_total"],
                "xpts_horizon": e.plan.total_xpts,
                "chips_kept_value": adj[k] - e.plan.total_xpts,
                "cost_vs_best": adj[ref] - adj[k],
            }
        )
    table = pd.DataFrame(rows).sort_values(["p_any", "e_total"], ascending=False).reset_index(drop=True)
    best = int(table.iloc[0]["plan"])
    return CeilingResult(target, gws, gws_h, table, evals, best, ref, scale)
