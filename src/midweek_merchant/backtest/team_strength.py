"""Tune the team-strength model against goals and the betting market (`mm diagnose team-strength`).

The live forecast usually has no odds for the fixtures it projects: football-data lists only the
next round a few days ahead and the-odds-api is optional. So the ratings must be good on their
own. This harness fits them point-in-time at regular gameweeks of past seasons, projects the next
six gameweeks (the planner's horizon), and scores each fixture's λ:

* Poisson deviance against the goals scored (the objective), and
* squared log error against the λ implied by that fixture's opening odds (a low-noise check),

along with the spread (sd) of λ next to the market's. A grid over decay, ridge and the weight
on past matches' market λ picks the settings; the spread factor then scales team differences if
the ratings remain flatter than the market.
"""

from __future__ import annotations

import itertools
import logging
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from midweek_merchant.backtest.run import Tables, load_tables
from midweek_merchant.config import Settings
from midweek_merchant.data.store import write_output
from midweek_merchant.models.team_strength import fit_ratings

log = logging.getLogger(__name__)

COLS = ["date", "league", "home", "away", "hg", "ag", "hxg", "axg", "hmk", "amk"]
DEFAULT_GRID = {
    "team_decay_per_day": [0.003, 0.01, 0.02, 0.03],
    "ridge": [2.0, 4.0],
    "market_target_weight": [0.0, 0.6, 0.8],
}
SPREADS = (1.0, 1.05, 1.1, 1.15, 1.2)
BASELINE = {"team_decay_per_day": 0.003, "ridge": 4.0, "market_target_weight": 0.0, "team_spread": 1.0}


def _deviance(goals: np.ndarray, lam: np.ndarray) -> float:
    with np.errstate(divide="ignore", invalid="ignore"):
        term = np.where(goals > 0, goals * np.log(goals / lam), 0.0)
    return float(2 * np.mean(term - (goals - lam)))


def fixture_predictions(
    t: Tables,
    season: str,
    origins: list[int],
    params: dict[str, float],
    spreads: tuple[float, ...] = (1.0,),
    horizon: int = 6,
    xg_weight: float = 0.6,
) -> pd.DataFrame:
    """Point-in-time λ for every fixture of GW o..o+horizon-1 at each origin GW o."""
    fx = t.tm[(t.tm["season"] == season) & (t.tm["league"] == "E0")]
    rows = []
    for gw in origins:
        first = fx[fx["gw"] == gw]
        if first.empty:
            continue
        cutoff = first["kickoff_time"].min().tz_convert("Europe/London").date().isoformat()
        hist = pd.concat(
            [
                t.tm.loc[t.tm["finished"].fillna(False).astype(bool) & (t.tm["date"] < cutoff), COLS],
                t.e1.loc[t.e1["finished"].astype(bool) & (t.e1["date"] < cutoff), COLS],
            ],
            ignore_index=True,
        )
        ratings = fit_ratings(
            hist,
            pd.Timestamp(cutoff),
            xi=params["team_decay_per_day"],
            xg_weight=xg_weight,
            ridge=params["ridge"],
            market_weight=params["market_target_weight"],
        )
        targets = fx[(fx["gw"] >= gw) & (fx["gw"] < gw + horizon)]
        for k in spreads:
            ratings.spread = k
            for r in targets.itertuples():
                lh, la = ratings.lambdas(r.home, r.away)
                ahead = int(r.gw) - gw
                rows.append((k, gw, ahead, lh, r.hmk, r.hg))
                rows.append((k, gw, ahead, la, r.amk, r.ag))
    return pd.DataFrame(rows, columns=["spread", "origin", "ahead", "model", "market", "goals"])


def score(d: pd.DataFrame) -> dict[str, float]:
    d = d.dropna(subset=["goals"])
    m = d.dropna(subset=["market"])
    lm, lk = np.log(m["model"]), np.log(m["market"])
    return {
        "deviance": _deviance(d["goals"].to_numpy(float), d["model"].to_numpy(float)),
        "deviance_market": _deviance(m["goals"].to_numpy(float), m["market"].to_numpy(float)),
        "msle_vs_market": float(((lm - lk) ** 2).mean()),
        "slope_vs_market": float(np.polyfit(lm - lm.mean(), lk - lk.mean(), 1)[0]),
        "sd": float(d["model"].std()),
        "sd_market": float(m["market"].std()),
        "n": len(d),
    }


def tune(
    settings: Settings,
    seasons: tuple[str, ...] = ("2024-25", "2025-26"),
    every: int = 3,
    grid: dict[str, list[float]] | None = None,
    spreads: tuple[float, ...] = SPREADS,
) -> dict[str, Any]:
    """Grid-search the settings on pooled seasons; deviance against goals picks the winner."""
    t = load_tables(settings)
    grid = grid or DEFAULT_GRID
    cfg = settings.forecast
    current = {
        "team_decay_per_day": cfg.team_decay_per_day,
        "ridge": cfg.ridge,
        "market_target_weight": cfg.market_target_weight,
        "team_spread": cfg.team_spread,
    }
    combos = [dict(zip(grid, v, strict=True)) for v in itertools.product(*grid.values())]
    rows = []
    for params in combos:
        preds = pd.concat(
            [
                fixture_predictions(t, s, list(range(5, 36, every)), params, spreads, xg_weight=cfg.xg_weight)
                for s in seasons
            ],
            ignore_index=True,
        )
        for k, d in preds.groupby("spread"):
            rows.append({**params, "team_spread": float(k), **score(d)})
        log.info("team strength %s done", params)
    table = pd.DataFrame(rows).sort_values("deviance").reset_index(drop=True)
    best = table.iloc[0]

    def scores_of(params: dict[str, float]) -> dict[str, float] | None:
        hit = table[np.logical_and.reduce([np.isclose(table[k], v) for k, v in params.items()])]
        keys = ("deviance", "msle_vs_market", "sd", "sd_market")
        return {k: float(hit.iloc[0][k]) for k in keys} if len(hit) else None

    out = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "seasons": list(seasons),
        "best": {k: float(best[k]) for k in current},
        "best_scores": {k: float(best[k]) for k in ("deviance", "msle_vs_market", "sd", "sd_market")},
        "current": current,
        "current_scores": scores_of(current),
        # the settings used before this tuning existed: slow decay, goals and xG only
        "baseline": BASELINE,
        "baseline_scores": scores_of(BASELINE),
        "deviance_market": float(best["deviance_market"]),
        "table": table.round(5).to_dict("records"),
    }
    write_output(settings, "team_strength_tuning.json", out)
    return out
