"""Hindcast tests.

* ``test_score_*`` are pure unit tests of the scoring (auto-subs, vice-captain).
* ``test_no_leak`` re-runs a real hindcast after deleting every statistic from the target
  gameweek onwards and checks the predictions and the picked XI are unchanged. It needs the
  local processed tables (``mm ingest``) and is skipped otherwise.
"""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from midweek_merchant.backtest import run as bt
from midweek_merchant.backtest.hindcast import _score
from midweek_merchant.config import get_settings


def _week(lineup: list[int], bench: list[int], cap: int, vice: int) -> dict:
    p = lambda e: {"element": e, "name": f"P{e}"}  # noqa: E731
    return {
        "lineup": [p(e) for e in lineup],
        "bench": [p(e) for e in bench],
        "captain": p(cap),
        "vice": p(vice),
    }


def test_score_autosub_and_vice() -> None:
    actual = pd.DataFrame({"points": [6, 2, 0, 9, 1], "minutes": [90, 90, 0, 90, 90]}, index=[1, 2, 3, 4, 5])
    # starters 1,2,3 (3 did not play), bench 4,5; captain 3 did not play -> vice 1 doubles
    s = _score(_week([1, 2, 3], [4, 5], cap=3, vice=1), gw=1, actual=actual)
    assert s["points"] == 6 + 2 + 9 + 6  # first bench player (4) comes on; vice 1 doubles
    assert not s["captain_played"] and s["captain_points"] == 6


def test_score_captain_played() -> None:
    actual = pd.DataFrame({"points": [10, 3], "minutes": [90, 90]}, index=[1, 2])
    s = _score(_week([1, 2], [], cap=1, vice=2), gw=1, actual=actual)
    assert s["points"] == 23 and s["captain_points"] == 10


STAT_COLS = [
    "minutes",
    "starts",
    "goals",
    "assists",
    "xg",
    "xa",
    "xgc",
    "cs",
    "gc",
    "saves",
    "bonus",
    "bps",
    "yc",
    "rc",
    "og",
    "pen_saved",
    "pen_missed",
    "dc",
    "cbi",
    "tackles",
    "recoveries",
    "points",
    "fpl_xp",
    "selected",
]


def _truncate(t: bt.Tables, season: str, gw: int, cutoff: str) -> bt.Tables:
    """Remove every statistic from (season, gw) onwards; keep only registration/fixture facts."""
    pm = t.pm.copy()
    key = pm["season"].str[:4].astype(int) * 100 + pm["gw"].astype(int)
    target = int(season[:4]) * 100 + gw
    pm = pm[key <= target].copy()
    cur = (pm["season"] == season) & (pm["gw"] == gw)
    pm.loc[cur, STAT_COLS] = np.nan
    tm = t.tm[(t.tm["date"] < cutoff) | ((t.tm["season"] == season) & (t.tm["gw"] == gw))].copy()
    cur_t = (tm["season"] == season) & (tm["gw"] == gw)
    closing = [
        c
        for c in tm.columns
        if c in ("hg", "ag", "hxg", "axg", "hxg_fd", "axg_fd", "ch", "cd", "ca", "c_over", "c_under")
    ]
    tm.loc[cur_t, closing] = np.nan
    tm.loc[cur_t, "finished"] = False
    e1 = t.e1[t.e1["date"] < cutoff]
    snaps = t.snaps[(t.snaps["season"] != season) | (t.snaps["snapshot_gw"] <= gw - 1)]
    snaps = snaps[snaps["season"].str[:4].astype(int) <= int(season[:4])]
    return bt.Tables(pm=pm, tm=tm, e1=e1, snaps=snaps, events=t.events)


@pytest.mark.network
@pytest.mark.parametrize(("season", "gw"), [("2025-26", 20), ("2026-27", 5)])
def test_no_leak(season: str, gw: int) -> None:
    s = get_settings()
    if not (s.processed_dir / "player_snapshots.parquet").exists():
        pytest.skip("needs local data: run `mm ingest`")
    from midweek_merchant.forecast import load_rules
    from midweek_merchant.optimize.milp import PlanOptions
    from midweek_merchant.optimize.planner import best_squad_per_gw

    rules = load_rules(s)
    full = bt.load_tables(s)
    inp = bt.point_in_time_inputs(s, full, season, gw)
    assert inp is not None and inp.snapshot_used
    cutoff = inp.upcoming["kickoff_time"].min().tz_convert("Europe/London").date().isoformat()
    cut = _truncate(full, season, gw, cutoff)
    inp_cut = bt.point_in_time_inputs(s, cut, season, gw)
    a = bt.point_in_time_forecast(s, full, inp, rules).set_index("element")["xpts"]
    b = bt.point_in_time_forecast(s, cut, inp_cut, rules).set_index("element")["xpts"]
    pd.testing.assert_series_equal(a.sort_index(), b.sort_index(), check_exact=False, atol=1e-9)

    opts = replace(PlanOptions.from_config(s.optimizer), mip_gap=0.0)
    proj = bt.point_in_time_forecast(s, full, inp, rules)
    pick_a = best_squad_per_gw(proj, rules, opts, gws=[gw])[gw].weeks[0]
    proj_b = bt.point_in_time_forecast(s, cut, inp_cut, rules)
    pick_b = best_squad_per_gw(proj_b, rules, opts, gws=[gw])[gw].weeks[0]
    assert sorted(pick_a.lineup) == sorted(pick_b.lineup) and pick_a.captain == pick_b.captain
