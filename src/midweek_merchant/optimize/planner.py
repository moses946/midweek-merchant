"""High-level planning API: transfer plans, best squads, alternatives and sensitivity."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import replace

import numpy as np
import pandas as pd

from midweek_merchant.optimize.milp import Plan, PlanOptions, build_and_solve
from midweek_merchant.optimize.pool import select_pool
from midweek_merchant.rules import Rules
from midweek_merchant.team.reconstruct import TeamState

log = logging.getLogger(__name__)


def _pool(proj: pd.DataFrame, state: TeamState, opts: PlanOptions, gws: list[int]) -> list[int]:
    must = set(state.elements) | set(opts.locked)
    for els in opts.booked_in.values():
        must |= set(els)
    return select_pool(proj, gws, opts.decay, must_include=must, quota=opts.pool_quota, exclude=opts.banned)


def horizon_gws(proj: pd.DataFrame, state: TeamState, opts: PlanOptions) -> list[int]:
    return [g for g in sorted(proj["gw"].unique()) if g >= state.next_gw][: opts.horizon]


def plan_transfers(proj: pd.DataFrame, state: TeamState, rules: Rules, opts: PlanOptions) -> Plan:
    gws = horizon_gws(proj, state, opts)
    elements = _pool(proj, state, opts, gws)
    plan, *_ = build_and_solve(proj, state, rules, opts, elements)
    log.info(
        "plan: %s obj=%.2f gap=%.4f t=%.1fs pool=%d",
        plan.status,
        plan.objective,
        plan.gap,
        plan.runtime,
        len(elements),
    )
    return plan


def empty_state(next_gw: int, budget: int = 1000, chips: dict[str, list[int]] | None = None) -> TeamState:
    return TeamState(
        entry_id=None,
        name="Unconstrained",
        next_gw=next_gw,
        squad=[],
        bank=budget,
        free_transfers=1,
        chips_available=chips or {},
    )


def best_squad_per_gw(
    proj: pd.DataFrame, rules: Rules, opts: PlanOptions, budget: int = 1000, gws: list[int] | None = None
) -> dict[int, Plan]:
    """The best possible squad for each single gameweek (a Free Hit view)."""
    gws = gws or sorted(proj["gw"].unique())
    out = {}
    for gw in gws:
        st = empty_state(gw, budget)
        o = replace(
            opts,
            horizon=1,
            free_first_week=True,
            allow_chips=False,
            ft_terminal={},
            chip_option_value={},
            transfer_penalty=0.0,
        )
        out[gw] = plan_transfers(proj, st, rules, o)
    return out


def best_wildcard(
    proj: pd.DataFrame, rules: Rules, opts: PlanOptions, next_gw: int, budget: int = 1000
) -> Plan:
    """Best squad built now for the whole horizon, with normal FT rules afterwards."""
    st = empty_state(next_gw, budget)
    o = replace(opts, free_first_week=True, allow_chips=False)
    return plan_transfers(proj, st, rules, o)


def alternatives(
    proj: pd.DataFrame, state: TeamState, rules: Rules, opts: PlanOptions, k: int = 4
) -> list[Plan]:
    """Top-k distinct plans by first-week transfer set (no-good cuts)."""
    gws = horizon_gws(proj, state, opts)
    elements = _pool(proj, state, opts, gws)
    cuts: list[tuple[np.ndarray, np.ndarray, float]] = []
    plans = []
    for _ in range(k):
        plan, _m, b, _sol = build_and_solve(proj, state, rules, opts, elements, extra_cuts=cuts)
        if not plan.weeks:
            break
        plans.append(plan)
        first = plan.weeks[0]
        tin = b.v["tin"][:, 0]
        chosen = {elements.index(e) for e in first.transfers_in}
        idx = np.array([tin[i] for i in range(len(elements))])
        val = np.array([1.0 if i in chosen else -1.0 for i in range(len(elements))])
        # forbid exactly this set of first-week buys (an empty set becomes "make at least one")
        cuts.append((idx, val, float(len(chosen) - 1)))
    return plans


def sensitivity(
    proj: pd.DataFrame,
    state: TeamState,
    rules: Rules,
    opts: PlanOptions,
    n: int = 12,
    seed: int = 0,
    sd_scale: float = 1.0,
) -> pd.DataFrame:
    """Re-solve with noisy xPts and count how often each first-week move/captain appears."""
    rng = np.random.default_rng(seed)
    gws = horizon_gws(proj, state, opts)
    elements = _pool(proj, state, opts, gws)
    pv = proj[proj["gw"].isin(gws) & proj["element"].isin(elements)]
    xp = (
        pv.pivot_table(index="element", columns="gw", values="xpts", aggfunc="sum")
        .reindex(index=elements, columns=gws)
        .fillna(0.0)
        .to_numpy()
    )
    xm = (
        pv.pivot_table(index="element", columns="gw", values="xmins", aggfunc="sum")
        .reindex(index=elements, columns=gws)
        .fillna(0.0)
        .to_numpy()
    )
    # noise grows with minutes uncertainty and with distance into the horizon
    sd = sd_scale * (0.12 * xp + 0.25 * (1 - np.clip(xm / 90, 0, 1)) * np.sqrt(np.maximum(xp, 0)))
    sd *= np.sqrt(1 + 0.25 * np.arange(len(gws)))[None, :]
    moves: Counter = Counter()
    caps: Counter = Counter()
    o = replace(opts, time_limit=min(opts.time_limit, 30), mip_gap=max(opts.mip_gap, 0.01))
    for _ in range(n):
        noisy = np.maximum(0, xp + rng.normal(0, 1, xp.shape) * sd)
        plan, *_ = build_and_solve(proj, state, rules, o, elements, xp_override=noisy)
        if not plan.weeks:
            continue
        w = plan.weeks[0]
        key = (tuple(sorted(w.transfers_out)), tuple(sorted(w.transfers_in)), w.chip)
        moves[key] += 1
        caps[w.captain] += 1
    rows = [
        {"out": list(k[0]), "in": list(k[1]), "chip": k[2], "share": c / n} for k, c in moves.most_common()
    ]
    df = pd.DataFrame(rows)
    df.attrs["captains"] = {int(k): v / n for k, v in caps.most_common()}
    return df
