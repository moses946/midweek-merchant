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
