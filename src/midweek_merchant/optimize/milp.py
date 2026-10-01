"""Multi-gameweek FPL squad/transfer/chip optimiser (MILP, HiGHS).

The formulation follows the open-fpl-solver approach, reimplemented and adapted to the
2026/27 rules (two chip sets split at GW19/20, one chip per GW, no back-to-back Free
Hits, banked FTs frozen through Wildcard/Free Hit weeks).

Per player i and week h: squad, lineup, captain, vice, bench slot (GK + 3 outfield),
transfer in, transfer out (first sale of an owned player at its selling price, later
sales at buy price), Free Hit squad, triple captain. Per week: chip flags, bank, free
transfers, transfer count and hits. FT dynamics clamp to [1, 5] with an indicator.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from midweek_merchant.config import OptimizerConfig
from midweek_merchant.optimize.linmodel import LinModel, Solution
from midweek_merchant.rules import Rules
from midweek_merchant.team.reconstruct import TeamState

log = logging.getLogger(__name__)

CHIPS = ("wildcard", "freehit", "bboost", "3xc")
FT_TERMINAL = {2: 1.5, 3: 1.0, 4: 0.6, 5: 0.3}


@dataclass
class PlanOptions:
    horizon: int = 6
    decay: float = 0.85
    bench_weights: tuple[float, float, float, float] = (0.03, 0.21, 0.06, 0.002)
    vice_weight: float = 0.05
    hit_cost: int = 4
    max_hits_per_gw: int = 2
    transfer_penalty: float = 0.05
    itb_value: float = 0.08  # per £1m left in the bank at the end of the horizon
    ft_terminal: dict[int, float] = field(default_factory=lambda: dict(FT_TERMINAL))
    chip_option_value: dict[str, float] = field(
        default_factory=lambda: {"wildcard": 6.0, "freehit": 5.0, "bboost": 5.0, "3xc": 3.0}
    )
    ft_after_chip: str = "freeze"
    allow_chips: bool = True
    forced_chips: dict[int, str] = field(default_factory=dict)  # gw -> chip
    banned_chips: set[str] = field(default_factory=set)
    locked: set[int] = field(default_factory=set)
    banned: set[int] = field(default_factory=set)
    booked_in: dict[int, set[int]] = field(default_factory=dict)  # gw -> elements
    booked_out: dict[int, set[int]] = field(default_factory=dict)
    no_transfer_gws: set[int] = field(default_factory=set)
    max_transfers_gw: dict[int, int] = field(default_factory=dict)
    free_first_week: bool = False  # building from scratch (wildcard-style first week)
    last_gw_chip: str | None = None  # chip played in the GW before the horizon (for FH spacing)
    time_limit: float = 60
    mip_gap: float = 0.003
    pool_quota: dict[str, int] | None = None

    @classmethod
    def from_config(cls, cfg: OptimizerConfig, **kw: Any) -> PlanOptions:
        base = dict(
            horizon=cfg.horizon,
            decay=cfg.decay,
            bench_weights=tuple(cfg.bench_weights),
            vice_weight=cfg.vice_weight,
            hit_cost=cfg.hit_cost,
            max_hits_per_gw=cfg.max_hits_per_gw,
            transfer_penalty=cfg.transfer_penalty,
            itb_value=cfg.itb_value,
            chip_option_value=dict(cfg.chip_option_value),
            ft_after_chip=cfg.ft_after_chip,
            time_limit=cfg.time_limit,
            mip_gap=cfg.mip_gap,
        )
        base.update(kw)
        return cls(**base)


@dataclass
class WeekPlan:
    gw: int
    chip: str | None
    transfers_in: list[int]
    transfers_out: list[int]
    squad: list[int]
    lineup: list[int]
    bench: list[int]  # ordered: GK, then outfield 1..3
    captain: int
    vice: int
    free_transfers: int
    hits: int
    bank: int  # tenths after this week's transfers
    xpts: float  # expected points incl. captain/TC/BB, minus hit cost
    xpts_lineup: float


@dataclass
class Plan:
    status: str
    objective: float
    gap: float
    runtime: float
    weeks: list[WeekPlan]
    pool_size: int

    @property
    def total_xpts(self) -> float:
        return float(sum(w.xpts for w in self.weeks))

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        d = asdict(self)
        d["total_xpts"] = self.total_xpts
        return d


class _Built:
    """Holds variable index arrays of one built model."""

    def __init__(self) -> None:
        self.v: dict[str, Any] = {}


def build_and_solve(
    proj: pd.DataFrame,
    state: TeamState,
    rules: Rules,
    opts: PlanOptions,
    elements: list[int],
    extra_cuts: list[tuple[np.ndarray, np.ndarray, float]] | None = None,
    xp_override: np.ndarray | None = None,
) -> tuple[Plan, LinModel, _Built, Solution]:
    gws = [int(g) for g in sorted(proj["gw"].unique()) if g >= state.next_gw][: opts.horizon]
    H, P = len(gws), len(elements)
    eidx = {e: i for i, e in enumerate(elements)}
    info = proj.drop_duplicates("element").set_index("element").loc[elements]
    pos = info["position"].to_numpy()
    club = info["team"].to_numpy()
    buy = info["now_cost"].to_numpy(int)
    xp = np.zeros((P, H)) if xp_override is None else xp_override
    if xp_override is None:
        pv = (
            proj[proj["gw"].isin(gws) & proj["element"].isin(elements)]
            .pivot_table(index="element", columns="gw", values="xpts", aggfunc="sum")
            .reindex(index=elements, columns=gws)
        )
        xp = pv.fillna(0.0).to_numpy()

    owned = np.zeros(P, dtype=bool)
    sell = buy.copy()
    for sp in state.squad:
        if sp.element in eidx:
            i = eidx[sp.element]
            owned[i] = True
            sell[i] = sp.selling_price
    fh_cost = np.where(owned, sell, buy)
    own_idx = np.flatnonzero(owned)

    m = LinModel()
    b = _Built()
    sq = m.add_vars((P, H))
    lu = m.add_vars((P, H))
    cap = m.add_vars((P, H))
    bn = m.add_vars((P, H))
    tin = m.add_vars((P, H))
    tout_r = m.add_vars((P, H))
    tout_f = m.add_vars((len(own_idx), H))
    itb = m.add_vars(H, 0, 5000, integer=False)
    ft = m.add_vars(H, 1, rules.max_free_transfers, integer=True)
    ntr = m.add_vars(H, 0, 15, integer=True)
    hits = m.add_vars(H, 0, opts.max_hits_per_gw, integer=True)
    zreg = m.add_vars(H)
    ft_end = m.add_var(1, rules.max_free_transfers, integer=True)
    y_ft = m.add_vars(len(opts.ft_terminal), 0, 1, integer=False)

    # chip availability per week
    avail = _chip_availability(state, rules, gws, opts)
    use = {c: m.add_vars(H) for c in ("wildcard", "freehit", "bboost")}
    for c in use:
        for h in range(H):
            if not avail[c][h]:
                m.set_bounds(use[c][h], ub=0)
    tc_on = any(avail["3xc"])
    tc = m.add_vars((P, H)) if tc_on else None
    if tc is not None:
        for h in range(H):
            if not avail["3xc"][h]:
                m.set_bounds(tc[:, h], ub=0)
    fh_on = any(avail["freehit"])
    sqfh = m.add_vars((P, H)) if fh_on else None
    b.v.update(
        sq=sq,
        lu=lu,
        cap=cap,
        bn=bn,
        tin=tin,
        tout_r=tout_r,
        tout_f=tout_f,
        itb=itb,
        ft=ft,
        ntr=ntr,
        hits=hits,
        use=use,
        tc=tc,
        sqfh=sqfh,
        own_elements=[elements[i] for i in own_idx],
        is_gk=pos == "GKP",
    )

    is_gk = pos == "GKP"

    # locks / bans / booked
    for e in opts.locked & set(elements):
        m.set_bounds(sq[eidx[e]], lb=1)
    for e in opts.banned & set(elements):
        m.set_bounds(sq[eidx[e]], ub=0)
        m.set_bounds(lu[eidx[e]], ub=0)
    for gw, els in opts.booked_in.items():
        if gw in gws:
            for e in els & set(elements):
                m.set_bounds(tin[eidx[e], gws.index(gw)], lb=1)
    for gw, els in opts.booked_out.items():
        if gw in gws:
            for e in els & set(elements):
                i = eidx[e]
                if owned[i]:
                    m.set_bounds(tout_f[int(np.searchsorted(own_idx, i)), gws.index(gw)], lb=1)
    for gw in opts.no_transfer_gws:
        if gw in gws:
            m.set_bounds(ntr[gws.index(gw)], ub=0)
    for gw, k in opts.max_transfers_gw.items():
        if gw in gws:
            m.set_bounds(ntr[gws.index(gw)], ub=k)

    own_pos = {i: k for k, i in enumerate(own_idx)}
    a_ft = 1 if opts.ft_after_chip == "accrue" else 0
    groups_pos = {p_: np.flatnonzero(pos == p_) for p_ in rules.squad_select}
    groups_club = {c_: np.flatnonzero(club == c_) for c_ in np.unique(club)}

    for h in range(H):
        wc_h, fh_h, bb_h = use["wildcard"][h], use["freehit"][h], use["bboost"][h]
        # --- squad flow & transfer exclusivity
        for i in range(P):
            idx = [sq[i, h], tin[i, h], tout_r[i, h]]
            val = [1.0, -1.0, 1.0]
            if owned[i]:
                idx.append(tout_f[own_pos[i], h])
                val.append(1.0)
            if h > 0:
                idx.append(sq[i, h - 1])
                val.append(-1.0)
                m.eq(idx, val, 0.0)
            else:
                m.eq(idx, val, 1.0 if owned[i] else 0.0)
            ex = [tin[i, h], tout_r[i, h]] + ([tout_f[own_pos[i], h]] if owned[i] else [])
            m.le(ex, 1.0, 1.0)
        # owned players: regular-price sale only after a first sale
        for k, i in enumerate(own_idx):
            idx = [tout_r[i, h]] + [tout_f[k, hh] for hh in range(h)]
            m.le(idx, [1.0] + [-1.0] * h, 0.0)
        # --- squad composition
        for p_, ids in groups_pos.items():
            m.eq(sq[ids, h], 1.0, rules.squad_select[p_])
        for ids in groups_club.values():
            m.le(sq[ids, h], 1.0, rules.team_limit)
        # --- budget
        idx = [itb[h]] + list(tin[:, h]) + list(tout_r[:, h]) + list(tout_f[:, h])
        val = [1.0] + list(buy.astype(float)) + list(-buy.astype(float)) + list(-sell[own_idx].astype(float))
        if h > 0:
            m.eq(idx + [itb[h - 1]], val + [-1.0], 0.0)
        else:
            m.eq(idx, val, float(state.bank))
        # --- transfer count / hits
        m.eq(list(tin[:, h]) + [ntr[h]], [1.0] * P + [-1.0], 0.0)
        if opts.free_first_week and h == 0:
            m.set_bounds(hits[0], ub=0)
        else:
            m.ge([hits[h], ntr[h], ft[h], wc_h, fh_h], [1.0, -1.0, 1.0, 15.0, 15.0], 0.0)
        if not (opts.free_first_week and h == 0):
            # transfers cap (20) does not apply to WC/FH weeks; squad size makes it moot there anyway
            m.le([ntr[h], wc_h], [1.0, -15.0], float(rules.transfers_cap))
        # --- Free Hit squad
        if sqfh is not None:
            m.le(list(tin[:, h]) + [fh_h], [1.0] * P + [15.0], 15.0)
            for i in range(P):
                m.le([sqfh[i, h], fh_h], [1.0, -1.0], 0.0)
            for p_, ids in groups_pos.items():
                m.eq(list(sqfh[ids, h]) + [fh_h], [1.0] * len(ids) + [-float(rules.squad_select[p_])], 0.0)
            for ids in groups_club.values():
                m.le(list(sqfh[ids, h]) + [fh_h], [1.0] * len(ids) + [-float(rules.team_limit)], 0.0)
            # FH budget: squad value (selling prices) + bank before the week
            val_prev = np.where(owned, sell, buy).astype(float)
            idx = list(sqfh[:, h])
            val = list(fh_cost.astype(float))
            if h > 0:
                m.le(idx + list(sq[:, h - 1]) + [itb[h - 1]], val + list(-val_prev) + [-1.0], 0.0)
            else:
                m.le(idx, val, float(state.bank + np.sum(sell[owned])))
        # --- lineup / bench from the active squad
        for i in range(P):
            act = [lu[i, h], bn[i, h]]
            if sqfh is not None:
                m.le(act + [sq[i, h], fh_h], [1.0, 1.0, -1.0, -1.0], 0.0)
                m.le(act + [sqfh[i, h], fh_h], [1.0, 1.0, -1.0, 1.0], 1.0)
            else:
                m.le(act + [sq[i, h]], [1.0, 1.0, -1.0], 0.0)
        m.eq(list(lu[:, h]) + [bb_h], [1.0] * P + [-4.0], float(rules.squad_play))
        gk = groups_pos["GKP"]
        m.eq(list(lu[gk, h]) + [bb_h], [1.0] * len(gk) + [-1.0], 1.0)
        for p_ in ("DEF", "MID", "FWD"):
            m.ge(lu[groups_pos[p_], h], 1.0, float(rules.play_min[p_]))
        # bench: one GK and three outfielders (none with Bench Boost)
        m.eq(list(bn[gk, h]) + [bb_h], [1.0] * len(gk) + [1.0], 1.0)
        m.eq(list(bn[:, h]) + [bb_h], [1.0] * P + [4.0], 4.0)
        # --- captaincy (vice-captain is chosen after solving)
        m.eq(cap[:, h], 1.0, 1.0)
        for i in range(P):
            m.le([cap[i, h], lu[i, h]], [1.0, -1.0], 0.0)
            if tc is not None:
                m.le([tc[i, h], cap[i, h]], [1.0, -1.0], 0.0)
        # --- one chip per week
        chip_idx = [wc_h, fh_h, bb_h] + (list(tc[:, h]) if tc is not None else [])
        m.le(chip_idx, 1.0, 1.0)
        if h + 1 < H:
            m.le([fh_h, use["freehit"][h + 1]], [1.0, 1.0], 1.0)
        # --- free-transfer dynamics h -> h+1
        nxt = ft[h + 1] if h + 1 < H else ft_end
        if opts.free_first_week and h == 0:
            m.set_bounds(nxt, ub=1)
        else:
            m.le([nxt, ft[h], ntr[h], zreg[h], wc_h, fh_h], [1, -1, 1, -5, -20, -20], 1.0)
            m.le([nxt, zreg[h], wc_h, fh_h], [1, 5, -20, -20], 6.0)
            m.le([nxt, ft[h], wc_h, fh_h], [1, -1, 5, 5], float(a_ft + 5))

    # initial FTs
    if opts.free_first_week:
        m.set_bounds(ft[0], lb=1, ub=1)
    else:
        m.set_bounds(ft[0], lb=state.free_transfers, ub=state.free_transfers)
    # forced chips
    for gw, chip in opts.forced_chips.items():
        if gw in gws:
            h = gws.index(gw)
            if chip == "3xc" and tc is not None:
                m.eq(tc[:, h], 1.0, 1.0)
            elif chip in use:
                m.set_bounds(use[chip][h], lb=1)
    # each chip at most once per half-season window
    for c in CHIPS:
        for w in rules.chip_windows(c):
            hs = [h for h, gw in enumerate(gws) if w.start_event <= gw <= w.stop_event]
            if not hs:
                continue
            if c == "3xc":
                if tc is not None:
                    m.le(tc[:, hs].ravel(), 1.0, 1.0)
            else:
                m.le(use[c][hs], 1.0, 1.0)
    # terminal FT value
    m.ge([ft_end] + list(y_ft), [1.0] + [-1.0] * len(y_ft), 1.0)

    # ------------------------------------------------------------------ objective
    d = opts.decay ** np.arange(H)
    bw = np.array(opts.bench_weights, dtype=float)
    # one bench weight per player: GK slot weight for keepers, mean outfield slot weight otherwise
    bench_w = np.where(is_gk, bw[0], bw[1:].mean())
    for h in range(H):
        m.add_obj(lu[:, h], d[h] * xp[:, h])
        m.add_obj(cap[:, h], d[h] * xp[:, h])
        m.add_obj(bn[:, h], d[h] * bench_w * xp[:, h])
        if tc is not None:
            m.add_obj(tc[:, h], d[h] * xp[:, h])
        m.add_obj(hits[h], -d[h] * opts.hit_cost)
        m.add_obj(ntr[h], -d[h] * opts.transfer_penalty)
    m.add_obj(itb[H - 1], opts.itb_value / 10.0)
    for k, (_, v) in enumerate(sorted(opts.ft_terminal.items())):
        m.add_obj(y_ft[k], (opts.decay**H) * v)
    # option value of keeping chips (spent chips forgo it)
    opt_val = _chip_option_values(state, rules, gws, opts)
    for c, vals in opt_val.items():
        for h, v in enumerate(vals):
            if v <= 0:
                continue
            if c == "3xc":
                if tc is not None:
                    m.add_obj(tc[:, h], -v)
            else:
                m.add_obj(use[c][h], -v)

    for idx, val, rhs in extra_cuts or []:
        m.le(idx, val, rhs)

    sol = m.solve(maximize=True, time_limit=opts.time_limit, mip_gap=opts.mip_gap)
    plan = _extract(sol, b, gws, elements, xp, opts, len(elements))
    return plan, m, b, sol


def _chip_availability(
    state: TeamState, rules: Rules, gws: list[int], opts: PlanOptions
) -> dict[str, list[bool]]:
    out: dict[str, list[bool]] = {}
    for c in CHIPS:
        halves = state.chips_available.get(c, []) if opts.allow_chips and c not in opts.banned_chips else []
        flags = []
        for gw in gws:
            ok = False
            for w in rules.chip_windows(c):
                if w.start_event <= gw <= w.stop_event and rules.chip_half(w.start_event) in halves:
                    ok = True
            if c == "freehit" and gw == gws[0] and opts.last_gw_chip == "freehit":
                ok = False
            flags.append(ok)
        out[c] = flags
    for gw, chip in opts.forced_chips.items():
        if gw in gws:
            out[chip][gws.index(gw)] = True
    return out


def _chip_option_values(
    state: TeamState, rules: Rules, gws: list[int], opts: PlanOptions
) -> dict[str, list[float]]:
    """Value forgone by spending a chip now rather than later in its window."""
    out: dict[str, list[float]] = {}
    last = gws[-1]
    for c in CHIPS:
        base = opts.chip_option_value.get(c, 0.0)
        vals = []
        for gw in gws:
            v = 0.0
            for w in rules.chip_windows(c):
                if w.start_event <= gw <= w.stop_event:
                    remaining_after = w.stop_event - last
                    v = base * min(1.0, max(0.0, remaining_after) / 6.0)
            vals.append(v)
        out[c] = vals
    return out


def _extract(
    sol: Solution,
    b: _Built,
    gws: list[int],
    elements: list[int],
    xp: np.ndarray,
    opts: PlanOptions,
    pool_size: int,
) -> Plan:
    if not sol.ok:
        return Plan(sol.status, float("nan"), sol.gap, sol.runtime, [], pool_size)
    x = sol.x
    v = b.v
    val = lambda a: np.rint(x[a]).astype(int)  # noqa: E731
    weeks = []
    for h, gw in enumerate(gws):
        chip = None
        for c, arr in v["use"].items():
            if val(arr[h]) == 1:
                chip = c
        tc_h = val(v["tc"][:, h]) if v["tc"] is not None else np.zeros(len(elements), int)
        if tc_h.sum() == 1:
            chip = "3xc"
        lineup = np.flatnonzero(val(v["lu"][:, h]))
        bench_idx = np.flatnonzero(val(v["bn"][:, h]))
        # bench order: GK first, then outfielders by expected points
        gk_b = [i for i in bench_idx if v["is_gk"][i]]
        out_b = sorted((i for i in bench_idx if not v["is_gk"][i]), key=lambda i: -xp[i, h])
        bench = [elements[i] for i in gk_b + out_b]
        cap = int(np.flatnonzero(val(v["cap"][:, h]))[0])
        others = [i for i in lineup if i != cap]
        vic = max(others, key=lambda i: xp[i, h]) if others else cap
        squad_arr = v["sqfh"][:, h] if (chip == "freehit" and v["sqfh"] is not None) else v["sq"][:, h]
        squad = [elements[i] for i in np.flatnonzero(val(squad_arr))]
        t_in = [elements[i] for i in np.flatnonzero(val(v["tin"][:, h]))]
        t_out = [elements[i] for i in np.flatnonzero(val(v["tout_r"][:, h]))]
        if v["tout_f"].size:  # rows of tout_f follow the owned-player order
            t_out += [v["own_elements"][k] for k in np.flatnonzero(val(v["tout_f"][:, h]))]
        hits = int(val(v["hits"][h]))
        mult = 3 if chip == "3xc" else 2
        xl = float(xp[lineup, h].sum())
        xpts = xl + (mult - 1) * float(xp[cap, h]) - opts.hit_cost * hits
        weeks.append(
            WeekPlan(
                gw=gw,
                chip=chip,
                transfers_in=t_in,
                transfers_out=t_out,
                squad=squad,
                lineup=[elements[i] for i in lineup],
                bench=bench,
                captain=elements[cap],
                vice=elements[vic],
                free_transfers=int(val(v["ft"][h])),
                hits=hits,
                bank=int(round(x[v["itb"][h]])),
                xpts=xpts,
                xpts_lineup=xl,
            )
        )
    return Plan(sol.status, sol.objective, sol.gap, sol.runtime, weeks, pool_size)
