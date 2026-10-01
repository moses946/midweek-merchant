"""On-disk layout helpers (parquet/JSON under ``data/``)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from midweek_merchant.config import Settings

# Standard player-match columns shared by historical (vaastav) and current-season data.
PM_COLS = [
    "season", "gw", "fixture", "kickoff_time", "code", "element", "name", "position", "team",
    "opponent", "was_home", "minutes", "starts", "goals", "assists", "xg", "xa", "xgc", "cs", "gc",
    "saves", "bonus", "bps", "yc", "rc", "og", "pen_saved", "pen_missed", "dc", "cbi", "tackles",
    "recoveries", "points", "value", "selected",
]

# Standard team-match columns.
TM_COLS = [
    "season", "league", "gw", "fixture", "kickoff_time", "date", "home", "away", "hg", "ag", "hxg", "axg",
    "finished",
]


def processed(settings: Settings, name: str) -> Path:
    return settings.processed_dir / f"{name}.parquet"


def write_table(settings: Settings, name: str, df: pd.DataFrame) -> Path:
    settings.ensure_dirs()
    path = processed(settings, name)
    df.to_parquet(path, index=False)
    return path


def read_table(settings: Settings, name: str) -> pd.DataFrame:
    return pd.read_parquet(processed(settings, name))


def write_output(settings: Settings, name: str, obj: Any) -> Path:
    settings.ensure_dirs()
    path = settings.outputs_dir / name
    if isinstance(obj, pd.DataFrame):
        obj.to_parquet(path, index=False)
    else:
        path.write_text(json.dumps(obj, indent=1, default=_json_default))
    return path


def read_output(settings: Settings, name: str) -> Any:
    path = settings.outputs_dir / name
    if name.endswith(".parquet"):
        return pd.read_parquet(path)
    return json.loads(path.read_text())


def _json_default(o: Any) -> Any:
    if hasattr(o, "item"):
        return o.item()
    if isinstance(o, pd.Timestamp):
        return o.isoformat()
    raise TypeError(f"Not JSON serialisable: {type(o)}")


def download(url: str, dest: Path, max_age: float | None = None, timeout: float = 60) -> Path:
    """Download ``url`` to ``dest`` unless a fresh-enough copy exists."""
    if dest.exists() and (max_age is None or time.time() - dest.stat().st_mtime < max_age):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=timeout, follow_redirects=True) as http:
        resp = http.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return dest
