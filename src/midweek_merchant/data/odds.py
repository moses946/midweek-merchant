"""Betting odds: football-data.co.uk CSVs (free) and the-odds-api (key, quota-aware).

Odds are converted to margin-free probabilities and then to Poisson goal expectancies
(lambda_home, lambda_away), which anchor the team-strength model.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

from midweek_merchant.config import Settings
from midweek_merchant.data.store import download
from midweek_merchant.data.teams import team_from_odds_api

log = logging.getLogger(__name__)

FD_BASE = "https://www.football-data.co.uk"
ODDS_API = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds"


def season_code(season: str) -> str:
    """'2026-27' -> '2627'."""
    a, b = season.split("-")
    return a[-2:] + b[-2:]


# ------------------------------------------------------------------ football-data.co.uk
def load_fd(
    settings: Settings, season: str, league: str = "E0", max_age: float | None = 6 * 3600
) -> pd.DataFrame:
    dest = settings.raw_dir / "football_data" / f"{league}_{season_code(season)}.csv"
    is_current = season == settings.season
    download(
        f"{FD_BASE}/mmz4281/{season_code(season)}/{league}.csv",
        dest,
        max_age=max_age if is_current else 30 * 86400,
    )
    df = pd.read_csv(dest, encoding="utf-8-sig", on_bad_lines="skip")
    df = df.dropna(subset=["HomeTeam", "AwayTeam"])
    return _standardise_fd(df, season, league)


def load_fd_fixtures(settings: Settings, max_age: float = 3 * 3600) -> pd.DataFrame:
    dest = settings.raw_dir / "football_data" / "fixtures.csv"
    download(f"{FD_BASE}/fixtures.csv", dest, max_age=max_age)
    df = pd.read_csv(dest, encoding="utf-8-sig", on_bad_lines="skip")
    df = df[df["Div"] == "E0"]
    return _standardise_fd(df, settings.season, "E0") if len(df) else pd.DataFrame()


def _standardise_fd(df: pd.DataFrame, season: str, league: str) -> pd.DataFrame:
    date = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    out = pd.DataFrame(
        {
            "season": season,
            "league": league,
            "date": date.dt.date.astype(str),
            "home": df["HomeTeam"].str.strip(),
            "away": df["AwayTeam"].str.strip(),
            "hg": pd.to_numeric(df.get("FTHG"), errors="coerce"),
            "ag": pd.to_numeric(df.get("FTAG"), errors="coerce"),
            "hxg_fd": pd.to_numeric(df.get("HxG"), errors="coerce") if "HxG" in df else np.nan,
            "axg_fd": pd.to_numeric(df.get("AxG"), errors="coerce") if "AxG" in df else np.nan,
        }
    )
    # Opening (pre-closing) market averages; fall back to Bet365 then max.
    for prefix_sets, names in (
        (
            (("AvgH", "AvgD", "AvgA"), ("B365H", "B365D", "B365A"), ("MaxH", "MaxD", "MaxA")),
            ("oh", "od", "oa"),
        ),
        ((("AvgCH", "AvgCD", "AvgCA"), ("B365CH", "B365CD", "B365CA")), ("ch", "cd", "ca")),
        ((("Avg>2.5", "Avg<2.5"), ("B365>2.5", "B365<2.5")), ("o_over", "o_under")),
        ((("AvgC>2.5", "AvgC<2.5"), ("B365C>2.5", "B365C<2.5")), ("c_over", "c_under")),
    ):
        for cols in prefix_sets:
            if all(c in df.columns for c in cols):
                for c, n in zip(cols, names, strict=True):
                    out[n] = pd.to_numeric(df[c], errors="coerce").values
                break
        else:
            for n in names:
                out[n] = np.nan
    return out.reset_index(drop=True)


# ------------------------------------------------------------------ the-odds-api
def fetch_odds_api(settings: Settings, force: bool = False, deadline: datetime | None = None) -> pd.DataFrame:
    """Fetch current EPL odds, respecting the free-tier quota.

    Calls are skipped (cached copy returned) unless ``min_hours_between_calls`` elapsed
    or the next deadline is within 24h and the cache is older than 3h.
    """
    cache = settings.raw_dir / "odds_api" / "latest.json"
    if not settings.odds_api_key:
        return _parse_odds_api(cache) if cache.exists() else pd.DataFrame()
    age_h = (time.time() - cache.stat().st_mtime) / 3600 if cache.exists() else 1e9
    near_deadline = deadline is not None and (deadline - datetime.now(UTC)).total_seconds() < 24 * 3600
    due = age_h >= settings.odds.min_hours_between_calls or (near_deadline and age_h >= 3)
    if not (force or due):
        return _parse_odds_api(cache)
    params = {
        "apiKey": settings.odds_api_key,
        "regions": settings.odds.regions,
        "markets": settings.odds.markets,
        "oddsFormat": "decimal",
    }
    try:
        resp = httpx.get(ODDS_API, params=params, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("the-odds-api call failed: %s", exc)
        return _parse_odds_api(cache) if cache.exists() else pd.DataFrame()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(resp.text)
    quota = {k: resp.headers.get(k) for k in ("x-requests-remaining", "x-requests-used", "x-requests-last")}
    (cache.parent / "quota.json").write_text(json.dumps({**quota, "at": datetime.now(UTC).isoformat()}))
    log.info("the-odds-api quota: %s", quota)
    return _parse_odds_api(cache)


def _parse_odds_api(path: Path) -> pd.DataFrame:
    events = json.loads(path.read_text())
    rows = []
    for ev in events:
        home, away = team_from_odds_api(ev["home_team"]), team_from_odds_api(ev["away_team"])
        h2h: list[tuple[float, float, float]] = []
        totals: list[tuple[float, float, float]] = []  # (line, over, under)
        for bk in ev.get("bookmakers", []):
            for m in bk.get("markets", []):
                oc = {o["name"]: o for o in m.get("outcomes", [])}
                if m["key"] == "h2h" and {ev["home_team"], ev["away_team"], "Draw"} <= oc.keys():
                    h2h.append(
                        (oc[ev["home_team"]]["price"], oc["Draw"]["price"], oc[ev["away_team"]]["price"])
                    )
                elif m["key"] == "totals" and {"Over", "Under"} <= oc.keys():
                    totals.append((oc["Over"].get("point", 2.5), oc["Over"]["price"], oc["Under"]["price"]))
        if not h2h:
            continue
        probs = np.mean([devig(np.array(o)) for o in h2h], axis=0)
        row = {
            "commence_time": ev["commence_time"],
            "home": home,
            "away": away,
            "p_home": probs[0],
            "p_draw": probs[1],
            "p_away": probs[2],
            "line": np.nan,
            "p_over": np.nan,
        }
        if totals:
            lines = pd.Series([t[0] for t in totals])
            line = float(lines.mode().iloc[0])
            sel = [devig(np.array([o, u]))[0] for ln, o, u in totals if ln == line]
            row["line"], row["p_over"] = line, float(np.mean(sel))
        rows.append(row)
    df = pd.DataFrame(rows)
    if len(df):
        df["commence_time"] = pd.to_datetime(df["commence_time"], utc=True)
        df["date"] = df["commence_time"].dt.tz_convert("Europe/London").dt.date.astype(str)
    return df


# ------------------------------------------------------------------ odds maths
def devig(odds: np.ndarray, method: str = "power") -> np.ndarray:
    """Remove bookmaker margin from decimal odds -> probabilities summing to 1."""
    inv = 1.0 / np.asarray(odds, dtype=float)
    if not np.all(np.isfinite(inv)):
        return np.full_like(inv, np.nan)
    if method == "proportional":
        return inv / inv.sum()
    # power method: find k with sum(inv**k) == 1
    lo, hi = 0.5, 3.0
    for _ in range(60):
        k = (lo + hi) / 2
        s = np.sum(inv**k)
        lo, hi = (k, hi) if s > 1 else (lo, k)
    p = inv ** ((lo + hi) / 2)
    return p / p.sum()


def _score_matrix(lh: float, la: float, rho: float = 0.0, max_goals: int = 10) -> np.ndarray:
    g = np.arange(max_goals + 1)
    m = np.outer(poisson.pmf(g, lh), poisson.pmf(g, la))
    if rho:
        m[0, 0] *= 1 - lh * la * rho
        m[0, 1] *= 1 + lh * rho
        m[1, 0] *= 1 + la * rho
        m[1, 1] *= 1 - rho
        m /= m.sum()
    return m


def outcome_probs(
    lh: float, la: float, rho: float = 0.0, line: float = 2.5
) -> tuple[float, float, float, float]:
    m = _score_matrix(lh, la, rho)
    g = np.arange(m.shape[0])
    tot = g[:, None] + g[None, :]
    return (
        float(np.tril(m, -1).sum()),
        float(np.trace(m)),
        float(np.triu(m, 1).sum()),
        float(m[tot > line].sum()),
    )


def implied_lambdas(
    p_home: float,
    p_draw: float,
    p_away: float,
    p_over: float | None = None,
    line: float = 2.5,
    rho: float = -0.05,
) -> tuple[float, float]:
    """Solve for Poisson goal expectancies that reproduce the market probabilities."""
    target = np.array([p_home, p_draw, p_away])
    use_total = p_over is not None and np.isfinite(p_over)

    def loss(x: np.ndarray) -> float:
        lh, la = np.exp(x)
        ph, pd_, pa, po = outcome_probs(lh, la, rho, line)
        err = np.sum((np.array([ph, pd_, pa]) - target) ** 2)
        if use_total:
            err += (po - p_over) ** 2
        return float(err)

    res = minimize(
        loss,
        x0=np.log([1.5, 1.2]),
        method="Nelder-Mead",
        options={"xatol": 1e-6, "fatol": 1e-12, "maxiter": 2000},
    )
    lh, la = np.exp(res.x)
    return float(lh), float(la)


def fd_row_lambdas(row: pd.Series, closing: bool = False) -> tuple[float, float]:
    oh, od, oa = (row["ch"], row["cd"], row["ca"]) if closing else (row["oh"], row["od"], row["oa"])
    ov, un = (row["c_over"], row["c_under"]) if closing else (row["o_over"], row["o_under"])
    if not all(np.isfinite([oh, od, oa])):
        return np.nan, np.nan
    p = devig(np.array([oh, od, oa]))
    p_over = devig(np.array([ov, un]))[0] if np.isfinite(ov) and np.isfinite(un) else None
    return implied_lambdas(p[0], p[1], p[2], p_over)
