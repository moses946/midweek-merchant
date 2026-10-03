"""Chip timing: quick per-gameweek chip values plus exact fixed-chip solves.

Quick values come from the no-chip baseline plan:
* Bench Boost  = expected points of the planned bench that week
* Triple Captain = expected points of the planned captain that week
* Free Hit     = best single-week squad (same budget) minus the planned lineup's points
Exact evaluation re-solves the multi-week plan with the chip forced into a given
gameweek (others banned) and compares against the baseline objective, so knock-on
effects (e.g. a Wildcard reshaping later transfers) are included.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pandas as pd

from midweek_merchant.optimize.milp import Plan, PlanOptions
from midweek_merchant.optimize.planner import best_squad_per_gw, plan_transfers
from midweek_merchant.rules import Rules
from midweek_merchant.team.reconstruct import TeamState


def chip_gws(state: TeamState, rules: Rules, chip: str, gws: list[int]) -> list[int]:
    out = []
    for w in rules.chip_windows(chip):
        if rules.chip_half(w.start_event) in state.chips_available.get(chip, []):
            out += [g for g in gws if w.start_event <= g <= w.stop_event]
    return sorted(set(out))


def quick_values(
    baseline: Plan, proj: pd.DataFrame, state: TeamState, rules: Rules, opts: PlanOptions
) -> pd.DataFrame:
    xp = proj.set_index(["element", "gw"])["xpts"]
    gws = [w.gw for w in baseline.weeks]
    budget = state.squad_value + state.bank
    fh = best_squad_per_gw(proj, rules, opts, budget=budget, gws=gws)
    rows = []
    for w in baseline.weeks:
        bench = sum(xp.get((e, w.gw), 0.0) for e in w.bench)
        cap = xp.get((w.captain, w.gw), 0.0)
        fh_pts = fh[w.gw].weeks[0].xpts if fh[w.gw].weeks else float("nan")
        rows.append(
            {
                "gw": w.gw,
                "bboost": bench,
                "3xc": cap,
                "freehit": fh_pts - w.xpts - 4 * w.hits,
                "planned_xpts": w.xpts,
            }
        )
    df = pd.DataFrame(rows)
    for chip in ("bboost", "3xc", "freehit"):
        ok = set(chip_gws(state, rules, chip, gws))
        df.loc[~df["gw"].isin(ok), chip] = float("nan")
    return df


def exact_values(
    proj: pd.DataFrame,
    state: TeamState,
    rules: Rules,
    opts: PlanOptions,
    chips: list[str] | None = None,
    max_workers: int = 4,
) -> tuple[Plan, pd.DataFrame]:
    base_opts = replace(opts, allow_chips=False, forced_chips={})
    baseline = plan_transfers(proj, state, rules, base_opts)
    gws = [w.gw for w in baseline.weeks]
    chips = chips or [c for c in ("wildcard", "freehit", "bboost", "3xc") if c in state.chips_available]
    jobs = [(c, g) for c in chips for g in chip_gws(state, rules, c, gws)]

    def solve(job: tuple[str, int]) -> dict:
        chip, gw = job
        o = replace(
            opts,
            allow_chips=True,
            forced_chips={gw: chip},
            banned_chips={c for c in ("wildcard", "freehit", "bboost", "3xc") if c != chip},
            time_limit=min(opts.time_limit, 40),
            mip_gap=max(opts.mip_gap, 0.01),
        )
        p = plan_transfers(proj, state, rules, o)
        return {
            "chip": chip,
            "gw": gw,
            "total_xpts": p.total_xpts if p.weeks else float("nan"),
            "gain": (p.total_xpts - baseline.total_xpts) if p.weeks else float("nan"),
            "status": p.status,
        }

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        rows = list(ex.map(solve, jobs))
    return baseline, pd.DataFrame(rows, columns=["chip", "gw", "total_xpts", "gain", "status"])


def best_chip_plan(
    proj: pd.DataFrame,
    state: TeamState,
    rules: Rules,
    opts: PlanOptions,
    exact: pd.DataFrame,
    max_workers: int = 4,
    max_rounds: int = 3,
) -> tuple[Plan, dict[int, str]] | None:
    """The best plan that plays chips, found by coordinate search over chip schedules.

    Letting the solver place chips freely is slow and stops at its time limit far from the
    optimum. Here every schedule is solved with its chips forced and the rest banned (seconds
    each). The search starts with no chips, then moves one chip at a time to its best week
    (or drops it) while the others stay put, until nothing improves. Moving chips one at a time
    catches pairs like a Bench Boost right after a Wildcard. Candidate weeks are those where the
    chip alone beats keeping it (``exact``, from :func:`exact_values`). The objective already
    charges each chip its hold value, so a schedule only wins when the chips are worth spending.
    Returns None when no schedule beats the no-chip plan.
    """
    ok = exact.dropna(subset=["gain"])
    weeks = {
        c: sorted(int(g) for g in d.loc[d["gain"] > opts.chip_option_value.get(c, 0.0), "gw"])
        for c, d in ok.groupby("chip")
    }
    weeks = {c: w for c, w in weeks.items() if w}
    if not weeks:
        return None
    fast = replace(opts, time_limit=min(opts.time_limit, 40), mip_gap=max(opts.mip_gap, 0.01))
    all_chips = {"wildcard", "freehit", "bboost", "3xc"}
    cache: dict[tuple, Plan] = {}

    def solve(sched: dict[int, str]) -> Plan:
        key = tuple(sorted(sched.items()))
        if key not in cache:
            o = replace(
                fast,
                allow_chips=bool(sched),
                forced_chips=dict(sched),
                banned_chips=all_chips - set(sched.values()),
            )
            cache[key] = plan_transfers(proj, state, rules, o)
        return cache[key]

    def score(p: Plan) -> float:
        return p.objective if p.weeks else float("-inf")

    current: dict[int, str] = {}
    best = solve(current)
    # most valuable chips first
    order = sorted(weeks, key=lambda c: -float(ok.loc[ok["chip"] == c, "gain"].max()))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for _ in range(max_rounds):
            moved = False
            for chip in order:
                others = {g: c for g, c in current.items() if c != chip}
                options = [others] + [{**others, g: chip} for g in weeks[chip] if g not in others]
                plans = list(ex.map(solve, options))
                i = max(range(len(plans)), key=lambda k: score(plans[k]))
                if score(plans[i]) > score(best) + 1e-6:
                    current, best, moved = options[i], plans[i], True
            if not moved:
                break
    return (best, current) if current else None
