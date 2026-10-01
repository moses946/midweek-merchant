import json

import numpy as np
import pandas as pd
import streamlit as st

from components import charts, common

common.page_setup("Projections")
proj = common.projections()
meta = common.ensure_data()["meta"]
gws = meta["gws"]

f1, f2, f3, f4, f5 = st.columns([2, 2, 2, 2, 2])
positions = f1.multiselect("Position", ["GKP", "DEF", "MID", "FWD"], default=[])
teams = f2.multiselect("Team", sorted(proj["team_short"].unique()), default=[])
max_price = f3.slider("Max price (£m)", 3.5, 16.0, 16.0, 0.5)
gw_range = f4.select_slider("Gameweeks", options=gws, value=(gws[0], gws[min(5, len(gws) - 1)]))
search = f5.text_input("Search player")

sel = [g for g in gws if gw_range[0] <= g <= gw_range[1]]
p = proj[proj["gw"].isin(sel)]
wide = p.pivot_table(index="element", columns="gw", values="xpts", aggfunc="sum")
wide.columns = [f"GW{c}" for c in wide.columns]
info = proj.drop_duplicates("element").set_index("element")
nxt = proj[proj["gw"] == sel[0]].set_index("element")
df = info[["name", "team_short", "position", "now_cost", "status", "news", "selected_by_percent"]].join(wide)
df["total"] = wide.sum(axis=1)
df["xmins"] = nxt["xmins"]
df["p_start"] = nxt["p_start"] * 100
df["per_m"] = df["total"] / (df["now_cost"] / 10)
df["price"] = df["now_cost"] / 10
if positions:
    df = df[df["position"].isin(positions)]
if teams:
    df = df[df["team_short"].isin(teams)]
df = df[df["price"] <= max_price]
if search:
    df = df[df["name"].str.contains(search, case=False, na=False)]
df["flag"] = np.where(df["status"] == "a", "", "⚠ ") + df["news"].fillna("")
df = df.sort_values("total", ascending=False)

gw_cols = list(wide.columns)
st.dataframe(
    df[
        [
            "name",
            "team_short",
            "position",
            "price",
            "total",
            "per_m",
            *gw_cols,
            "xmins",
            "p_start",
            "selected_by_percent",
            "flag",
        ]
    ],
    hide_index=True,
    width="stretch",
    height=560,
    column_config={
        "name": "Player",
        "team_short": "Team",
        "position": "Pos",
        "price": st.column_config.NumberColumn("Price", format="£%.1fm"),
        "total": st.column_config.NumberColumn("Total xPts", format="%.1f"),
        "per_m": st.column_config.NumberColumn("xPts/£m", format="%.2f"),
        **{c: st.column_config.NumberColumn(c, format="%.1f") for c in gw_cols},
        "xmins": st.column_config.NumberColumn(f"xMins GW{sel[0]}", format="%.0f"),
        "p_start": st.column_config.NumberColumn("P(start)", format="%.0f%%"),
        "selected_by_percent": st.column_config.NumberColumn("Owned %", format="%.1f"),
        "flag": "News",
    },
)
st.download_button("Download CSV", df.to_csv(index=False).encode(), "projections.csv", "text/csv")

st.subheader("Fixture ticker")
fx = common.output("fixture_lambdas.parquet")
teams_tbl = common.table("teams")
short = dict(zip(teams_tbl["team"], teams_tbl["short_name"], strict=True))
if fx is not None and len(fx):
    mode = st.radio("Show", ["Expected goals scored", "Clean sheet chance"], horizontal=True)
    rows = []
    for r in fx.itertuples():
        for team, opp, lam_f, lam_a, venue in (
            (r.home, r.away, r.lh, r.la, "H"),
            (r.away, r.home, r.la, r.lh, "A"),
        ):
            rows.append(
                {
                    "team_short": short.get(team, team),
                    "gw": int(r.gw),
                    "label": f"{short.get(opp, opp)}({venue})",
                    "xg": lam_f,
                    "cs": float(np.exp(-lam_a)),
                }
            )
    ticker = pd.DataFrame(rows)
    value = "xg" if mode.startswith("Expected") else "cs"
    title = (
        "Team expected goals per gameweek (darker = more goals)"
        if value == "xg"
        else "Clean-sheet probability per gameweek (darker = more likely)"
    )
    st.plotly_chart(charts.fixture_ticker(ticker, value, title), width="stretch", theme=None)
    st.caption("Double gameweeks show both opponents and sum the values; blank gameweeks show as gaps.")

st.subheader("Price change watch")
players = common.table("players")
pw = players[players["price_change_percent"].abs() >= 60].copy()
if len(pw):
    pw["direction"] = np.where(pw["price_change_percent"] > 0, "▲ rising", "▼ falling")

    def tonight(s: str) -> float:
        proj_ = json.loads(s or "[]")
        return float(proj_[0]["projected_percent"]) if proj_ else np.nan

    pw["projected_next"] = pw["price_change_projections"].map(tonight)
    pw = pw.sort_values("price_change_percent", key=abs, ascending=False)
    st.dataframe(
        pw[
            [
                "name",
                "team_short",
                "position",
                "now_cost",
                "direction",
                "price_change_percent",
                "projected_next",
                "transfers_in_event",
                "transfers_out_event",
            ]
        ].assign(now_cost=lambda d: d["now_cost"] / 10),
        hide_index=True,
        width="stretch",
        column_config={
            "name": "Player",
            "team_short": "Team",
            "position": "Pos",
            "now_cost": st.column_config.NumberColumn("Price", format="£%.1fm"),
            "direction": "Direction",
            "price_change_percent": st.column_config.NumberColumn("Progress %", format="%.0f"),
            "projected_next": st.column_config.NumberColumn("Projected at next update %", format="%.0f"),
            "transfers_in_event": "Transfers in (GW)",
            "transfers_out_event": "Transfers out (GW)",
        },
    )
    st.caption(
        "FPL's official predictor: at ±100% a player is expected to change price at the next 00:00 UK "
        "update. Buy risers before then; sell fallers you plan to drop."
    )
else:
    st.write("No players close to a price change.")
