"""Archive point-in-time player state (news, availability, prices, ownership).

Nobody publishes historical FPL news/availability, so we build our own archive:
each run appends a slim snapshot that later trains the minutes model and price
predictions, plus a gzipped copy of the full bootstrap once per day.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from midweek_merchant.config import Settings

SLIM_COLS = [
    "element",
    "code",
    "status",
    "news",
    "chance_next",
    "chance_this",
    "now_cost",
    "selected_by_percent",
    "transfers_in_event",
    "transfers_out_event",
    "price_change_percent",
    "price_change_hourly_rate",
    "price_change_locked_until",
    "ep_next",
]


def archive_bootstrap(settings: Settings, bootstrap: dict[str, Any], players: pd.DataFrame) -> None:
    now = datetime.now(UTC)
    day_dir = settings.raw_dir / "snapshots" / now.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    full = day_dir / "bootstrap.json.gz"
    if not full.exists():
        with gzip.open(full, "wt") as fh:
            json.dump(bootstrap, fh)
    slim = players[SLIM_COLS].copy()
    slim["snapshot_time"] = now
    slim["next_gw"] = next((e["id"] for e in bootstrap["events"] if e["is_next"]), None)
    slim.to_parquet(day_dir / f"players_{now.strftime('%H%M')}.parquet", index=False)


def load_slim_history(settings: Settings) -> pd.DataFrame:
    files = sorted((settings.raw_dir / "snapshots").glob("*/players_*.parquet"))
    if not files:
        return pd.DataFrame(columns=SLIM_COLS + ["snapshot_time", "next_gw"])
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
