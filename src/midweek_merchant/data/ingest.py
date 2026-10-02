"""`mm ingest`: refresh every data source into ``data/processed``."""

from __future__ import annotations

import logging
from datetime import datetime

import numpy as np
import pandas as pd

from midweek_merchant.config import Settings
from midweek_merchant.data import current, elo_insights, history, odds, snapshots
from midweek_merchant.data.fpl_api import FPLClient
from midweek_merchant.data.store import read_table, write_table

log = logging.getLogger(__name__)


def previous_seasons(season: str, n: int) -> list[str]:
    start = int(season[:4])
    return [f"{y}-{str(y + 1)[-2:]}" for y in range(start - n, start)]


def ingest(settings: Settings, history_refresh: bool = True, use_odds_api: bool = True) -> dict[str, int]:
    settings.ensure_dirs()
    with FPLClient(cache_dir=settings.raw_dir / "fpl") as client:
        bootstrap = client.bootstrap(max_age=120)
        fixtures_raw = client.fixtures(max_age=120)
        teams = current.teams_table(bootstrap)
        players = current.players_table(bootstrap)
        events = current.events_table(bootstrap)
        fixtures = current.fixtures_table(fixtures_raw, teams, settings.season)
        pm_cur = current.player_matches(client, bootstrap, fixtures, settings.season)
        tm_cur = current.team_matches(fixtures, pm_cur)
    snapshots.archive_bootstrap(settings, bootstrap, players)

    write_table(settings, "teams", teams)
    write_table(settings, "players", players)
    write_table(settings, "events", events)
    write_table(settings, "fixtures", fixtures)

    # ---- history
    if history_refresh or not (settings.processed_dir / "pm_history.parquet").exists():
        pm_hist, tm_hist = history.load_history(settings)
        write_table(settings, "pm_history", pm_hist)
        write_table(settings, "tm_history", tm_hist)
    else:
        pm_hist, tm_hist = read_table(settings, "pm_history"), read_table(settings, "tm_history")

    pm = pd.concat([pm_hist, pm_cur], ignore_index=True)
    write_table(settings, "player_matches", pm)

    # ---- football-data results + odds, merged onto FPL fixtures
    fd_frames = []
    seasons = sorted(set(settings.history_seasons) | {settings.season})
    for s in seasons:
        for league in ("E0", "E1"):
            try:
                fd_frames.append(odds.load_fd(settings, s, league))
            except Exception as exc:  # noqa: BLE001
                log.warning("football-data %s %s unavailable: %s", league, s, exc)
    fd = pd.concat(fd_frames, ignore_index=True) if fd_frames else pd.DataFrame()

    tm_e0 = pd.concat([tm_hist, tm_cur[tm_hist.columns]], ignore_index=True)
    if len(fd):
        fd_e0 = fd[fd["league"] == "E0"].drop(columns=["league", "season", "hg", "ag"])
        tm_e0 = tm_e0.merge(fd_e0, on=["date", "home", "away"], how="left")
        unmatched = tm_e0["finished"].fillna(False) & tm_e0["oh"].isna()
        if unmatched.any():
            log.info("%d finished FPL fixtures without football-data odds match", int(unmatched.sum()))
        # fill missing FPL xG with football-data xG where available
        for a, b in (("hxg", "hxg_fd"), ("axg", "axg_fd")):
            tm_e0[a] = tm_e0[a].fillna(tm_e0[b])
    write_table(settings, "team_matches", tm_e0)

    # ---- point-in-time player snapshots (news, prices, FPL ep) for hindcasts/backtests
    snaps = elo_insights.load_all(settings, previous_seasons(settings.season, 1) + [settings.season])
    if len(snaps):
        write_table(settings, "player_snapshots", snaps)

    if len(fd):
        e1 = fd[fd["league"] == "E1"].rename(columns={"hxg_fd": "hxg", "axg_fd": "axg"})
        e1["finished"] = e1["hg"].notna()
        write_table(settings, "fd_e1", e1)

    # ---- upcoming market odds
    deadline = _next_deadline(events)
    up = []
    try:
        fdf = odds.load_fd_fixtures(settings)
        if len(fdf):
            fdf = fdf.assign(source="football-data")
            up.append(fdf)
    except Exception as exc:  # noqa: BLE001
        log.warning("football-data fixtures unavailable: %s", exc)
    if use_odds_api:
        oa = odds.fetch_odds_api(settings, deadline=deadline)
        if len(oa):
            up.append(oa.assign(source="the-odds-api"))
    market = _market_lambdas(up)
    write_table(settings, "market_odds", market)

    counts = {
        "players": len(players),
        "player_matches": len(pm),
        "current_rows": len(pm_cur),
        "team_matches": len(tm_e0),
        "market_fixtures": len(market),
    }
    log.info("ingest complete: %s", counts)
    return counts


def _next_deadline(events: pd.DataFrame) -> datetime | None:
    nxt = events.loc[events["is_next"] == True, "deadline_time"]  # noqa: E712
    return nxt.iloc[0].to_pydatetime() if len(nxt) else None


def _market_lambdas(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Odds-implied lambdas for upcoming fixtures; the-odds-api preferred over football-data."""
    rows = []
    for df in frames:
        for r in df.itertuples(index=False):
            r = r._asdict()
            if r.get("source") == "the-odds-api":
                p_over = r.get("p_over")
                line = r.get("line") if np.isfinite(r.get("line", np.nan)) else 2.5
                lh, la = odds.implied_lambdas(
                    r["p_home"], r["p_draw"], r["p_away"], p_over if np.isfinite(p_over) else None, line
                )
            else:
                lh, la = odds.fd_row_lambdas(pd.Series(r))
            if np.isfinite(lh):
                rows.append(
                    {
                        "date": r["date"],
                        "home": r["home"],
                        "away": r["away"],
                        "lh": lh,
                        "la": la,
                        "source": r["source"],
                    }
                )
    cols = ["date", "home", "away", "lh", "la", "source"]
    if not rows:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame(rows)
    out["prio"] = (out["source"] == "the-odds-api").astype(int)
    out = out.sort_values("prio", ascending=False).drop_duplicates(["home", "away"]).drop(columns="prio")
    return out[cols].reset_index(drop=True)
