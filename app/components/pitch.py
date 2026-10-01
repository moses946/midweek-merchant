"""Pitch / formation view rendered as HTML."""

from __future__ import annotations

import html
from typing import Any

import streamlit as st

from components.common import theme

ROWS = ["GKP", "DEF", "MID", "FWD"]


def _card(p: dict[str, Any], t: dict[str, Any], badge: str = "", highlight: bool = False) -> str:
    ring = f"box-shadow:0 0 0 2px {t['series'][0]};" if highlight else ""
    badge_html = (
        f'<span style="position:absolute;top:-8px;right:-8px;background:{t["ink"]};color:{t["surface"]};'
        f'border-radius:10px;font-size:11px;font-weight:700;padding:1px 6px">{badge}</span>'
        if badge
        else ""
    )
    subtitle = f"£{p['price']:.1f}m" if "actual" in p else str(p["fixture"])
    width = (74, 98) if "actual" in p else (92, 130)
    if "actual" in p:  # hindcast card: prediction made before the deadline vs what happened
        did_not_play = p.get("minutes", 1) == 0
        ink = t["muted"] if did_not_play else t["ink"]
        result = "DNP" if did_not_play else f"{p['actual']:.0f}"
        stats = (
            f'<div style="font-size:12px;color:{t["ink2"]};font-variant-numeric:tabular-nums">'
            f'pred {p["xpts"]:.1f} → <b style="color:{ink}">{result}</b></div>'
        )
    else:
        ink = t["ink"]
        stats = (
            f'<div style="font-size:12px;color:{t["ink"]};font-variant-numeric:tabular-nums">'
            f"{p['xpts']:.1f} xPts · £{p['price']:.1f}m</div>"
        )
    return (
        f'<div style="position:relative;background:{t["card"]};border:1px solid {t["border"]};{ring}'
        f'border-radius:8px;padding:6px 8px;min-width:{width[0]}px;max-width:{width[1]}px;text-align:center">'
        f"{badge_html}"
        f'<div style="font-weight:600;font-size:13px;color:{ink};white-space:nowrap;overflow:hidden;'
        f'text-overflow:ellipsis">{html.escape(p["name"])}</div>'
        f'<div style="font-size:11px;color:{t["ink2"]};white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
        f"{html.escape(str(p['team']))} · {html.escape(subtitle)}</div>"
        f"{stats}</div>"
    )


def render_week(week: dict[str, Any], highlight: set[int] | None = None, title: str | None = None) -> None:
    """Render one plan week (lineup by position + ordered bench)."""
    t = theme()
    highlight = highlight or set()
    cap, vice = week["captain"]["element"], week["vice"]["element"]
    triple = week.get("chip") == "3xc"

    def badge(e: int) -> str:
        if e == cap:
            return "TC" if triple else "C"
        return "V" if e == vice else ""

    rows_html = []
    for pos in ROWS:
        players = [p for p in week["lineup"] if p["position"] == pos]
        if not players:
            continue
        cards = "".join(_card(p, t, badge(p["element"]), p["element"] in highlight) for p in players)
        rows_html.append(
            f'<div style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap">{cards}</div>'
        )
    bench = "".join(_card(p, t, "", p["element"] in highlight) for p in week["bench"])
    head = (
        f'<div style="font-weight:600;color:{t["ink"]};margin-bottom:6px">{html.escape(title)}</div>'
        if title
        else ""
    )
    st.html(
        f"""{head}
        <div style="background:{t["pitch"]};border:1px solid {t["pitch_line"]};border-radius:12px;padding:14px 8px;
                    display:flex;flex-direction:column;gap:14px">{"".join(rows_html)}</div>
        <div style="margin-top:8px;font-size:12px;color:{t["ink2"]}">Bench (in order)</div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:4px">{bench or "<em>Bench Boost: all 15 play</em>"}</div>"""
    )
