"""Tail calibration of the Monte Carlo simulator on blind hindcast picks.

A planner that targets P(100+ week) is only as good as the upper tail of the simulated
score distribution. For each hindcast gameweek, this re-simulates the blind XI with that
week's point-in-time inputs and compares the predicted distribution with the real score:
mean, spread, P(>= 80/100) and the PIT value (the predicted probability of scoring below
what actually happened; uniform when calibrated).

It also fits one spread factor ``k`` over all seasons by minimising the CRPS (a proper
scoring rule) of the rescaled distribution ``mean + k * (score - mean)``. The ceiling
planner applies ``k`` to its tail probabilities.
"""

from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

from midweek_merchant.backtest import run as bt
from midweek_merchant.config import Settings
from midweek_merchant.data.store import write_output
from midweek_merchant.forecast import forecast_core, load_rules
from midweek_merchant.models.simulate import rescale, simulate
from midweek_merchant.strategy.league import Lineup, score_lineup

log = logging.getLogger(__name__)

THRESHOLDS = (80, 100)
SCALES = [round(float(k), 2) for k in np.arange(0.6, 1.41, 0.05)]
PIT_BINS = [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0]


def crps_scaled(samples: np.ndarray, y: float, scales: list[float]) -> list[float]:
    """Ensemble CRPS of ``rescale(samples, k)`` for each k (E|X-y| - E|X-X'|/2)."""
    x = np.sort(samples.astype(float))
    n = len(x)
    mu = x.mean()
    spread = 2 * np.sum((2 * np.arange(1, n + 1) - n - 1) * x) / n**2  # E|X - X'|
    return [float(np.abs(mu + k * (x - mu) - y).mean() - 0.5 * k * spread) for k in scales]


def _pit(dist: np.ndarray, y: float) -> float:
    return float((dist < y).mean() + 0.5 * (dist == y).mean())


def tail_calibration(
    settings: Settings, season: str, every: int = 1, n_sims: int = 4000, picks: tuple[str, ...] = ("model",)
) -> dict:
    rules = load_rules(settings)
    t = bt.load_tables(settings)
    hc = json.loads((settings.outputs_dir / f"hindcast_{season}.json").read_text())
    rows = []
    for r in hc["gameweeks"][::every]:
        gw = r["gw"]
        inp = bt.point_in_time_inputs(settings, t, season, gw)
        teams = set(inp.upcoming["home"]) | set(inp.upcoming["away"])
        fc = forecast_core(
            settings,
            inp.players,
            inp.upcoming,
            t.pm,
            t.tm,
            inp.team_hist,
            inp.market,
            season,
            gw,
            [gw],
            inp.deadline,
            {x: x for x in teams},
            rules,
            {},
        )
        for key in picks:
            if key not in r["picks"]:
                continue
            w = r["picks"][key]
            els = {p["element"] for p in w["lineup"] + w["bench"]}
            sim = simulate(fc.fixture_rows, fc.params, rules, n_sims=n_sims, elements=els, seed=gw)
            lu = Lineup(
                [p["element"] for p in w["lineup"]],
                [p["element"] for p in w["bench"]],
                w["captain"]["element"],
                w["vice"]["element"],
            )
            dist = score_lineup(sim, gw, lu)
            a = float(r["scores"][key])
            rows.append(
                {
                    "season": season,
                    "gw": gw,
                    "pick": key,
                    "actual": a,
                    "sim_mean": float(dist.mean()),
                    "sim_sd": float(dist.std()),
                    "pit": _pit(dist, a),
                    **{f"p{k}": float((dist >= k).mean()) for k in THRESHOLDS},
                    "crps": crps_scaled(dist, a, SCALES),
                    "pit_by_scale": [_pit(rescale(dist, k), a) for k in SCALES],
                    **{
                        f"p{th}_by_scale": [float((rescale(dist, k) >= th).mean()) for k in SCALES]
                        for th in THRESHOLDS
                    },
                }
            )
    out = {"season": season, "scales": SCALES, "summary": summarise(pd.DataFrame(rows)), "weeks": rows}
    write_output(settings, f"tail_calibration_{season}.json", out)
    return out


def summarise(d: pd.DataFrame, k_index: int | None = None) -> list[dict]:
    """Per-pick calibration summary, raw or with the spread factor ``SCALES[k_index]`` applied."""
    k = 1.0 if k_index is None else SCALES[k_index]

    def scaled(col: str) -> pd.Series:
        return (
            d.loc[g.index, col]
            if k_index is None
            else d.loc[g.index, f"{col}_by_scale"].map(lambda v: v[k_index])
        )

    summary = []
    for key, g in d.groupby("pick"):
        pit = scaled("pit") if k_index is None or "pit_by_scale" in d else None
        row = {
            "pick": key,
            "gameweeks": len(g),
            "actual_mean": float(g["actual"].mean()),
            "sim_mean": float(g["sim_mean"].mean()),
            "sim_sd": float(k * g["sim_sd"].mean()),
            "realised_sd": float((g["actual"] - g["sim_mean"]).std()),
            "pit_hist": np.histogram(pit, bins=PIT_BINS)[0].tolist() if pit is not None else None,
        }
        for th in THRESHOLDS:
            row[f"n{th}_expected"] = float(scaled(f"p{th}").sum())
            row[f"n{th}_observed"] = int((g["actual"] >= th).sum())
        summary.append(row)
    return summary


def fit_scale(
    settings: Settings, seasons: tuple[str, ...] = ("2025-26", "2026-27"), pick: str = "model"
) -> dict:
    """Pool the saved per-season calibrations and fit the spread factor by mean CRPS."""
    weeks = []
    for season in seasons:
        path = settings.outputs_dir / f"tail_calibration_{season}.json"
        if path.exists():
            weeks += [w for w in json.loads(path.read_text())["weeks"] if w["pick"] == pick]
    if not weeks:
        return {"scale": 1.0, "gameweeks": 0}
    d = pd.DataFrame(weeks)
    crps = np.array(d["crps"].tolist()).mean(axis=0)
    i = int(np.argmin(crps))
    raw, fitted = summarise(d)[0], summarise(d, i)[0]
    out = {
        "scale": SCALES[i],
        "pick": pick,
        "seasons": list(seasons),
        "gameweeks": len(d),
        "crps_by_scale": dict(zip(SCALES, crps.round(3).tolist(), strict=True)),
        "raw": raw,
        "fitted": fitted,
    }
    write_output(settings, "tail_calibration.json", out)
    return out
