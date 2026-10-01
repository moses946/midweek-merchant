"""Team attack/defence ratings.

A time-decayed, ridge-regularised Poisson model (the Dixon–Coles / Maher family):

    log λ_home = μ_L + h_L + att_home − def_away
    log λ_away = μ_L        + att_away − def_home

fitted to a blend of goals and xG (a quasi-Poisson likelihood accepts non-integer
targets). Championship (E1) matches share the team ratings, which rates promoted
clubs through the teams that move between divisions. Market-implied goal
expectancies for upcoming fixtures enter as weighted pseudo-observations so the
ratings are re-anchored to the betting market, then projected across the horizon.
The Dixon–Coles low-score correction ρ is fitted afterwards on integer scores.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import poisson


@dataclass
class TeamRatings:
    attack: dict[str, float]
    defence: dict[str, float]
    intercept: dict[str, float]
    home_adv: dict[str, float]
    rho: float

    def lambdas(self, home: str, away: str, league: str = "E0", neutral: bool = False) -> tuple[float, float]:
        mu = self.intercept.get(league, self.intercept["E0"])
        h = 0.0 if neutral else self.home_adv.get(league, self.home_adv["E0"])
        ah, dh = self.attack.get(home, 0.0), self.defence.get(home, 0.0)
        aa, da = self.attack.get(away, 0.0), self.defence.get(away, 0.0)
        return float(np.exp(mu + h + ah - da)), float(np.exp(mu + aa - dh))

    def table(self) -> pd.DataFrame:
        teams = sorted(self.attack)
        lh = [self.lambdas(t, t)[0] for t in teams]
        df = pd.DataFrame(
            {
                "team": teams,
                "attack": [self.attack[t] for t in teams],
                "defence": [self.defence[t] for t in teams],
            }
        )
        df["xg_for_vs_avg"] = np.exp(self.intercept["E0"] + df["attack"])
        df["xg_against_vs_avg"] = np.exp(self.intercept["E0"] - df["defence"])
        del lh
        return df.sort_values("attack", ascending=False).reset_index(drop=True)


def fit_ratings(
    matches: pd.DataFrame,
    ref_date: pd.Timestamp,
    xi: float = 0.0019,
    xg_weight: float = 0.6,
    ridge: float = 4.0,
    pseudo: pd.DataFrame | None = None,
    pseudo_weight: float = 3.0,
) -> TeamRatings:
    """Fit ratings.

    ``matches`` needs columns date, league, home, away, hg, ag, hxg, axg (xG may be NaN).
    ``pseudo`` (optional) has home, away, lh, la: market-implied expectancies.
    """
    m = matches.dropna(subset=["hg", "ag"]).copy()
    m["date"] = pd.to_datetime(m["date"])
    days = (pd.Timestamp(ref_date).tz_localize(None) - m["date"]).dt.days.clip(lower=0).to_numpy()
    w = np.exp(-xi * days)

    def target(g: pd.Series, xg: pd.Series) -> np.ndarray:
        g, xg = g.to_numpy(float), xg.to_numpy(float)
        return np.where(np.isfinite(xg), xg_weight * xg + (1 - xg_weight) * g, g)

    y_home, y_away = target(m["hg"], m["hxg"]), target(m["ag"], m["axg"])
    homes, aways, leagues = list(m["home"]), list(m["away"]), list(m["league"])
    weights = [w, w]
    ys = [y_home, y_away]
    if pseudo is not None and len(pseudo):
        homes += list(pseudo["home"])
        aways += list(pseudo["away"])
        leagues += ["E0"] * len(pseudo)
        pw = np.full(len(pseudo), pseudo_weight)
        weights = [np.concatenate([w, pw]), np.concatenate([w, pw])]
        ys = [
            np.concatenate([y_home, pseudo["lh"].to_numpy(float)]),
            np.concatenate([y_away, pseudo["la"].to_numpy(float)]),
        ]

    teams = sorted(set(homes) | set(aways))
    lgs = sorted(set(leagues) | {"E0"})
    ti = {t: i for i, t in enumerate(teams)}
    li = {lg: i for i, lg in enumerate(lgs)}
    nt, nl = len(teams), len(lgs)
    n = len(homes)
    # parameter layout: [att(nt), def(nt), mu(nl), home(nl)]
    rows = np.arange(n)
    h_idx = np.array([ti[t] for t in homes])
    a_idx = np.array([ti[t] for t in aways])
    l_idx = np.array([li[lg] for lg in leagues])
    ones = np.ones(n)

    def design(att_team: np.ndarray, def_team: np.ndarray, home: bool) -> sparse.csr_matrix:
        cols = [att_team, nt + def_team, 2 * nt + l_idx]
        vals = [ones, -ones, ones]
        if home:
            cols.append(2 * nt + nl + l_idx)
            vals.append(ones)
        return sparse.csr_matrix(
            (np.concatenate(vals), (np.tile(rows, len(cols)), np.concatenate(cols))),
            shape=(n, 2 * nt + 2 * nl),
        )

    X = sparse.vstack([design(h_idx, a_idx, True), design(a_idx, h_idx, False)]).tocsr()
    y = np.concatenate(ys)
    wt = np.concatenate(weights)
    pen = np.zeros(2 * nt + 2 * nl)
    pen[: 2 * nt] = ridge

    def f(theta: np.ndarray) -> tuple[float, np.ndarray]:
        eta = X @ theta
        mu = np.exp(eta)
        loss = np.sum(wt * (mu - y * eta)) + 0.5 * np.sum(pen * theta**2)
        grad = X.T @ (wt * (mu - y)) + pen * theta
        return float(loss), grad

    theta0 = np.zeros(2 * nt + 2 * nl)
    theta0[2 * nt : 2 * nt + nl] = np.log(1.3)
    res = minimize(f, theta0, jac=True, method="L-BFGS-B", options={"maxiter": 2000})
    th = res.x
    att = dict(zip(teams, th[:nt], strict=True))
    dfn = dict(zip(teams, th[nt : 2 * nt], strict=True))
    mu = dict(zip(lgs, th[2 * nt : 2 * nt + nl], strict=True))
    hadv = dict(zip(lgs, th[2 * nt + nl :], strict=True))
    ratings = TeamRatings(att, dfn, mu, hadv, rho=0.0)
    ratings.rho = fit_rho(ratings, m.assign(w=w))
    return ratings


def fit_rho(ratings: TeamRatings, m: pd.DataFrame) -> float:
    """Dixon–Coles low-score dependence parameter on integer E0 scores."""
    e0 = m[m["league"] == "E0"]
    if len(e0) < 50:
        return -0.05
    lam = np.array([ratings.lambdas(h, a) for h, a in zip(e0["home"], e0["away"], strict=True)])
    lh, la = lam[:, 0], lam[:, 1]
    hg, ag, w = e0["hg"].to_numpy(int), e0["ag"].to_numpy(int), e0["w"].to_numpy()

    def nll(rho: float) -> float:
        tau = np.ones_like(lh)
        tau = np.where((hg == 0) & (ag == 0), 1 - lh * la * rho, tau)
        tau = np.where((hg == 0) & (ag == 1), 1 + lh * rho, tau)
        tau = np.where((hg == 1) & (ag == 0), 1 + la * rho, tau)
        tau = np.where((hg == 1) & (ag == 1), 1 - rho, tau)
        return float(-np.sum(w * np.log(np.clip(tau, 1e-9, None))))

    return float(minimize_scalar(nll, bounds=(-0.2, 0.1), method="bounded").x)


def project_fixtures(
    ratings: TeamRatings,
    fixtures: pd.DataFrame,
    market: pd.DataFrame | None,
    next_gw: int,
    market_weight_next: float = 0.9,
    market_weight_decay: float = 0.6,
) -> pd.DataFrame:
    """λ for every upcoming fixture, blending market odds where available.

    ``fixtures`` needs gw, fixture, kickoff_time, home, away. Returns one row per fixture.
    """
    fx = fixtures.copy()
    lam = np.array([ratings.lambdas(h, a) for h, a in zip(fx["home"], fx["away"], strict=True)])
    fx["lh_model"], fx["la_model"] = lam[:, 0], lam[:, 1]
    fx["lh"], fx["la"] = fx["lh_model"], fx["la_model"]
    fx["market"] = False
    if market is not None and len(market):
        mk = market.drop_duplicates(["home", "away"]).set_index(["home", "away"])
        for i, r in fx.iterrows():
            key = (r["home"], r["away"])
            if key not in mk.index or pd.isna(r["gw"]):
                continue
            mrow = mk.loc[key]
            if abs((pd.Timestamp(mrow["date"]) - r["kickoff_time"].tz_localize(None).normalize()).days) > 4:
                continue
            wm = market_weight_next * market_weight_decay ** max(0, int(r["gw"]) - next_gw)
            fx.at[i, "lh"] = wm * mrow["lh"] + (1 - wm) * r["lh_model"]
            fx.at[i, "la"] = wm * mrow["la"] + (1 - wm) * r["la_model"]
            fx.at[i, "market"] = True
    fx["rho"] = ratings.rho
    return fx


def team_fixture_rows(proj: pd.DataFrame) -> pd.DataFrame:
    """Expand fixtures into one row per team per fixture with λ_for / λ_against."""
    home = proj.assign(
        team=proj["home"], opp=proj["away"], is_home=True, lam_for=proj["lh"], lam_against=proj["la"]
    )
    away = proj.assign(
        team=proj["away"], opp=proj["home"], is_home=False, lam_for=proj["la"], lam_against=proj["lh"]
    )
    cols = [
        "gw",
        "fixture",
        "kickoff_time",
        "team",
        "opp",
        "is_home",
        "lam_for",
        "lam_against",
        "market",
        "rho",
    ]
    out = pd.concat([home[cols], away[cols]], ignore_index=True)
    out["p_cs"] = np.exp(-out["lam_against"])
    out["p_score2"] = 1 - poisson.cdf(1, out["lam_for"])
    return out.sort_values(["gw", "kickoff_time", "fixture", "is_home"], ascending=[True, True, True, False])
