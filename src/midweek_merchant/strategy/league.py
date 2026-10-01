"""Mini-league strategy: rivals, effective ownership and Monte Carlo win probability.

Key fact: against any rival, the expected change in the points gap is my expected points
minus theirs, and their part does not depend on my choices. So maximising xPts also
maximises the expected gap; effective ownership (EO) matters through *variance*. When
behind, owning players your rivals do not (swords) widens the spread of outcomes and
raises the chance of catching up; when ahead, owning what they own (shields) narrows it.
This module quantifies that with correlated simulations of everyone's scores.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from midweek_merchant.data.fpl_api import FPLClient, FPLNotFound
from midweek_merchant.models.simulate import SimResult
from midweek_merchant.optimize.milp import Plan
from midweek_merchant.rules import Rules
from midweek_merchant.team.reconstruct import TeamState, reconstruct

log = logging.getLogger(__name__)


@dataclass
class Lineup:
    """Who plays and with what multiplier in one gameweek."""

    starters: list[int]
    bench: list[int]
    captain: int
    vice: int
    triple: bool = False
    bench_boost: bool = False
    hits: int = 0


@dataclass
class Manager:
    entry: int
    name: str
    player_name: str
    total: int
    rank: int
    state: TeamState | None = None
    lineups: dict[int, Lineup] = field(default_factory=dict)
    last_picks: dict[str, Any] | None = None


def load_league(
    client: FPLClient,
    league_id: int,
    players: pd.DataFrame,
    rules: Rules,
    next_gw: int,
    max_managers: int = 30,
    ft_after_chip: str = "freeze",
) -> tuple[dict, list[Manager]]:
    meta, rows = client.league_classic_all(league_id)
    managers = []
    for r in rows[:max_managers]:
        m = Manager(
            entry=r["entry"],
            name=r["entry_name"],
            player_name=r.get("player_name", ""),
            total=int(r["total"]),
            rank=int(r["rank"]),
        )
        try:
            m.state = reconstruct(client, m.entry, players, rules, next_gw, ft_after_chip)
            last = max(u["event"] for u in client.entry_history(m.entry)["current"])
            m.last_picks = client.entry_picks(m.entry, last)
        except (FPLNotFound, ValueError, KeyError) as exc:
            log.warning("rival %s skipped: %s", m.entry, exc)
        managers.append(m)
    return meta, managers


def best_xi(squad: list[tuple[int, str]], xp: dict[int, float], rules: Rules) -> Lineup:
    """Exact best XI for a fixed squad: fill formation minimums, then best remaining outfielders."""
    by_pos: dict[str, list[int]] = {}
    for e, pos in squad:
        by_pos.setdefault(pos, []).append(e)
    for pos in by_pos:
        by_pos[pos].sort(key=lambda e: -xp.get(e, 0.0))
    starters = by_pos.get("GKP", [])[:1]
    for pos in ("DEF", "MID", "FWD"):
        starters += by_pos.get(pos, [])[: rules.play_min[pos]]
    rest = [e for pos in ("DEF", "MID", "FWD") for e in by_pos.get(pos, [])[rules.play_min[pos] :]]
    rest.sort(key=lambda e: -xp.get(e, 0.0))
    count = {pos: rules.play_min[pos] for pos in ("DEF", "MID", "FWD")}
    pos_of = dict(squad)
    for e in rest:
        if len(starters) == rules.squad_play:
            break
        if count[pos_of[e]] < rules.play_max[pos_of[e]]:
            starters.append(e)
            count[pos_of[e]] += 1
    bench_gk = by_pos.get("GKP", [])[1:]
    bench_out = sorted(
        (e for e, _ in squad if e not in starters and e not in bench_gk), key=lambda e: -xp.get(e, 0.0)
    )
    ranked = sorted(starters, key=lambda e: -xp.get(e, 0.0))
    return Lineup(starters, bench_gk + bench_out, ranked[0], ranked[1] if len(ranked) > 1 else ranked[0])


def rival_lineups(m: Manager, proj: pd.DataFrame, rules: Rules, gws: list[int]) -> None:
    """Predict a rival's lineups: keep their squad, best XI and captain by our xPts each week."""
    if m.state is None:
        return
    squad = [(p.element, p.position) for p in m.state.squad]
    for gw in gws:
        xp = proj[proj["gw"] == gw].set_index("element")["xpts"].to_dict()
        m.lineups[gw] = best_xi(squad, xp, rules)


