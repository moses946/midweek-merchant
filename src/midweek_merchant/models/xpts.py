"""Analytic expected FPL points per player per fixture, aggregated to gameweeks."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import nbinom, poisson

from midweek_merchant.models.player_rates import RateParams
from midweek_merchant.rules import DEFCON_THRESHOLD, Rules

PTS_COLS = ["x_app", "x_goals", "x_assists", "x_cs", "x_gc", "x_saves", "x_dc", "x_bonus", "x_cards"]
STATES = (("s60", "m_start60", 2), ("slt", "m_start_lt", 1), ("sub", "m_sub", 1))


def expected_floor_div(mu: np.ndarray, k: int, terms: int = 12) -> np.ndarray:
    """E[floor(X / k)] for X ~ Poisson(mu)."""
    mu = np.asarray(mu, dtype=float)
    out = np.zeros_like(mu)
    for j in range(1, terms + 1):
        out += poisson.sf(j * k - 1, mu)
    return out


def p_defcon(mu: np.ndarray, size: np.ndarray, threshold: np.ndarray) -> np.ndarray:
    mu = np.maximum(np.asarray(mu, dtype=float), 1e-9)
    size = np.asarray(size, dtype=float)
    p = size / (size + mu)
    return nbinom.sf(np.asarray(threshold) - 1, size, p)


def normalise_shares(df: pd.DataFrame, params: RateParams) -> pd.DataFrame:
    """Scale goal/assist shares so a team's expected allocation sums to its expected output."""
    df = df.copy()
    df["_g"] = df["s_g"] * df["xmins"] / 90
    df["_a"] = df["s_a"] * df["xmins"] / 90
    tot = df.groupby(["team", "fixture"])[["_g", "_a"]].transform("sum")
    df["f_g"] = np.clip(0.97 / tot["_g"].replace(0, np.nan), 0.75, 1.35).fillna(1.0)
    df["f_a"] = np.clip(0.97 * params.assist_per_goal / tot["_a"].replace(0, np.nan), 0.75, 1.35).fillna(1.0)
    return df.drop(columns=["_g", "_a"])


def fixture_xpts(df: pd.DataFrame, params: RateParams, rules: Rules) -> pd.DataFrame:
    """Expected points per (element, fixture) row.

    ``df`` combines minutes states (p_s60, p_slt, p_sub_app + minutes), team λs and rates.
    """
    df = normalise_shares(df, params)
    pos = df["position"].to_numpy()
    goal_pts = np.array([rules.goal_pts[p] for p in pos], dtype=float)
    cs_pts = np.array([rules.cs_pts[p] for p in pos], dtype=float)
    gc_pts = np.array([rules.gc_pts[p] for p in pos], dtype=float)
    dcp = np.array([rules.defcon_pts[p] for p in pos], dtype=float)
    thr = np.array([DEFCON_THRESHOLD[p] or 10_000 for p in pos], dtype=float)
    nb_size = np.array([params.nb_size[p] for p in pos], dtype=float)
    coef = np.vstack([params.bonus_coef[p] for p in pos])
    is_gk = pos == "GKP"
    lam_f, lam_a = df["lam_for"].to_numpy(float), df["lam_against"].to_numpy(float)
    # Defenders facing stronger attacks make more defensive actions.
    opp_adj = (lam_a / params.avg_team_xg) ** np.where(pos == "DEF", 0.2, 0.1)

    probs = {
        "s60": df["p_s60"].to_numpy(float),
        "slt": df["p_slt"].to_numpy(float),
        "sub": df["p_sub_app"].to_numpy(float),
    }
    comp = {
        k: np.zeros(len(df))
        for k in (
            "app",
            "goals",
            "assists",
            "cs",
            "gc",
            "saves",
            "dc",
            "bonus",
            "cards",
            "e_goals",
            "e_assists",
            "p_cs",
            "p_dc",
        )
    }
    for state, mcol, app in STATES:
        p = probs[state]
        m = df[mcol].to_numpy(float) / 90.0
        mu_g = lam_f * df["s_g"].to_numpy(float) * df["f_g"].to_numpy(float) * m
        mu_a = lam_f * df["s_a"].to_numpy(float) * df["f_a"].to_numpy(float) * m
        pcs = np.exp(-lam_a * m) if state == "s60" else np.zeros(len(df))
        egc = lam_a * m
        gc_ded = expected_floor_div(egc, 2)
        saves = np.where(is_gk, expected_floor_div(df["save_k"].to_numpy(float) * lam_a * m, 3), 0.0)
        pdc = np.where(thr < 10_000, p_defcon(df["dc90"].to_numpy(float) * m * opp_adj, nb_size, thr), 0.0)
        X = np.column_stack(
            [
                np.full(len(df), 1.0 if state == "s60" else 0.0),
                np.full(len(df), 0.0 if state == "s60" else 1.0),
                mu_g,
                mu_a,
                pcs,
                pdc,
                saves,
                np.where(np.isin(pos, ["GKP", "DEF"]), egc, 0.0),
            ]
        )
        bonus = np.clip(np.sum(X * coef, axis=1), 0, None)
        cards = (
            df["yc90"].to_numpy(float) * m * rules.yellow_pts + df["rc90"].to_numpy(float) * m * rules.red_pts
        )
        comp["app"] += p * app
        comp["goals"] += p * goal_pts * mu_g
        comp["assists"] += p * rules.assist_pts * mu_a
        comp["cs"] += p * cs_pts * pcs
        comp["gc"] += p * gc_pts * gc_ded
        comp["saves"] += p * saves * rules.save_pts
        comp["dc"] += p * dcp * pdc
        comp["bonus"] += p * bonus
        comp["cards"] += p * cards
        comp["e_goals"] += p * mu_g
        comp["e_assists"] += p * mu_a
        comp["p_cs"] += p * pcs
        comp["p_dc"] += p * pdc
    for k, v in comp.items():
        df[
            f"x_{k}" if k in ("app", "goals", "assists", "cs", "gc", "saves", "dc", "bonus", "cards") else k
        ] = v
    df["xpts"] = df[PTS_COLS].sum(axis=1)
    return df


