"""Per-player event rates, empirical-Bayes shrunk towards position/price priors.

* goal share  s_g: player's share of team xG while on the pitch (blend of xG and goals)
* assist share s_a: same for xA (calibrated to FPL's broader assist definition)
* DefCon rate: CBIT (DEF) / CBIRT (MID, FWD) count per 90, with a negative-binomial dispersion
* GK save factor: saves per unit of xG conceded on the pitch
* card rates per 90
* bonus: per-position linear model of bonus on match events (refit on 2026/27 data
  because the BPS changed this season)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

POS = ["GKP", "DEF", "MID", "FWD"]


@dataclass
class RateParams:
    goal_calib: float
    assist_calib: float
    assist_per_goal: float
    avg_team_xg: float
    nb_size: dict[str, float]
    bonus_coef: dict[str, np.ndarray] = field(default_factory=dict)


BONUS_FEATURES = ["i60", "ilt", "goals", "assists", "cs60", "dc_hit", "saves3", "gc"]


def _weights(
    panel: pd.DataFrame, half_life: float, current_season: str, prev_discount: float = 0.7
) -> np.ndarray:
    w = 0.5 ** (panel["age"].to_numpy(float) / half_life)
    return np.where(panel["season"].to_numpy() == current_season, w, w * prev_discount)


def _linear_prior(df: pd.DataFrame, value: str, weight: str) -> dict[str, tuple[float, float, float]]:
    """Weighted LS fit value ~ a + b*(cost-mean) per position -> {pos: (a, b, mean_cost)}."""
    out = {}
    for pos in POS:
        d = df[(df["position"] == pos) & (df[weight] > 0)]
        if len(d) < 10:
            out[pos] = (float(d[value].mean()) if len(d) else 0.05, 0.0, 50.0)
            continue
        x = d["now_cost"].to_numpy(float)
        xm = float(np.average(x, weights=d[weight]))
        A = np.vstack([np.ones(len(d)), x - xm]).T
        W = np.sqrt(d[weight].to_numpy(float))
        coef, *_ = np.linalg.lstsq(A * W[:, None], d[value].to_numpy(float) * W, rcond=None)
        out[pos] = (float(coef[0]), float(coef[1]), xm)
    return out


def _apply_prior(
    prior: dict[str, tuple[float, float, float]], pos: pd.Series, cost: pd.Series, lo: float, hi: float
) -> np.ndarray:
    vals = [prior[p][0] + prior[p][1] * (c - prior[p][2]) for p, c in zip(pos, cost, strict=True)]
    return np.clip(np.array(vals, dtype=float), lo, hi)


def fit_rates(
    panel: pd.DataFrame,
    players: pd.DataFrame,
    current_season: str,
    half_life: float = 12,
    prior_matches: float = 8,
) -> tuple[pd.DataFrame, RateParams]:
    played = panel[panel["minutes"] > 0].copy()
    played["w"] = _weights(played, half_life, current_season)
    played["m90"] = played["minutes"] / 90.0
    played["exposure"] = played["team_xg"].fillna(1.35) * played["m90"]

    goal_calib = float(played["goals"].sum() / max(played["xg"].sum(), 1e-6))
    assist_calib = float(played["assists"].sum() / max(played["xa"].sum(), 1e-6))
    assist_per_goal = float(played["assists"].sum() / max(played["goals"].sum(), 1e-6))
    avg_team_xg = float(played.drop_duplicates(["season", "fixture", "team"])["team_xg"].mean())

    played["g_target"] = 0.8 * goal_calib * played["xg"] + 0.2 * played["goals"]
    played["a_target"] = 0.75 * assist_calib * played["xa"] + 0.25 * played["assists"]
    played["dc_m90"] = np.where(played["dc"].notna(), played["m90"], 0.0)
    played["dc_val"] = played["dc"].fillna(0.0)
    for c in ("g_target", "a_target", "exposure", "m90", "dc_m90", "dc_val", "saves", "xgc", "yc", "rc"):
        played[f"w_{c}"] = played["w"] * played[c].fillna(0.0)
    keep = [
        "w_g_target",
        "w_a_target",
        "w_exposure",
        "w_m90",
        "w_dc_m90",
        "w_dc_val",
        "w_saves",
        "w_xgc",
        "w_yc",
        "w_rc",
    ]
    agg = played.groupby("code")[keep].sum()
    agg["minutes_obs"] = played.groupby("code")["minutes"].sum()

    df = players[["element", "code", "name", "position", "team", "now_cost"]].merge(
        agg, left_on="code", right_index=True, how="left"
    )
    df[keep + ["minutes_obs"]] = df[keep + ["minutes_obs"]].fillna(0.0)

    # Raw per-player rates for prior fitting (players with decent exposure)
    raw = df.copy()
    raw["s_g_raw"] = raw["w_g_target"] / raw["w_exposure"].replace(0, np.nan)
    raw["s_a_raw"] = raw["w_a_target"] / raw["w_exposure"].replace(0, np.nan)
    raw["dc_raw"] = raw["w_dc_val"] / raw["w_dc_m90"].replace(0, np.nan)
    raw["wt"] = raw["w_m90"].clip(upper=20)
    raw = raw[raw["w_m90"] > 3]
    pg = _linear_prior(raw.dropna(subset=["s_g_raw"]), "s_g_raw", "wt")
    pa = _linear_prior(raw.dropna(subset=["s_a_raw"]), "s_a_raw", "wt")
    pdc = _linear_prior(raw.dropna(subset=["dc_raw"]), "dc_raw", "wt")

    k_exp = prior_matches * avg_team_xg
    prior_g = _apply_prior(pg, df["position"], df["now_cost"], 0.003, 0.45)
    prior_a = _apply_prior(pa, df["position"], df["now_cost"], 0.003, 0.35)
    # DefCon volume is a stable, role-driven trait that price says little about: use a light
    # position-mean prior.
    prior_dc = df["position"].map({pos: pdc[pos][0] for pos in POS}).clip(0.5, 15.0).to_numpy(float)
    df["s_g"] = (k_exp * prior_g + df["w_g_target"]) / (k_exp + df["w_exposure"])
    df["s_a"] = (k_exp * prior_a + df["w_a_target"]) / (k_exp + df["w_exposure"])
    k_dc = 3.0
    df["dc90"] = (k_dc * prior_dc + df["w_dc_val"]) / (k_dc + df["w_dc_m90"])

    gk = played[played["position"] == "GKP"]
    save_prior = float(gk["saves"].sum() / max(gk["xgc"].sum(), 1e-6))
    k_s = prior_matches * avg_team_xg
    df["save_k"] = np.where(
        df["position"] == "GKP", (k_s * save_prior + df["w_saves"]) / (k_s + df["w_xgc"]), 0.0
    )
    yc_prior = played.groupby("position").apply(
        lambda d: d["yc"].sum() / d["m90"].sum(), include_groups=False
    )
    rc_prior = played.groupby("position").apply(
        lambda d: d["rc"].sum() / d["m90"].sum(), include_groups=False
    )
    k_c = 10.0
    df["yc90"] = (k_c * df["position"].map(yc_prior) + df["w_yc"]) / (k_c + df["w_m90"])
    df["rc90"] = df["position"].map(rc_prior)

    params = RateParams(goal_calib, assist_calib, assist_per_goal, avg_team_xg, _nb_sizes(played))
    params.bonus_coef = fit_bonus(panel, current_season)
    cols = ["element", "code", "s_g", "s_a", "dc90", "save_k", "yc90", "rc90", "minutes_obs"]
    return df[cols], params


def _nb_sizes(played: pd.DataFrame) -> dict[str, float]:
    """Negative-binomial size for DefCon counts per position (from full matches)."""
    out = {}
    full = played[(played["minutes"] >= 85) & played["dc"].notna()]
    for pos in POS:
        d = full[full["position"] == pos]
        if pos == "GKP" or len(d) < 50:
            out[pos] = 5.0
            continue
        mu_p = d.groupby("code")["dc"].transform("mean")
        n_p = d.groupby("code")["dc"].transform("size")
        d = d[n_p >= 4]
        resid_var = float(((d["dc"] - mu_p[n_p >= 4]) ** 2).mean())
        mean = float(d["dc"].mean())
        excess = resid_var - mean
        out[pos] = float(np.clip(mean**2 / excess, 2.0, 200.0)) if excess > 0 else 200.0
    return out


def bonus_design(df: pd.DataFrame) -> np.ndarray:
    return np.column_stack([df[c].to_numpy(float) for c in BONUS_FEATURES])


def fit_bonus(panel: pd.DataFrame, current_season: str, prev_weight: float = 0.3) -> dict[str, np.ndarray]:
    from midweek_merchant.rules import DEFCON_THRESHOLD

    d = panel[(panel["minutes"] > 0) & panel["bonus"].notna()].copy()
    d = d[d["season"].isin(sorted(d["season"].unique())[-2:])]
    d["i60"] = (d["minutes"] >= 60).astype(float)
    d["ilt"] = ((d["minutes"] > 0) & (d["minutes"] < 60)).astype(float)
    d["cs60"] = d["cs"].fillna(0) * d["i60"]
    thr = d["position"].map(lambda p: DEFCON_THRESHOLD[p] or 1e9)
    d["dc_hit"] = (d["dc"].fillna(0) >= thr).astype(float)
    d["saves3"] = np.floor(d["saves"].fillna(0) / 3)
    d["gc"] = d["gc"].fillna(0)
    w = np.where(d["season"] == current_season, 1.0, prev_weight)
    coefs = {}
    for pos in POS:
        m = (d["position"] == pos).to_numpy()
        X, y, ww = bonus_design(d[m]), d.loc[m, "bonus"].to_numpy(float), np.sqrt(w[m])
        if pos != "GKP":
            X[:, BONUS_FEATURES.index("saves3")] = 0
        if pos in ("MID", "FWD"):
            X[:, BONUS_FEATURES.index("gc")] = 0
        coef, *_ = np.linalg.lstsq(X * ww[:, None], y * ww, rcond=None)
        coefs[pos] = coef
    return coefs