def plan_lineups(plan: Plan) -> dict[int, Lineup]:
    return {
        w.gw: Lineup(
            starters=w.lineup if w.chip != "bboost" else w.squad,
            bench=[] if w.chip == "bboost" else w.bench,
            captain=w.captain,
            vice=w.vice,
            triple=w.chip == "3xc",
            bench_boost=w.chip == "bboost",
            hits=w.hits,
        )
        for w in plan.weeks
    }


OUTFIELD = ("DEF", "MID", "FWD")
FORMATION_MIN = {"DEF": 3, "MID": 2, "FWD": 1}


def _autosubs(sim: SimResult, gw: int, starters: list[int], bench: list[int]) -> np.ndarray:
    """Extra points from FPL automatic substitutions, per simulation.

    FPL rules: only the bench goalkeeper can replace a starting goalkeeper; outfield bench
    players come on in bench order, each replacing a non-playing starter only if the team
    still has at least 3 DEF, 2 MID and 1 FWD afterwards.
    """
    col = sim.column()
    pts, played = sim.points[gw], sim.played[gw]
    S = pts.shape[0]
    pos = sim.positions or {}
    extra = np.zeros(S)
    st = [e for e in starters if e in col]
    bn = [e for e in bench if e in col]
    if not pos:  # positions unknown: plain bench order
        if not bn or not st:
            return extra
        missing = (~played[:, [col[e] for e in st]]).sum(axis=1)
        bpl = played[:, [col[e] for e in bn]]
        use = bpl & (np.cumsum(bpl, axis=1) <= missing[:, None])
        return (pts[:, [col[e] for e in bn]] * use).sum(axis=1)
    gk_s = [e for e in st if pos.get(e) == "GKP"]
    gk_b = [e for e in bn if pos.get(e) == "GKP"]
    if gk_s and gk_b:
        swap = ~played[:, col[gk_s[0]]] & played[:, col[gk_b[0]]]
        extra += np.where(swap, pts[:, col[gk_b[0]]], 0.0)
    out_s = [e for e in st if pos.get(e) in OUTFIELD]
    out_b = [e for e in bn if pos.get(e) in OUTFIELD]
    if not out_s or not out_b:
        return extra
    s_pos = np.array([OUTFIELD.index(pos[e]) for e in out_s])
    missing = ~played[:, [col[e] for e in out_s]]  # [S, n_starters]
    counts = np.tile(np.bincount(s_pos, minlength=3), (S, 1))  # players per position in the XI
    mins = np.array([FORMATION_MIN[p] for p in OUTFIELD])
    for e in out_b:
        b = OUTFIELD.index(pos[e])
        came_on = played[:, col[e]]
        # a missing starter can be replaced if same position or his position stays above its minimum
        ok = missing & ((s_pos[None, :] == b) | (counts[:, s_pos] - 1 >= mins[s_pos][None, :]))
        rows = np.flatnonzero(came_on & ok.any(axis=1))
        if not len(rows):
            continue
        first = ok[rows].argmax(axis=1)
        missing[rows, first] = False
        np.subtract.at(counts, (rows, s_pos[first]), 1)
        np.add.at(counts, (rows, np.full(len(rows), b)), 1)
        extra[rows] += pts[rows, col[e]]
    return extra


def score_lineup(sim: SimResult, gw: int, lu: Lineup) -> np.ndarray:
    """Simulated points for a lineup with FPL auto-substitutions and the vice-captain fallback."""
    col = sim.column()
    pts, played = sim.points[gw], sim.played[gw]
    S = pts.shape[0]
    idx = [col[e] for e in lu.starters if e in col]
    total = pts[:, idx].sum(axis=1) if idx else np.zeros(S)
    if not lu.bench_boost and lu.bench:
        total = total + _autosubs(sim, gw, lu.starters, lu.bench)
    mult = 2 if lu.triple else 1
    ci, vi = col.get(lu.captain), col.get(lu.vice)
    cap_pts = pts[:, ci] if ci is not None else np.zeros(S)
    cap_played = played[:, ci] if ci is not None else np.zeros(S, bool)
    vice_pts = pts[:, vi] if vi is not None else np.zeros(S)
    total = total + mult * np.where(cap_played, cap_pts, vice_pts)
    return total - 4 * lu.hits


def league_eo(rivals: list[Manager], gw: int) -> dict[int, float]:
    """Effective ownership (%) among rivals for one gameweek: starters count 1, captain +1 (TC +2)."""
    eo: dict[int, float] = {}
    n = 0
    for r in rivals:
        lu = r.lineups.get(gw)
        if not lu:
            continue
        n += 1
        for e in lu.starters:
            eo[e] = eo.get(e, 0.0) + 1
        eo[lu.captain] = eo.get(lu.captain, 0.0) + (2 if lu.triple else 1)
    return {e: v / max(n, 1) * 100 for e, v in eo.items()}


