"""Rolling-origin backtest of the expected-points model on a past season.

For every target gameweek the model only sees data from before it: results and xG of
earlier matches, the market's *opening* odds for the target fixtures (closing odds embed
team news that was not known at the FPL deadline), and player prices at the time. Player
news/availability is not archived for past seasons, so the backtest assumes everyone is
available - live performance on zero-minute players will be better than measured here.

Baselines: FPL's own expected points (``xP`` in the vaastav data) and recent form
(mean points over the player's previous four appearances in the season).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from midweek_merchant.config import Settings
from midweek_merchant.data import odds
from midweek_merchant.data.store import read_table, write_output
from midweek_merchant.forecast import forecast_core, load_rules

log = logging.getLogger(__name__)


def _players_at(pm_season: pd.DataFrame, gw: int) -> pd.DataFrame:
    rows = pm_season[pm_season["gw"] == gw].drop_duplicates("element")
    return pd.DataFrame(
        {
            "element": rows["element"].astype(int),
            "code": rows["code"].astype(int),
            "name": rows["name"],
            "full_name": rows["name"],
            "position": rows["position"],
            "team": rows["team"],
            "team_short": rows["team"],
            "now_cost": rows["value"].fillna(50).astype(int),
            "status": "a",
            "news": "",
            "chance_next": np.nan,
            "scout_risk_gws": "[]",
            "can_select": True,
            "removed": False,
        }
    ).reset_index(drop=True)


def _market_for(tm_gw: pd.DataFrame) -> pd.DataFrame:
    out = []
    for r in tm_gw.itertuples():
        lh, la = odds.fd_row_lambdas(pd.Series(r._asdict()), closing=False)
        if np.isfinite(lh):
            out.append(
                {
                    "date": r.date,
                    "home": r.home,
                    "away": r.away,
                    "lh": lh,
                    "la": la,
                    "source": "football-data",
                }
            )
    return pd.DataFrame(out, columns=["date", "home", "away", "lh", "la", "source"])


def backtest_season(
    settings: Settings, season: str = "2025-26", gws: list[int] | None = None, use_market: bool = True
) -> pd.DataFrame:
    rules = load_rules(settings)
    pm = read_table(settings, "player_matches")
    tm = read_table(settings, "team_matches")
    e1 = read_table(settings, "fd_e1")
    pm_s = pm[pm["season"] == season]
    tm_s = tm[tm["season"] == season]
    gws = gws or list(range(4, 39))
    cols = ["date", "league", "home", "away", "hg", "ag", "hxg", "axg"]
    results = []
    for gw in gws:
        fx = tm_s[tm_s["gw"] == gw]
        if fx.empty:
            continue
        first_ko = fx["kickoff_time"].min()
        cutoff = first_ko.tz_convert("Europe/London").date().isoformat()
        hist = pd.concat(
            [
                tm.loc[tm["finished"].fillna(False).astype(bool) & (tm["date"] < cutoff), cols],
                e1.loc[e1["finished"].astype(bool) & (e1["date"] < cutoff), cols],
            ],
            ignore_index=True,
        )
        players = _players_at(pm_s, gw)
        upcoming = fx[["gw", "fixture", "kickoff_time", "home", "away"]].copy()
        market = _market_for(fx) if use_market else None
        now = (first_ko - pd.Timedelta(hours=2)).to_pydatetime()
        fc = forecast_core(
            settings,
            players,
            upcoming,
            pm,
            tm,
            hist,
            market,
            season,
            gw,
            [gw],
            now,
            {t: t for t in set(fx["home"]) | set(fx["away"])},
            rules,
            {},
        )
        pred = fc.projections[["element", "position", "xpts", "xmins", "p_start", "p_cs"]]
        actual = (
            pm_s[pm_s["gw"] == gw]
            .groupby("element")
            .agg(points=("points", "sum"), minutes=("minutes", "sum"), xP=("fpl_xp", "sum"))
        )
        res = pred.merge(actual, left_on="element", right_index=True, how="inner")
        res["gw"] = gw
        results.append(res)
        log.info("backtest %s GW%d: %d players", season, gw, len(res))
    df = pd.concat(results, ignore_index=True)
    df = df.merge(_form_baseline(pm_s), on=["element", "gw"], how="left")
    df["season"] = season
    return df


def _form_baseline(pm_s: pd.DataFrame) -> pd.DataFrame:
    g = (
        pm_s.groupby(["element", "gw"])
        .agg(points=("points", "sum"), minutes=("minutes", "sum"))
        .reset_index()
    )
    g = g.sort_values(["element", "gw"])
    played = g[g["minutes"] > 0]
    form = played.groupby("element")["points"].transform(
        lambda s: s.shift(1).rolling(4, min_periods=1).mean()
    )
    played = played.assign(form=form)
    out = g.merge(played[["element", "gw", "form"]], on=["element", "gw"], how="left")
    out["form"] = out.groupby("element")["form"].ffill().fillna(0.0)
    return out[["element", "gw", "form"]]


def metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Accuracy of the model and baselines on all player-gameweeks with any data."""
    rows = []
    preds = {"model": "xpts", "form (last 4)": "form"}
    if "xP" in df.columns and df["xP"].notna().any():
        preds["FPL xP"] = "xP"
    subsets = {
        "all players": df,
        "played (1+ min)": df[df["minutes"] > 0],
        "regular starters (xMins >= 60)": df[df["xmins"] >= 60],
    }
    for sub_name, d in subsets.items():
        for name, col in preds.items():
            x = pd.to_numeric(d[col], errors="coerce").fillna(0.0)
            y = d["points"].astype(float)
            err = x - y
            sp = np.nanmean(
                [
                    spearmanr(g[col].astype(float), g["points"]).statistic
                    for _, g in d.groupby(["gw", "position"])
                    if len(g) > 10 and g[col].nunique() > 1 and g["points"].nunique() > 1
                ]
            )
            rows.append(
                {
                    "subset": sub_name,
                    "predictor": name,
                    "n": len(d),
                    "rmse": float(np.sqrt((err**2).mean())),
                    "mae": float(err.abs().mean()),
                    "bias": float(err.mean()),
                    "spearman_within_pos": sp,
                }
            )
    return pd.DataFrame(rows)


