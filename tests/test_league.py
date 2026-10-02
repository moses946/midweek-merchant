"""Simulation and league-layer checks on synthetic data."""

import numpy as np
import pandas as pd

from midweek_merchant.models.player_rates import BONUS_FEATURES, RateParams
from midweek_merchant.models.simulate import SimResult, simulate
from midweek_merchant.models.xpts import fixture_xpts
from midweek_merchant.rules import rules_from_bootstrap
from midweek_merchant.strategy.league import Lineup, Manager, best_xi, league_eo, score_lineup

RULES = rules_from_bootstrap(None)
PARAMS = RateParams(
    1.0,
    1.3,
    0.9,
    1.4,
    {"GKP": 5.0, "DEF": 25.0, "MID": 38.0, "FWD": 55.0},
    {p: np.array([0.0, 0.0, 1.2, 0.5, 0.6, 0.2, 0.3, 0.0]) for p in ("GKP", "DEF", "MID", "FWD")},
)
assert len(BONUS_FEATURES) == 8


def fixture_rows() -> pd.DataFrame:
    rows = []
    el = 1
    for team, is_home, lf, la in (("A", True, 1.8, 0.9), ("B", False, 0.9, 1.8)):
        for pos, n in (("GKP", 1), ("DEF", 4), ("MID", 4), ("FWD", 2)):
            for _ in range(n):
                rows.append(
                    {
                        "element": el,
                        "gw": 1,
                        "fixture": 1,
                        "team": team,
                        "opp": "B" if team == "A" else "A",
                        "is_home": is_home,
                        "lam_for": lf,
                        "lam_against": la,
                        "rho": -0.05,
                        "position": pos,
                        "p_s60": 0.85,
                        "p_slt": 0.05,
                        "p_sub_app": 0.05,
                        "m_start60": 88.0,
                        "m_start_lt": 55.0,
                        "m_sub": 20.0,
                        "xmins": 0.85 * 88 + 0.05 * 55 + 0.05 * 20,
                        "s_g": {"GKP": 0.0, "DEF": 0.03, "MID": 0.12, "FWD": 0.25}[pos],
                        "s_a": {"GKP": 0.01, "DEF": 0.05, "MID": 0.12, "FWD": 0.08}[pos],
                        "dc90": {"GKP": 0.0, "DEF": 9.0, "MID": 8.0, "FWD": 4.0}[pos],
                        "save_k": 2.2 if pos == "GKP" else 0.0,
                        "yc90": 0.12,
                        "rc90": 0.005,
                    }
                )
                el += 1
    return pd.DataFrame(rows)


def test_simulation_matches_analytic_means() -> None:
    fx = fixture_xpts(fixture_rows(), PARAMS, RULES)
    sim = simulate(fx, PARAMS, RULES, n_sims=6000, seed=3)
    m = sim.mean().merge(fx[["element", "xpts"]], on="element")
    assert np.corrcoef(m["sim_mean"], m["xpts"])[0, 1] > 0.97
    assert abs(m["sim_mean"].mean() - m["xpts"].mean()) < 0.15
    # clean sheets are shared: the two defences of a lopsided fixture differ
    d = m.merge(fx[["element", "team", "position"]], on="element")
    defs = d[d["position"] == "DEF"].groupby("team")["sim_mean"].mean()
    assert defs["A"] > defs["B"]


def _toy_sim() -> SimResult:
    pts = np.array([[10, 2, 0, 5], [4, 6, 0, 1], [0, 3, 8, 2]], dtype=np.float32)
    played = np.array([[1, 1, 0, 1], [1, 1, 0, 1], [0, 1, 1, 1]], dtype=bool)
    return SimResult([1], np.array([1, 2, 3, 4]), {1: pts}, {1: played})


def test_score_lineup_autosub_and_vice() -> None:
    sim = _toy_sim()
    lu = Lineup(starters=[1, 2], bench=[3, 4], captain=1, vice=2)
    s = score_lineup(sim, 1, lu)
    # sim0: 10+2, captain 1 doubles (+10); sim1: 4+6 +4; sim2: captain 1 did not play: bench 3 comes on (+8),
    # vice 2 doubles (+3)
    assert list(s) == [22, 14, 3 + 8 + 3]


def test_best_xi_and_eo() -> None:
    squad = (
        [(1, "GKP"), (2, "GKP")]
        + [(10 + i, "DEF") for i in range(5)]
        + [(20 + i, "MID") for i in range(5)]
        + [(30 + i, "FWD") for i in range(3)]
    )
    xp = {e: float(e % 7) for e, _ in squad}
    lu = best_xi(squad, xp, RULES)
    assert len(lu.starters) == 11 and len(lu.bench) == 4
    assert 2 in lu.starters and lu.bench[0] == 1  # higher-xPts keeper starts, the other is bench GK
    pos = dict(squad)
    counts = pd.Series([pos[e] for e in lu.starters]).value_counts()
    assert counts["GKP"] == 1 and counts["DEF"] >= 3 and counts["MID"] >= 2 and counts["FWD"] >= 1
    r = Manager(1, "r", "", 0, 1)
    r.lineups[1] = lu
    eo = league_eo([r], 1)
    assert eo[lu.captain] == 200 and all(eo[e] == 100 for e in lu.starters if e != lu.captain)


def _fpl_sim(points: dict[int, float], played: set[int], positions: dict[int, str]) -> SimResult:
    els = np.array(sorted(points))
    return SimResult(
        [1],
        els,
        {1: np.array([[points[e] for e in els]], dtype=np.float32)},
        {1: np.array([[e in played for e in els]])},
        positions,
    )


# XI: GK 1; DEF 2,3,4; MID 5,6,7,8; FWD 9,10,11. Bench: GK 12, then 13 (MID), 14 (DEF), 15 (FWD)
POS = {
    1: "GKP",
    2: "DEF",
    3: "DEF",
    4: "DEF",
    5: "MID",
    6: "MID",
    7: "MID",
    8: "MID",
    9: "FWD",
    10: "FWD",
    11: "FWD",
    12: "GKP",
    13: "MID",
    14: "DEF",
    15: "FWD",
}
XI, BENCH = list(range(1, 12)), [12, 13, 14, 15]


def test_autosub_bench_gk_never_replaces_outfielder() -> None:
    pts = {e: 2.0 for e in POS} | {12: 7.0, 13: 5.0, 9: 0.0}
    played = set(POS) - {9}  # a forward did not play
    s = score_lineup(_fpl_sim(pts, played, POS), 1, Lineup(XI, BENCH, captain=5, vice=6))
    # XI without 9 = 10 players x 2 = 20, captain +2, first eligible outfield bench (13, MID) +5; GK 12 ignored
    assert s[0] == 20 + 2 + 5


def test_autosub_respects_formation_minimum() -> None:
    pts = {e: 2.0 for e in POS} | {2: 0.0, 13: 9.0, 14: 4.0}
    played = set(POS) - {2}  # a defender did not play and only 3 DEF start
    s = score_lineup(_fpl_sim(pts, played, POS), 1, Lineup(XI, BENCH, captain=5, vice=6))
    # MID 13 cannot replace him (would leave 2 DEF); DEF 14 comes on instead
    assert s[0] == 20 + 2 + 4


def test_autosub_goalkeeper_swap() -> None:
    pts = {e: 2.0 for e in POS} | {1: 0.0, 12: 6.0}
    played = set(POS) - {1}
    s = score_lineup(_fpl_sim(pts, played, POS), 1, Lineup(XI, BENCH, captain=5, vice=6))
    assert s[0] == 20 + 2 + 6