def candidate_locks(
    eo: dict[int, float], my_squad: set[int], proj: pd.DataFrame, gws: list[int], n: int = 2
) -> dict[str, list[int]]:
    """Shields (high league EO, not owned) and swords (high xPts, low EO, not owned) to test."""
    xp = proj[proj["gw"].isin(gws)].groupby("element")["xpts"].sum()
    shields = [e for e, v in sorted(eo.items(), key=lambda kv: -kv[1]) if v >= 50 and e not in my_squad][:n]
    cand = xp.drop(index=[e for e in my_squad if e in xp.index], errors="ignore").sort_values(ascending=False)
    swords = [int(e) for e in cand.index if eo.get(int(e), 0.0) <= 15][:n]
    return {"shield": shields, "sword": swords}


@dataclass
class LeagueAnalysis:
    standings: pd.DataFrame
    eo: pd.DataFrame
    plans: pd.DataFrame
    captains: pd.DataFrame
    head_to_head: pd.DataFrame
    advice: str
    z: float
    best_plan: int


def analyse(
    me: Manager,
    rivals: list[Manager],
    my_plans: list[Plan],
    sim: SimResult,
    proj: pd.DataFrame,
    gws: list[int],
    weeks_left_after: int,
    plan_labels: list[str] | None = None,
    seed: int = 11,
) -> LeagueAnalysis:
    rng = np.random.default_rng(seed)
    info = proj.drop_duplicates("element").set_index("element")
    first = gws[0]
    S = sim.points[first].shape[0]
    rivals = [r for r in rivals if first in r.lineups]
    plan_labels = plan_labels or [f"option {k + 1}" for k in range(len(my_plans))]

    riv_first = (
        np.column_stack([score_lineup(sim, first, r.lineups[first]) for r in rivals])
        if rivals
        else np.zeros((S, 0))
    )
    riv_h = (
        np.column_stack(
            [
                r.total + sum(score_lineup(sim, gw, r.lineups[gw]) for gw in gws if gw in r.lineups)
                for r in rivals
            ]
        )
        if rivals
        else np.zeros((S, 0))
    )

    base_lus = plan_lineups(my_plans[0])
    my_first = score_lineup(sim, first, base_lus[first])
    # Weekly spread of score *differences* (shared players cancel), used beyond the horizon.
    sd_diff = (
        float(np.mean([np.std(my_first - riv_first[:, j]) for j in range(riv_first.shape[1])]))
        if rivals
        else 12.0
    )
    idio = sd_diff / np.sqrt(2) * np.sqrt(max(weeks_left_after, 0))
    ext = rng.normal(0, idio, (S, 1 + len(rivals)))  # common random numbers across plans

    plan_rows = []
    for k, plan in enumerate(my_plans):
        lus = plan_lineups(plan)
        mine = me.total + sum(score_lineup(sim, gw, lus[gw]) for gw in gws if gw in lus)
        allsc = np.column_stack([mine, riv_h])
        rank = 1 + (allsc[:, 1:] > allsc[:, :1]).sum(axis=1)
        final = allsc + ext
        w0 = plan.weeks[0]
        plan_rows.append(
            {
                "option": k + 1,
                "type": plan_labels[k],
                "this_week": ", ".join(
                    f"{info.loc[o, 'name']} → {info.loc[i, 'name']}"
                    for o, i in zip(w0.transfers_out, w0.transfers_in, strict=False)
                )
                or "roll",
                "hits": w0.hits,
                "captain": info.loc[w0.captain, "name"],
                "chip": w0.chip or "",
                "xpts_horizon": round(plan.total_xpts, 1),
                "mean_rank_horizon": round(float(rank.mean()), 2),
                "p_first_horizon": float(np.mean(rank == 1)),
                "p_first_season": float(np.mean(final[:, 0] >= final[:, 1:].max(axis=1))) if rivals else 1.0,
            }
        )
    plans_df = pd.DataFrame(plan_rows)
    best = (
        int(plans_df.sort_values(["p_first_season", "xpts_horizon"], ascending=False).iloc[0]["option"]) - 1
    )

    lus = plan_lineups(my_plans[best])
    mine = me.total + sum(score_lineup(sim, gw, lus[gw]) for gw in gws if gw in lus)
    scores = np.column_stack([mine, riv_h])
    ranks = 1 + (scores[:, :, None] < scores[:, None, :]).sum(axis=2)
    final = scores + ext
    franks = 1 + (final[:, :, None] < final[:, None, :]).sum(axis=2)
    standings = pd.DataFrame(
        {
            "manager": [me.name] + [r.name for r in rivals],
            "now": [me.total] + [r.total for r in rivals],
            "projected": scores.mean(axis=0).round(1),
            "p_lead_after_horizon": (ranks == 1).mean(axis=0),
            "p_win_league": (franks == 1).mean(axis=0),
            "is_me": [True] + [False] * len(rivals),
        }
    ).sort_values("projected", ascending=False)

    eo_map = league_eo(rivals, first)
    my_lu = lus[first]
    my_mult = {e: 1 for e in my_lu.starters}
    my_mult[my_lu.captain] = 3 if my_lu.triple else 2
    xp = proj[proj["gw"] == first].set_index("element")["xpts"]
    eo = pd.DataFrame(
        [
            {
                "element": e,
                "name": info.loc[e, "name"],
                "team": info.loc[e, "team_short"],
                "position": info.loc[e, "position"],
                "xpts": float(xp.get(e, 0.0)),
                "league_eo": eo_map.get(e, 0.0),
                "my_mult": my_mult.get(e, 0),
            }
            for e in set(eo_map) | set(my_mult)
            if e in info.index
        ]
    )
    eo["net_exposure"] = eo["my_mult"] * 100 - eo["league_eo"]
    eo["role"] = np.select(
        [(eo["my_mult"] == 0) & (eo["league_eo"] >= 50), (eo["my_mult"] > 0) & (eo["league_eo"] <= 25)],
        ["shield: rivals have, you don't", "sword: you have, rivals don't"],
        default="",
    )
    eo = eo.sort_values("league_eo", ascending=False)

    # captaincy: same team, different armband
    cap_rows = []
    best_riv = riv_first.max(axis=1) if rivals else np.zeros(S)
    for c in sorted(my_lu.starters, key=lambda e: -float(xp.get(e, 0.0)))[:6]:
        alt = Lineup(
            my_lu.starters,
            my_lu.bench,
            c,
            my_lu.vice if my_lu.vice != c else my_lu.captain,
            my_lu.triple,
            my_lu.bench_boost,
            my_lu.hits,
        )
        s_ = score_lineup(sim, first, alt)
        cap_rows.append(
            {
                "captain": info.loc[c, "name"],
                "my_gw_xpts": float(s_.mean()),
                "league_eo": eo_map.get(c, 0.0),
                "p_beat_rival_avg": float(
                    np.mean([(s_ > riv_first[:, j]).mean() for j in range(riv_first.shape[1])])
                )
                if rivals
                else 1.0,
                "p_top_score_gw": float(np.mean(s_ > best_riv)),
                "p_lead_after_gw": float(
                    np.mean(me.total + s_ > (np.array([r.total for r in rivals]) + riv_first).max(axis=1))
                )
                if rivals
                else 1.0,
            }
        )
    captains = pd.DataFrame(cap_rows)

    my_first = score_lineup(sim, first, my_lu)
    h2h = pd.DataFrame(
        [
            {
                "rival": r.name,
                "gap_now": me.total - r.total,
                "p_outscore_this_gw": float(np.mean(my_first > riv_first[:, j])),
                "exp_margin_this_gw": float(np.mean(my_first - riv_first[:, j])),
                "captain": info.loc[r.lineups[first].captain, "name"]
                if r.lineups[first].captain in info.index
                else "",
            }
            for j, r in enumerate(rivals)
        ]
    )

    others = [r.total for r in rivals]
    gap = me.total - max(others) if others else 0
    z = gap / (sd_diff * np.sqrt(max(len(gws) + weeks_left_after, 1)))
    if z <= -0.75:
        advice = (
            "You are behind the leader by more than the usual spread of outcomes, so take calculated "
            "risks. Prefer swords (strong players your rivals don't own) and consider a low-ownership "
            "captain when it costs little in expected points."
        )
    elif z >= 0.75:
        advice = (
            "You are ahead, so protect the lead. Cover shields (popular picks you don't own), captain the "
            "league's favourite unless an alternative is clearly better, and avoid speculative hits."
        )
    else:
        advice = (
            "The race is close: maximise expected points, and use differentials only as tie-breakers "
            "between near-equal options."
        )
    return LeagueAnalysis(standings, eo, plans_df, captains, h2h, advice, float(z), best)
