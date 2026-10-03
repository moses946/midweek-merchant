"""Calibrate next-gameweek xPts on point-in-time backtests (`mm diagnose points`).

Forecasts for the coming gameweek come out compressed: the players ranked highest score more
than predicted and fringe players less. The slope of actual on predicted points was 1.12 in
2025/26 and 1.25 over the first 2026/27 gameweeks. Shrinking player rates toward position
means, and team ratings toward average, keeps the forecast stable at the cost of making the
best players look closer to the pack. Further ahead the effect fades: unforeseen absences
spread projections the other way, so the curve applies to the next gameweek only.

The curve is fitted on one season's next-gameweek forecasts (no odds, as the live forecast
usually runs). Each knot is shrunk toward "no change" by its sample size. The curve is then
checked on another season.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from midweek_merchant.backtest.minutes_calibration import _pava
from midweek_merchant.backtest.run import horizon_backtest, load_tables, top_calibration
from midweek_merchant.config import Settings
from midweek_merchant.data.store import write_output
from midweek_merchant.models.xpts import points_curve

EDGES = (0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 7.0, 30.0)


def fit_points_curve(
    pred: pd.Series, actual: pd.Series, min_n: int = 200, shrink_n: int = 400
) -> list[list[float]]:
    """Monotone knots [[predicted, calibrated], ...], anchored at 0.

    Fixed bins (sparse ones merge into the next); each bin's mean outcome is pulled toward its
    mean prediction with weight n / (n + shrink_n), so thin bins barely move.
    """
    d = pd.DataFrame({"p": pred.to_numpy(float), "y": actual.to_numpy(float)}).dropna()
    d = d[d["p"] > 0]
    d["bin"] = pd.cut(d["p"], EDGES, include_lowest=True)
    g = d.groupby("bin", observed=True).agg(p=("p", "sum"), y=("y", "sum"), n=("y", "size"))
    merged, acc = [], np.zeros(3)
    for row in g[["p", "y", "n"]].to_numpy(float):
        acc += row
        if acc[2] >= min_n:
            merged.append(acc.copy())
            acc[:] = 0
    if acc[2] > 0 and merged:
        merged[-1] += acc
    m = np.array(merged)
    ps, ys, ns = m[:, 0] / m[:, 2], m[:, 1] / m[:, 2], m[:, 2]
    ys = _pava(ps + ns / (ns + shrink_n) * (ys - ps), ns)
    return [[0.0, 0.0]] + [[round(float(p), 4), round(float(y), 4)] for p, y in zip(ps, ys, strict=True)]


def summary(df: pd.DataFrame, col: str) -> dict[str, Any]:
    d = df.assign(xpts=df[col])
    err = d["xpts"] - d["points"]
    played = d[d["xpts"] > 1.0]
    return {
        "rmse": float(np.sqrt((err**2).mean())),
        "bias": float(err.mean()),
        "slope": float(np.polyfit(played["xpts"], played["points"], 1)[0]),
        "by_rank": top_calibration(d, key=("origin", "gw")).round(4).to_dict("records"),
    }


def calibrate(
    settings: Settings,
    fit_season: str,
    fit_origins: list[int],
    check_season: str,
    check_origins: list[int],
) -> dict[str, Any]:
    raw = settings.model_copy(
        update={"forecast": settings.forecast.model_copy(update={"next_gw_points_calibration": []})}
    )
    t = load_tables(raw)
    fit = horizon_backtest(raw, fit_season, fit_origins, horizon=1, t=t)
    knots = fit_points_curve(fit["xpts"], fit["points"])
    checks = {}
    for use_market in (False, True):
        chk = horizon_backtest(raw, check_season, check_origins, horizon=1, use_market=use_market, t=t)
        chk["xpts_cal"] = points_curve(chk["xpts"].to_numpy(float), knots)
        checks["with_odds" if use_market else "no_odds"] = {
            "rows": len(chk),
            "before": summary(chk, "xpts"),
            "after": summary(chk, "xpts_cal"),
        }
    out = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "fit": {"season": fit_season, "origins": fit_origins, "rows": len(fit)},
        "check": {"season": check_season, "origins": check_origins, **checks},
        "curve": knots,
    }
    write_output(settings, "points_calibration.json", out)
    return out