def calibration(df: pd.DataFrame, bins: int = 10) -> pd.DataFrame:
    d = df[df["xpts"] > 0.3].copy()
    d["bin"] = pd.qcut(d["xpts"], bins, duplicates="drop")
    return (
        d.groupby("bin", observed=True)
        .agg(predicted=("xpts", "mean"), actual=("points", "mean"), n=("points", "size"))
        .reset_index(drop=True)
    )


def top_pick_precision(df: pd.DataFrame, k: int = 10) -> pd.DataFrame:
    """Average actual points of each predictor's top-k picks per gameweek."""
    rows = []
    for name, col in (("model", "xpts"), ("form (last 4)", "form"), ("FPL xP", "xP")):
        if col not in df.columns:
            continue
        vals = [g.nlargest(k, col)["points"].mean() for _, g in df.groupby("gw")]
        rows.append({"predictor": name, f"mean points of top {k}": float(np.mean(vals))})
    best = [g.nlargest(k, "points")["points"].mean() for _, g in df.groupby("gw")]
    rows.append({"predictor": "hindsight best", f"mean points of top {k}": float(np.mean(best))})
    return pd.DataFrame(rows)


def run_and_save(settings: Settings, season: str = "2025-26", gws: list[int] | None = None) -> dict:
    df = backtest_season(settings, season, gws)
    met, cal, top = metrics(df), calibration(df), top_pick_precision(df)
    write_output(settings, "backtest_predictions.parquet", df)
    summary = {
        "season": season,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "gws": sorted(int(g) for g in df["gw"].unique()),
        "metrics": met.to_dict("records"),
        "calibration": cal.to_dict("records"),
        "top_picks": top.to_dict("records"),
    }
    write_output(settings, "backtest_summary.json", summary)
    return summary


def live_tracking(settings: Settings) -> pd.DataFrame:
    """Compare archived pre-deadline projections of this season with actual points."""
    hist = sorted((settings.outputs_dir / "history").glob("projections_gw*.parquet"))
    if not hist:
        return pd.DataFrame()
    pm = read_table(settings, "player_matches")
    cur = (
        pm[pm["season"] == settings.season]
        .groupby(["element", "gw"])
        .agg(points=("points", "sum"), minutes=("minutes", "sum"))
        .reset_index()
    )
    frames = []
    for f in hist:
        p = pd.read_parquet(f)
        m = p.merge(cur, on=["element", "gw"], how="inner")
        if len(m):
            frames.append(m)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
