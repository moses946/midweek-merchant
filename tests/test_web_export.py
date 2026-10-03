"""The React dashboard's JSON bundle, built from a tiny synthetic data directory."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from midweek_merchant.config import Settings
from midweek_merchant.web_export import export_web


def _settings(tmp_path: Path) -> Settings:
    s = Settings(season="2026-27", team_id=7, league_id=None, data_dir=tmp_path / "data")
    s.ensure_dirs()
    teams = pd.DataFrame(
        {
            "team_id": [1, 2],
            "code": [3, 7],
            "team": ["Arsenal", "Aston Villa"],
            "fpl_name": ["Arsenal", "Aston Villa"],
            "short_name": ["ARS", "AVL"],
        }
    )
    teams.to_parquet(s.processed_dir / "teams.parquet")
    pd.DataFrame(
        {
            "gw": [5, 6, 7],
            "deadline_time": pd.to_datetime(
                ["2026-09-18 17:30", "2026-10-10 10:00", "2026-10-17 10:00"], utc=True
            ),
            "finished": [True, False, False],
            "average_entry_score": [48, 0, 0],
            "highest_score": [126.0, np.nan, np.nan],
        }
    ).to_parquet(s.processed_dir / "events.parquet")
    pd.DataFrame(
        {
            "gw": [6.0, 7.0, np.nan],
            "home": ["Arsenal", "Arsenal", "Aston Villa"],
            "away": ["Aston Villa", "Aston Villa", "Arsenal"],
            "finished": [False, False, False],
        }
    ).to_parquet(s.processed_dir / "fixtures.parquet")
    rows = []
    for e, (name, pos, team) in {1: ("Raya", "GKP", "ARS"), 2: ("Watkins", "FWD", "AVL")}.items():
        for gw, xp in ((6, 3.0 + e), (7, np.nan if e == 2 else 2.5)):
            rows.append(
                {
                    "element": e,
                    "name": name,
                    "full_name": name,
                    "position": pos,
                    "team_short": team,
                    "now_cost": 60 + e,
                    "status": "a",
                    "news": "",
                    "chance_next": np.nan,
                    "selected_by_percent": 10.0,
                    "form": 3.0,
                    "total_points": 20,
                    "ep_next": 3.0,
                    "price_change_percent": 0.0,
                    "gw": gw,
                    "xpts": xp,
                    "xmins": 90.0,
                    "fixtures": "AVL(H)" if team == "ARS" else "ARS(A)",
                    "p_start": 0.95,
                    "e_goals": 0.1,
                    "e_assists": 0.1,
                    "p_cs": 0.3,
                    **{c: 0.1 for c in ("x_app", "x_goals", "x_assists", "x_cs", "x_gc", "x_saves")},
                    **{c: 0.1 for c in ("x_dc", "x_bonus", "x_cards")},
                }
            )
    pd.DataFrame(rows).to_parquet(s.outputs_dir / "projections.parquet")
    (s.outputs_dir / "forecast_meta.json").write_text(
        json.dumps({"next_gw": 6, "gws": [6, 7], "generated_at": "2026-10-03T16:28:52+00:00"})
    )
    (s.outputs_dir / "plan_7.json").write_text(json.dumps({"state": {"name": "x"}, "weeks": []}))
    ceiling = {"table": [{"plan": 3}, {"plan": 1}], "reference": 1, "plans": {"1": {}, "2": {}, "3": {}}}
    (s.outputs_dir / "ceiling_7.json").write_text(json.dumps(ceiling))
    old = {"gameweeks": [{"gw": 2, "picks": {"model": {}, "hindsight": {}, "form": {}}}], "summary": []}
    (s.outputs_dir / "hindcast_2025-26.json").write_text(json.dumps(old))
    (s.outputs_dir / "hindcast_team_7_gw2.json").write_text("{}")
    return s


def test_export_web(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    dest = tmp_path / "web"
    meta = export_web(s, dest)

    assert meta["next_gw"] == 6 and meta["deadline"].startswith("2026-10-10")
    assert meta["files"]["plan"] == "plan_7.json" and "league" not in meta["files"]
    assert meta["files"]["hindcast"] == {"2025-26": "hindcast_2025-26.json"}  # team replays are not seasons
    assert json.loads((dest / "meta.json").read_text())["files"] == meta["files"]
    assert [(t["short"], t["code"]) for t in meta["teams"]] == [("ARS", 3), ("AVL", 7)]

    players = json.loads((dest / "players.json").read_text())
    assert [p["id"] for p in players] == [2, 1]  # sorted by next-GW xPts
    assert players[0]["xp"] == [5.0, None]  # NaN becomes null, never invalid JSON
    assert players[1]["price"] == 6.1 and players[1]["next"]["breakdown"]["bonus"] == 0.1

    fx = json.loads((dest / "fixtures.json").read_text())
    assert fx["unscheduled"] == 1
    assert {c["gw"]: c["blank"] for c in fx["calendar"]} == {6: [], 7: []}

    assert set(json.loads((dest / "ceiling_7.json").read_text())["plans"]) == {"1", "3"}
    past = json.loads((dest / "hindcast_2025-26.json").read_text())
    assert set(past["gameweeks"][0]["picks"]) == {"model", "hindsight"}
