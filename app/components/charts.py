"""Plotly figure builders following the reference data-viz palette and mark specs."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from components.common import theme

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def _layout(fig: go.Figure, height: int = 420, **kw) -> go.Figure:  # noqa: ANN003
    t = theme()
    fig.update_layout(
        height=height,
        margin=dict(l=48, r=16, t=56, b=48),
        paper_bgcolor=t["surface"],
        plot_bgcolor=t["surface"],
        font=dict(family=FONT, color=t["ink2"], size=12),
        hoverlabel=dict(font=dict(family=FONT)),
        legend=dict(orientation="h", yanchor="top", y=-0.22, x=0, font=dict(color=t["ink2"])),
        **kw,
    )
    fig.update_xaxes(
        gridcolor=t["grid"], linecolor=t["axis"], zeroline=False, tickfont=dict(color=t["muted"])
    )
    fig.update_yaxes(
        gridcolor=t["grid"], linecolor=t["axis"], zeroline=False, tickfont=dict(color=t["muted"])
    )
    return fig


def _seq_scale() -> list[list]:
    seq = theme()["seq"]
    n = len(seq) - 1
    return [[i / n, c] for i, c in enumerate(seq)]


def fixture_ticker(rows: pd.DataFrame, value: str, title: str) -> go.Figure:
    """Team × gameweek heatmap. ``rows`` has team_short, gw, label (opponent), and ``value``."""
    t = theme()
    pv = rows.pivot_table(index="team_short", columns="gw", values=value, aggfunc="sum")
    lab = rows.groupby(["team_short", "gw"])["label"].agg(" + ".join).unstack("gw").reindex_like(pv)
    order = pv.mean(axis=1).sort_values(ascending=True).index
    pv, lab = pv.loc[order], lab.loc[order]
    z = pv.to_numpy()
    zmin, zmax = float(pd.Series(z.ravel()).quantile(0.02)), float(pd.Series(z.ravel()).quantile(0.98))
    # Plotly picks white/ink cell text by the fill's luminance, so labels always clear contrast.
    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=[f"GW{g}" for g in pv.columns],
            y=list(pv.index),
            colorscale=_seq_scale(),
            zmin=zmin,
            zmax=zmax,
            text=lab.fillna("blank").to_numpy(),
            texttemplate="%{text}",
            textfont=dict(size=10),
            hovertemplate="%{y} %{x}<br>%{text}<br>" + value + ": %{z:.2f}<extra></extra>",
            xgap=2,
            ygap=2,
            colorbar=dict(thickness=10, outlinewidth=0, tickfont=dict(color=t["muted"])),
        )
    )
    fig = _layout(fig, height=max(380, 24 * len(pv) + 80), title=dict(text=title, font=dict(color=t["ink"])))
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(showgrid=False, side="top")
    return fig


def bar(
    df: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    hover: str | None = None,
    horizontal: bool = True,
    height: int = 380,
) -> go.Figure:
    t = theme()
    kw = dict(x=df[y], y=df[x], orientation="h") if horizontal else dict(x=df[x], y=df[y])
    # cap bar thickness at ~24px: width is a fraction of each category band
    band_px = (height - 80) / max(len(df), 1) if horizontal else 700 / max(len(df), 1)
    width = min(0.6, 24 / max(band_px, 1))
    fig = go.Figure(
        go.Bar(
            **kw,
            marker=dict(color=t["series"][0], cornerradius=4),
            width=width,
            hovertext=df[hover] if hover else None,
            hovertemplate=(
                ("%{hovertext}<br>" if hover else "")
                + ("%{y}: %{x:.2f}" if horizontal else "%{x}: %{y:.2f}")
                + "<extra></extra>"
            ),
        )
    )
    fig = _layout(fig, height=height, title=dict(text=title, font=dict(color=t["ink"])))
    if horizontal:
        fig.update_yaxes(autorange="reversed", showgrid=False)
    else:
        fig.update_xaxes(showgrid=False)
    return fig


def lines(
    df: pd.DataFrame,
    x: str,
    y: str,
    series: str,
    title: str,
    order: list[str] | None = None,
    highlight: str | None = None,
    height: int = 420,
) -> go.Figure:
    """Multi-series line chart with fixed categorical order (colour follows the entity)."""
    t = theme()
    order = order or list(dict.fromkeys(df[series]))
    fig = go.Figure()
    for k, name in enumerate(order[:8]):
        d = df[df[series] == name]
        color = t["series"][k % 8]
        fig.add_trace(
            go.Scatter(
                x=d[x],
                y=d[y],
                name=str(name),
                mode="lines+markers",
                line=dict(color=color, width=3 if name == highlight else 2, shape="linear"),
                marker=dict(size=8, color=color, line=dict(color=t["surface"], width=2)),
                hovertemplate=f"{name}<br>{x} %{{x}}: %{{y:.1f}}<extra></extra>",
            )
        )
    fig = _layout(
        fig, height=height, title=dict(text=title, font=dict(color=t["ink"])), hovermode="x unified"
    )
    return fig


def scatter_calibration(df: pd.DataFrame, x: str, y: str, title: str) -> go.Figure:
    t = theme()
    lim = float(max(df[x].max(), df[y].max()))
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[0, lim],
            y=[0, lim],
            mode="lines",
            name="perfect calibration",
            line=dict(color=t["axis"], width=1),
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df[x],
            y=df[y],
            mode="lines+markers",
            name="model",
            line=dict(color=t["series"][0], width=2),
            marker=dict(size=8, color=t["series"][0], line=dict(color=t["surface"], width=2)),
            hovertemplate="predicted %{x:.2f}<br>actual %{y:.2f}<extra></extra>",
        )
    )
    fig = _layout(fig, height=380, title=dict(text=title, font=dict(color=t["ink"])))
    fig.update_xaxes(title=dict(text="Predicted xPts", font=dict(color=t["ink2"])))
    fig.update_yaxes(title=dict(text="Actual points", font=dict(color=t["ink2"])))
    # the top-left of a calibration plot is empty: keep the legend there, clear of the axis titles
    fig.update_layout(legend=dict(orientation="v", x=0.02, y=0.98, yanchor="top", bgcolor="rgba(0,0,0,0)"))
    return fig
