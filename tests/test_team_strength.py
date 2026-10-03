"""Team ratings: the market target, the spread factor and the cached odds-to-λ conversion."""

from pathlib import Path

import numpy as np
import pandas as pd

from midweek_merchant.data.odds import attach_market_lambdas
from midweek_merchant.models.team_strength import fit_ratings

TEAMS = ["A", "B", "C", "D", "E", "F"]
TRUE_ATT = dict(zip(TEAMS, [0.5, 0.3, 0.1, -0.1, -0.3, -0.5], strict=True))
TRUE_DEF = dict(zip(TEAMS, [0.4, 0.2, 0.0, 0.0, -0.2, -0.4], strict=True))


def _true(h: str, a: str) -> tuple[float, float]:
    mu, home = np.log(1.35), 0.15
    return float(np.exp(mu + home + TRUE_ATT[h] - TRUE_DEF[a])), float(np.exp(mu + TRUE_ATT[a] - TRUE_DEF[h]))


def _matches(rounds: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    day = pd.Timestamp("2025-08-01")
    for r in range(rounds):
        for h in TEAMS:
            for a in TEAMS:
                if h == a:
                    continue
                lh, la = _true(h, a)
                rows.append(
                    {
                        "date": day + pd.Timedelta(days=r),
                        "league": "E0",
                        "home": h,
                        "away": a,
                        "hg": rng.poisson(lh),
                        "ag": rng.poisson(la),
                        "hxg": np.nan,
                        "axg": np.nan,
                        "hmk": lh,  # a perfectly informed market
                        "amk": la,
                    }
                )
    return pd.DataFrame(rows)


def _error(ratings) -> float:  # noqa: ANN001
    err = []
    for h in TEAMS:
        for a in TEAMS:
            if h != a:
                err += list(np.log(ratings.lambdas(h, a)) - np.log(_true(h, a)))
    return float(np.sqrt(np.mean(np.square(err))))


def test_market_target_recovers_ratings_from_few_matches() -> None:
    m = _matches(rounds=1)  # 30 matches: goals alone are very noisy
    ref = pd.Timestamp("2025-08-10")
    goals_only = fit_ratings(m, ref, xi=0.0, ridge=1.0, market_weight=0.0)
    with_market = fit_ratings(m, ref, xi=0.0, ridge=1.0, market_weight=1.0)
    assert _error(with_market) < 0.5 * _error(goals_only)
    # Without hmk/amk columns the market weight is ignored rather than failing.
    plain = fit_ratings(m.drop(columns=["hmk", "amk"]), ref, xi=0.0, ridge=1.0, market_weight=1.0)
    assert np.isclose(_error(plain), _error(goals_only))


def test_spread_scales_team_differences_only() -> None:
    ratings = fit_ratings(
        _matches(rounds=2), pd.Timestamp("2025-08-10"), xi=0.0, ridge=1.0, market_weight=1.0
    )
    base = {(h, a): np.log(ratings.lambdas(h, a)) for h in TEAMS for a in TEAMS if h != a}
    ratings.spread = 1.2
    wide = {k: np.log(ratings.lambdas(*k)) for k in base}
    mu = ratings.intercept["E0"]
    for (h, a), (bh, ba) in base.items():
        wh, wa = wide[(h, a)]
        assert np.isclose(wa - mu, 1.2 * (ba - mu))  # away side: no home advantage
        assert np.isclose(wh - mu - ratings.home_adv["E0"], 1.2 * (bh - mu - ratings.home_adv["E0"]))


def test_attach_market_lambdas_caches(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {
            "oh": [1.5, np.nan],
            "od": [4.2, np.nan],
            "oa": [6.5, np.nan],
            "o_over": [1.7, np.nan],
            "o_under": [2.2, np.nan],
        }
    )
    cache = tmp_path / "mk.parquet"
    out = attach_market_lambdas(df, cache)
    assert out.loc[0, "hmk"] > out.loc[0, "amk"] > 0  # the favourite is expected to score more
    assert np.isnan(out.loc[1, "hmk"])  # no odds, no λ
    assert cache.exists() and len(pd.read_parquet(cache)) == 1
    again = attach_market_lambdas(df, cache)
    assert np.allclose(
        again.loc[0, ["hmk", "amk"]].to_numpy(float), out.loc[0, ["hmk", "amk"]].to_numpy(float)
    )