def points_curve(xpts: np.ndarray, knots: list[list[float]] | None) -> np.ndarray:
    """Piecewise-linear calibration through ``knots`` ([[predicted, calibrated], ...]).

    Identity without knots; beyond the last knot the curve keeps that knot's ratio.
    """
    x = np.asarray(xpts, dtype=float)
    if not knots:
        return x
    kx, ky = np.asarray(knots, dtype=float).T
    return np.where(x > kx[-1], x * ky[-1] / kx[-1], np.interp(x, kx, ky))


def calibrate_points(
    df: pd.DataFrame, knots: list[list[float]] | None, rows: pd.Series | np.ndarray | None = None
) -> pd.DataFrame:
    """Map fixture xPts through :func:`points_curve`, for ``rows`` only (default: all).

    The points components are scaled by the same factor, so they still add up to xPts. The
    factor is kept as ``pts_scale`` (the simulator applies it too) and the uncalibrated total
    as ``xpts_raw``.
    """
    df = df.copy()
    raw = df["xpts"].to_numpy(float)
    df["xpts_raw"] = raw
    scale = np.ones_like(raw)
    sel = raw > 1e-9
    if rows is not None:
        sel &= np.asarray(rows, dtype=bool)
    if knots and sel.any():
        scale[sel] = np.clip(points_curve(raw[sel], knots) / raw[sel], 0.0, 2.0)
    df["pts_scale"] = scale
    for c in [*PTS_COLS, "xpts"]:
        df[c] = df[c] * scale
    return df


def gameweek_xpts(
    fx: pd.DataFrame, elements: pd.Series, gws: list[int], teams_short: dict[str, str]
) -> pd.DataFrame:
    """Sum fixture rows into one row per (element, gw); blank gameweeks get zeros."""
    fx = fx.copy()
    fx["opp_label"] = fx["opp"].map(teams_short).fillna(fx["opp"]) + np.where(fx["is_home"], "(H)", "(A)")
    agg_cols = [
        "xpts",
        "xpts_raw",
        "xmins",
        "p_start",
        "p_play",
        "p_s60",
        "x_app",
        "x_goals",
        "x_assists",
        "x_cs",
        "x_gc",
        "x_saves",
        "x_dc",
        "x_bonus",
        "x_cards",
        "e_goals",
        "e_assists",
        "p_cs",
        "p_dc",
    ]
    g = (
        fx.groupby(["element", "gw"])
        .agg(
            **{c: (c, "sum") for c in agg_cols},
            n_fix=("fixture", "size"),
            fixtures=("opp_label", lambda s: " + ".join(s)),
            lam_for=("lam_for", "sum"),
            lam_against=("lam_against", "sum"),
        )
        .reset_index()
    )
    grid = pd.MultiIndex.from_product([elements, gws], names=["element", "gw"]).to_frame(index=False)
    out = grid.merge(g, on=["element", "gw"], how="left")
    out["n_fix"] = out["n_fix"].fillna(0).astype(int)
    out["fixtures"] = out["fixtures"].fillna("—")
    return out.fillna(0.0)
