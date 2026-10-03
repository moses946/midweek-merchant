"""Calibrate the minutes model on point-in-time backtests (`mm diagnose minutes`).

The minutes model's recency-weighted start and 60-minute rates are too cautious for regular
starters: in 2025/26 players given a 0.83 chance of 60+ minutes got there 90% of the time. This
fits monotone curves from the raw probabilities to the realised rates on one season, using only
players without injury news (news is applied on top of the curves), and checks them on another.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from midweek_merchant.backtest.run import load_tables, point_in_time_fc, point_in_time_inputs
from midweek_merchant.config import Settings
from midweek_merchant.data.store import write_output
from midweek_merchant.forecast import load_rules
from midweek_merchant.models.minutes import apply_curve


def collect(settings: Settings, season: str, gws: list[int]) -> pd.DataFrame:
    """Raw start / 60-minute probabilities and what happened, one row per player-fixture."""
    t = load_tables(settings)
    rules = load_rules(settings)
    pm = t.pm[t.pm["season"] == season][["element", "fixture", "minutes", "starts"]]
    out = []
    for gw in gws:
        inp = point_in_time_inputs(settings, t, season, gw)
        if inp is None:
            continue
        fx = point_in_time_fc(settings, t, inp, rules).fixture_rows
        cols = ["element", "fixture", "gw", "avail", "p_start_raw", "q60_raw", "p_start", "p_s60"]
        out.append(fx[cols].merge(pm, on=["element", "fixture"], how="inner"))
    df = pd.concat(out, ignore_index=True)
    df["started"] = (df["starts"] > 0).astype(float)
    df["s60"] = (df["minutes"] >= 60).astype(float)
    return df


def _pava(y: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Pool-adjacent-violators: the non-decreasing fit to ``y`` with weights ``w``."""
    blocks = [[float(v), float(wt), 1] for v, wt in zip(y, w, strict=True)]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] > blocks[i + 1][0]:
            a, b = blocks[i], blocks[i + 1]
            wt = a[1] + b[1]
            blocks[i] = [(a[0] * a[1] + b[0] * b[1]) / wt, wt, a[2] + b[2]]
            del blocks[i + 1]
            i = max(i - 1, 0)
        else:
            i += 1
    return np.concatenate([np.full(n, v) for v, _, n in blocks])


EDGES = (0.0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.93, 0.96, 1.0)


def fit_curve(pred: pd.Series, actual: pd.Series, min_n: int = 150) -> list[list[float]]:
    """Monotone knots [[predicted, actual], ...], anchored at 0.

    Fixed bins, narrow at the top where regular starters sit (wide quantile bins would lump a
    0.90 and a 0.99 starter together); sparse bins merge into the next one.
    """
    d = pd.DataFrame({"p": pred.to_numpy(float), "y": actual.to_numpy(float)}).dropna()
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
    ps, ys = m[:, 0] / m[:, 2], _pava(m[:, 1] / m[:, 2], m[:, 2])
    return [[0.0, 0.0]] + [[round(float(p), 4), round(float(y), 4)] for p, y in zip(ps, ys, strict=True)]


def reliability(pred: np.ndarray, actual: np.ndarray) -> dict[str, Any]:
    d = pd.DataFrame({"p": pred, "y": actual})
    d["bin"] = pd.cut(d["p"], [0, 0.2, 0.4, 0.6, 0.7, 0.8, 0.85, 0.9, 1.0])
    table = d.groupby("bin", observed=True).agg(
        predicted=("p", "mean"), actual=("y", "mean"), n=("y", "size")
    )
    return {
        "brier": float(((d["p"] - d["y"]) ** 2).mean()),
        "table": [
            {"bin": str(i), **{k: round(float(v), 4) for k, v in r.items()}} for i, r in table.iterrows()
        ],
    }


def calibrate(
    settings: Settings, fit_season: str, fit_gws: list[int], check_season: str, check_gws: list[int]
) -> dict[str, Any]:
    fit = collect(settings, fit_season, fit_gws)
    clean = fit[fit["avail"] >= 0.999]
    curves = {
        "start": fit_curve(clean["p_start_raw"], clean["started"]),
        "q60": fit_curve(clean.loc[clean["started"] > 0, "q60_raw"], clean.loc[clean["started"] > 0, "s60"]),
    }
    chk = collect(settings, check_season, check_gws)
    raw_start = chk["p_start_raw"] * chk["avail"]
    new_start = apply_curve(chk["p_start_raw"].to_numpy(), curves["start"]) * chk["avail"]
    raw_s60 = raw_start * chk["q60_raw"]
    new_s60 = new_start * apply_curve(chk["q60_raw"].to_numpy(), curves["q60"])
    out = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "fit": {"season": fit_season, "rows": len(clean)},
        "check": {"season": check_season, "rows": len(chk)},
        "curves": curves,
        "start_before": reliability(raw_start.to_numpy(), chk["started"].to_numpy()),
        "start_after": reliability(np.asarray(new_start), chk["started"].to_numpy()),
        "s60_before": reliability(raw_s60.to_numpy(), chk["s60"].to_numpy()),
        "s60_after": reliability(np.asarray(new_s60), chk["s60"].to_numpy()),
    }
    write_output(settings, "minutes_calibration.json", out)
    return out
