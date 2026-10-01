"""Shared dashboard plumbing: imports, settings, data loading, theme tokens, formatting."""

from __future__ import annotations

import contextlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from midweek_merchant.config import get_settings  # noqa: E402
from midweek_merchant.publish import REMOTE_BASE, sync_from_remote  # noqa: E402

SETTINGS = get_settings()

# Colour tokens (reference data-viz palette): text never wears series colours.
TOKENS = {
    "light": {
        "surface": "#fcfcfb",
        "page": "#f9f9f7",
        "ink": "#0b0b0b",
        "ink2": "#52514e",
        "muted": "#898781",
        "grid": "#e1e0d9",
        "axis": "#c3c2b7",
        "border": "rgba(11,11,11,0.10)",
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
        "seq": ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
        "good": "#006300",
        "bad": "#d03b3b",
        "pitch": "#e8f2e8",
        "pitch_line": "#c7dcc7",
        "card": "#ffffff",
    },
    "dark": {
        "surface": "#1a1a19",
        "page": "#0d0d0d",
        "ink": "#ffffff",
        "ink2": "#c3c2b7",
        "muted": "#898781",
        "grid": "#2c2c2a",
        "axis": "#383835",
        "border": "rgba(255,255,255,0.10)",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
        "seq": ["#0d366b", "#104281", "#184f95", "#1c5cab", "#2a78d6", "#5598e7", "#86b6ef"],
        "good": "#0ca30c",
        "bad": "#e66767",
        "pitch": "#16261a",
        "pitch_line": "#24402b",
        "card": "#232322",
    },
}


def theme() -> dict[str, Any]:
    kind = "light"
    with contextlib.suppress(Exception):
        kind = st.context.theme.type or "light"
    return TOKENS["dark" if kind == "dark" else "light"]


def page_setup(title: str) -> None:
    st.title(title)


@st.cache_data(ttl=600, show_spinner="Loading data…")
def ensure_data() -> dict[str, Any]:
    """Make sure outputs exist locally; otherwise pull the latest published bundle."""
    out = SETTINGS.outputs_dir / "projections.parquet"
    source = "local"
    if not out.exists():
        sync_from_remote(SETTINGS)
        source = "published"
    meta = json.loads((SETTINGS.outputs_dir / "forecast_meta.json").read_text())
    return {"source": source, "meta": meta}


@st.cache_data(ttl=600)
def projections() -> pd.DataFrame:
    ensure_data()
    return pd.read_parquet(SETTINGS.outputs_dir / "projections.parquet")


@st.cache_data(ttl=600)
def table(name: str) -> pd.DataFrame:
    ensure_data()
    return pd.read_parquet(SETTINGS.processed_dir / f"{name}.parquet")


@st.cache_data(ttl=600)
def output(name: str) -> Any:
    ensure_data()
    path = SETTINGS.outputs_dir / name
    if not path.exists():
        return None
    if name.endswith(".parquet"):
        return pd.read_parquet(path)
    return json.loads(path.read_text())


def clear_caches() -> None:
    st.cache_data.clear()


def next_deadline() -> tuple[int | None, datetime | None]:
    ev = table("events")
    nxt = ev[ev["is_next"] == True]  # noqa: E712
    if not len(nxt):
        return None, None
    r = nxt.iloc[0]
    return int(r["gw"]), pd.Timestamp(r["deadline_time"]).to_pydatetime()


def countdown(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    delta = dt - datetime.now(UTC)
    if delta.total_seconds() <= 0:
        return "passed"
    d, rem = divmod(int(delta.total_seconds()), 86400)
    h, rem = divmod(rem, 3600)
    return f"{d}d {h}h {rem // 60}m"


def price(tenths: float) -> str:
    return f"£{tenths / 10:.1f}m"


def player_label(row: pd.Series | dict) -> str:
    return f"{row['name']} ({row['team_short']}, {row['position']}, {price(row['now_cost'])})"


def remote_note() -> str:
    return f"Published data: {REMOTE_BASE}"
