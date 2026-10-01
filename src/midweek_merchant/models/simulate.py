"""Correlated Monte Carlo simulation of FPL points.

For each fixture a Dixon–Coles scoreline is drawn; each player's minutes state is drawn
(start 60+, start <60, bench appearance, none); team goals are allocated to the players
on the pitch in proportion to their goal shares (assists likewise); clean sheets, goals
conceded, saves, DefCon, cards and bonus follow. Teammates are therefore correlated (a
clean sheet is shared, attackers compete for the same goals) and opponents are
anti-correlated, which is what a mini-league decision needs.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import nbinom

from midweek_merchant.data.odds import _score_matrix
from midweek_merchant.models.player_rates import BONUS_FEATURES, RateParams
from midweek_merchant.rules import DEFCON_THRESHOLD, Rules

MAX_GOALS = 10


@dataclass
class SimResult:
    gws: list[int]
    elements: np.ndarray  # element ids (columns)
    points: dict[int, np.ndarray]  # gw -> [n_sims, n_elements] float32
    played: dict[int, np.ndarray]  # gw -> [n_sims, n_elements] bool (any minutes)

    def column(self) -> dict[int, int]:
        return {int(e): i for i, e in enumerate(self.elements)}

    def mean(self) -> pd.DataFrame:
        rows = []
        for gw in self.gws:
            m, sd = self.points[gw].mean(axis=0), self.points[gw].std(axis=0)
            rows.append(pd.DataFrame({"element": self.elements, "gw": gw, "sim_mean": m, "sim_sd": sd}))
        return pd.concat(rows, ignore_index=True)


def simulate(
    fx: pd.DataFrame,
    params: RateParams,
    rules: Rules,
    n_sims: int = 2000,
    seed: int = 7,
    elements: set[int] | None = None,
) -> SimResult:
    """Simulate points for the (element, fixture) rows in ``fx`` (output of ``fixture_xpts``)."""
    rng = np.random.default_rng(seed)
    fx = fx.copy()
    if elements is not None:
        # keep whole teams of the relevant fixtures so goal allocation stays consistent
        teams_needed = set(
            zip(
                fx.loc[fx["element"].isin(elements), "team"],
                fx.loc[fx["element"].isin(elements), "fixture"],
                strict=True,
            )
        )
        mask = [(t, f) in teams_needed for t, f in zip(fx["team"], fx["fixture"], strict=True)]
        fx = fx[np.array(mask, dtype=bool)]
    gws = sorted(int(g) for g in fx["gw"].unique())
    all_el = np.array(sorted(fx["element"].unique()))
    col = {e: i for i, e in enumerate(all_el)}
    pts = {gw: np.zeros((n_sims, len(all_el)), dtype=np.float32) for gw in gws}
    played = {gw: np.zeros((n_sims, len(all_el)), dtype=bool) for gw in gws}
    coef = {p: np.asarray(c, dtype=float) for p, c in params.bonus_coef.items()}
    bi = {f: k for k, f in enumerate(BONUS_FEATURES)}

    for _fid, g in fx.groupby("fixture", sort=False):
        gw = int(g["gw"].iloc[0])
        home = g[g["is_home"]]
        away = g[~g["is_home"]]
        if not len(home) or not len(away):
            continue
        lh, la, rho = float(home["lam_for"].iloc[0]), float(away["lam_for"].iloc[0]), float(g["rho"].iloc[0])
        mat = _score_matrix(lh, la, rho, MAX_GOALS).ravel()
        draw = rng.choice(mat.size, size=n_sims, p=mat / mat.sum())
        hg, ag = draw // (MAX_GOALS + 1), draw % (MAX_GOALS + 1)
        for side, scored, conceded in ((home, hg, ag), (away, ag, hg)):
            _simulate_side(side, scored, conceded, params, rules, rng, coef, bi, pts[gw], played[gw], col)
    return SimResult(gws, all_el, pts, played)


def _simulate_side(
    side: pd.DataFrame,
    scored: np.ndarray,
    conceded: np.ndarray,
    params: RateParams,
    rules: Rules,
    rng: np.random.Generator,
    coef: dict,
    bi: dict,
    out: np.ndarray,
    played_out: np.ndarray,
    col: dict,
) -> None:
    S, n = len(scored), len(side)
    pos = side["position"].to_numpy()
    # minutes state: 0 none, 1 start60, 2 start<60, 3 sub
    probs = np.column_stack(
        [
            np.clip(1 - side["p_s60"] - side["p_slt"] - side["p_sub_app"], 0, 1),
            side["p_s60"],
            side["p_slt"],
            side["p_sub_app"],
        ]
    ).astype(float)
    probs /= probs.sum(axis=1, keepdims=True)
    u = rng.random((S, n))
    cum = np.cumsum(probs, axis=1)
    state = (u[:, :, None] > cum[None, :, :]).sum(axis=2)  # [S, n] in 0..3
    mins_by_state = np.column_stack([np.zeros(n), side["m_start60"], side["m_start_lt"], side["m_sub"]])
    m = np.take_along_axis(np.broadcast_to(mins_by_state, (S, n, 4)), state[:, :, None], axis=2)[:, :, 0] / 90
    on = state > 0

    # goal & assist allocation
    wg = (side["s_g"] * side["f_g"]).to_numpy(float)[None, :] * m
    wa = (side["s_a"] * side["f_a"]).to_numpy(float)[None, :] * m
    goals = _allocate(scored, wg, rng)
    has_assist = rng.random((S, MAX_GOALS)) < np.clip(wa.sum(axis=1, keepdims=True), 0, 1)
    assists = _allocate(scored, wa / np.maximum(wa.sum(axis=1, keepdims=True), 1e-9), rng, mask=has_assist)

    s60 = state == 1
    cs = s60 & (conceded[:, None] == 0)
    gc = np.where(s60, conceded[:, None], rng.binomial(conceded[:, None].repeat(n, axis=1), np.clip(m, 0, 1)))
    gc = np.where(on, gc, 0)
    lam_a = side["lam_against"].to_numpy(float)[None, :]
    saves = np.where(pos == "GKP", rng.poisson(side["save_k"].to_numpy(float)[None, :] * lam_a * m), 0)
    thr = np.array([DEFCON_THRESHOLD[p] or 10_000 for p in pos], dtype=float)
    size = np.array([params.nb_size[p] for p in pos], dtype=float)
    opp_adj = (lam_a / params.avg_team_xg) ** np.where(pos == "DEF", 0.2, 0.1)[None, :]
    mu_dc = np.maximum(side["dc90"].to_numpy(float)[None, :] * m * opp_adj, 1e-9)
    p_dc = np.where(thr < 10_000, nbinom.sf(thr - 1, size, size / (size + mu_dc)), 0.0)
    dc = (rng.random((S, n)) < p_dc) & on
    yc = (rng.random((S, n)) < side["yc90"].to_numpy(float)[None, :] * m) & on
    rc = (rng.random((S, n)) < side["rc90"].to_numpy(float)[None, :] * m) & on

    goal_pts = np.array([rules.goal_pts[p] for p in pos], dtype=float)
    cs_pts = np.array([rules.cs_pts[p] for p in pos], dtype=float)
    gc_pts = np.array([rules.gc_pts[p] for p in pos], dtype=float)
    dcp = np.array([rules.defcon_pts[p] for p in pos], dtype=float)
    app = np.where(s60, 2, np.where(on, 1, 0))
    saves3 = np.floor(saves / 3)
    feats = {
        "i60": s60.astype(float),
        "ilt": (on & ~s60).astype(float),
        "goals": goals,
        "assists": assists,
        "cs60": cs.astype(float),
        "dc_hit": dc.astype(float),
        "saves3": saves3,
        "gc": np.where(np.isin(pos, ["GKP", "DEF"])[None, :], gc, 0),
    }
    B = np.stack([np.stack([coef[p] for p in pos])[:, bi[f]] for f in BONUS_FEATURES])  # [F, n]
    bonus = np.clip(sum(feats[f] * B[k][None, :] for k, f in enumerate(BONUS_FEATURES)), 0, None) * on
    total = (
        app
        + goal_pts * goals
        + rules.assist_pts * assists
        + cs_pts * cs
        + gc_pts * np.floor(gc / 2)
        + saves3 * rules.save_pts
        + dcp * dc
        + bonus
        + rules.yellow_pts * yc
        + rules.red_pts * rc
    )
    cols = np.array([col[e] for e in side["element"]])
    np.add.at(out, (slice(None), cols), total.astype(np.float32))
    played_out[:, cols] |= on


def _allocate(
    counts: np.ndarray, weights: np.ndarray, rng: np.random.Generator, mask: np.ndarray | None = None
) -> np.ndarray:
    """Allocate ``counts[s]`` events among columns with per-sim ``weights`` (+ an implicit 'other')."""
    S, n = weights.shape
    other = np.clip(1 - weights.sum(axis=1, keepdims=True), 0, None)
    w = np.concatenate([weights, other], axis=1)
    cum = np.cumsum(w / np.maximum(w.sum(axis=1, keepdims=True), 1e-12), axis=1)
    out = np.zeros((S, n))
    for g in range(MAX_GOALS):
        active = counts > g
        if mask is not None:
            active &= mask[:, g]
        if not active.any():
            continue
        u = rng.random(S)[:, None]
        pick = (u > cum).sum(axis=1)
        hit = active & (pick < n)
        out[np.flatnonzero(hit), pick[hit]] += 1
    return out
