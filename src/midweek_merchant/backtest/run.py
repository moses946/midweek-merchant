"""Rolling-origin backtest of the expected-points model on a past season.

For every target gameweek the model only sees what was known before its deadline:
results and xG of earlier matches, the market's *opening* odds for the target fixtures
(closing odds embed team news that was not known at the FPL deadline), and - from the
FPL-Elo-Insights snapshot taken after the previous gameweek - each player's injury news,
chance of playing and price. Seasons without snapshots fall back to "everyone available".

Baselines: FPL's own pre-deadline expected points (``ep_next`` from the same snapshot;
the archived vaastav ``xP`` is only a fallback because it appears to be recorded after
kick-off) and recent form (mean points over the previous four appearances).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from midweek_merchant.config import Settings
from midweek_merchant.data import odds
from midweek_merchant.data.store import read_table, write_output
from midweek_merchant.forecast import forecast_core, load_rules
from midweek_merchant.rules import Rules

log = logging.getLogger(__name__)


@dataclass
class PITInputs:
    """Everything known before the GW deadline (nothing from GW ``gw`` itself)."""

    season: str
    gw: int
    deadline: datetime
    players: pd.DataFrame
    upcoming: pd.DataFrame
    team_hist: pd.DataFrame
    market: pd.DataFrame | None
    fpl_ep: pd.Series  # FPL's own pre-deadline expected points (snapshot gw-1), indexed by element
    snapshot_used: bool


@dataclass
class Tables:
    pm: pd.DataFrame
    tm: pd.DataFrame
    e1: pd.DataFrame
    snaps: pd.DataFrame
    events: pd.DataFrame


def load_tables(settings: Settings) -> Tables:
    snaps_path = settings.processed_dir / "player_snapshots.parquet"
    return Tables(
        pm=read_table(settings, "player_matches"),
        tm=read_table(settings, "team_matches"),
        e1=read_table(settings, "fd_e1"),
        snaps=pd.read_parquet(snaps_path) if snaps_path.exists() else pd.DataFrame(),
        events=read_table(settings, "events"),
    )


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


def point_in_time_inputs(
    settings: Settings, t: Tables, season: str, gw: int, use_market: bool = True
) -> PITInputs | None:
    """Inputs as they stood at the GW ``gw`` deadline.

    Player news, chance of playing, price and FPL's ep come from the FPL-Elo-Insights
    snapshot taken after GW ``gw - 1`` (i.e. before this deadline). Without a snapshot the
    player state falls back to "everyone available" and the archived per-GW price.
    """
    pm_s = t.pm[t.pm["season"] == season]
    fx = t.tm[(t.tm["season"] == season) & (t.tm["gw"] == gw)]
    if fx.empty or pm_s[pm_s["gw"] == gw].empty:
        return None
    first_ko = fx["kickoff_time"].min()
    deadline = first_ko - pd.Timedelta(minutes=90)
    if season == settings.season and len(t.events):
        ev = t.events[t.events["gw"] == gw]
        if len(ev):
            deadline = pd.Timestamp(ev["deadline_time"].iloc[0])
    cutoff = first_ko.tz_convert("Europe/London").date().isoformat()
    cols = ["date", "league", "home", "away", "hg", "ag", "hxg", "axg"]
    team_hist = pd.concat(
        [
            t.tm.loc[t.tm["finished"].fillna(False).astype(bool) & (t.tm["date"] < cutoff), cols],
            t.e1.loc[t.e1["finished"].astype(bool) & (t.e1["date"] < cutoff), cols],
        ],
        ignore_index=True,
    )
    players = _players_at(pm_s, gw)
    snap = (
        t.snaps[(t.snaps["season"] == season) & (t.snaps["snapshot_gw"] == gw - 1)]
        if len(t.snaps)
        else pd.DataFrame()
    )
    fpl_ep = pd.Series(dtype=float)
    used = len(snap) > 0
    if used:
        sn = snap.set_index("element")
        players = players[players["element"].isin(sn.index)].reset_index(drop=True)  # registered pre-deadline
        idx = players["element"]
        players["name"] = idx.map(sn["web_name"]).fillna(players["name"]).to_numpy()  # short display names
        players["status"] = idx.map(sn["status"]).fillna("a").to_numpy()
        players["chance_next"] = idx.map(sn["chance_next"]).to_numpy()
        players["news"] = idx.map(sn["news"]).fillna("").to_numpy()
        players["now_cost"] = idx.map(sn["now_cost"]).fillna(players["now_cost"]).astype(int).to_numpy()
        fpl_ep = sn["ep_next"].astype(float)
    upcoming = fx[["gw", "fixture", "kickoff_time", "home", "away"]].copy()
    return PITInputs(
        season=season,
        gw=gw,
        deadline=deadline.to_pydatetime(),
        players=players,
        upcoming=upcoming,
        team_hist=team_hist,
        market=_market_for(fx) if use_market else None,
        fpl_ep=fpl_ep,
        snapshot_used=used,
    )


def point_in_time_forecast(settings: Settings, t: Tables, inp: PITInputs, rules: Rules) -> pd.DataFrame:
    """xPts for one past gameweek using only pre-deadline inputs."""
    teams = set(inp.upcoming["home"]) | set(inp.upcoming["away"])
    fc = forecast_core(
        settings,
        inp.players,
        inp.upcoming,
        t.pm,
        t.tm,
        inp.team_hist,
        inp.market,
        inp.season,
        inp.gw,
        [inp.gw],
        inp.deadline,
        {x: x for x in teams},
        rules,
        {},
    )
    return fc.projections


def backtest_season(
    settings: Settings, season: str = "2025-26", gws: list[int] | None = None, use_market: bool = True
) -> pd.DataFrame:
    rules = load_rules(settings)
    t = load_tables(settings)
    pm_s = t.pm[t.pm["season"] == season]
    gws = gws or list(range(4, 39))
    results = []
    for gw in gws:
        inp = point_in_time_inputs(settings, t, season, gw, use_market)
        if inp is None:
            continue
        proj = point_in_time_forecast(settings, t, inp, rules)
        pred = proj[["element", "position", "xpts", "xmins", "p_start", "p_cs"]].copy()
        pred["fpl_ep"] = pred["element"].map(inp.fpl_ep) if inp.snapshot_used else np.nan
        actual = (
            pm_s[pm_s["gw"] == gw]
            .groupby("element")
            .agg(points=("points", "sum"), minutes=("minutes", "sum"), xP=("fpl_xp", "sum"))
        )
        res = pred.merge(actual, left_on="element", right_index=True, how="inner")
        res["gw"] = gw
        res["snapshot"] = inp.snapshot_used
        results.append(res)
        log.info("backtest %s GW%d: %d players (snapshot=%s)", season, gw, len(res), inp.snapshot_used)
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
    if "fpl_ep" in df.columns and df["fpl_ep"].notna().any():
        preds["FPL ep (pre-deadline)"] = "fpl_ep"
    elif "xP" in df.columns and df["xP"].notna().any():
        preds["FPL xP (archived)"] = "xP"
    subsets = {
        "all players": df,
        "played (1+ min)": df[df["minutes"] > 0],
        "regular starters (xMins >= 60)": df[df["xmins"] >= 60],
    }
    for sub_name, d in subsets.items():
        for name, col in preds.items():
            x = pd.to_numeric(d[col], errors="coerce").fillna(0.0)  # missing prediction counts as 0
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
    for name, col in (("model", "xpts"), ("form (last 4)", "form"), ("FPL ep (pre-deadline)", "fpl_ep")):
        if col not in df.columns or df[col].isna().all():
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
