import pandas as pd
import streamlit as st

from components import common

common.page_setup("Midweek Merchant")
st.caption("Expected points, optimal squads and mini-league strategy for Fantasy Premier League 2026/27.")

try:
    info = common.ensure_data()
except Exception as exc:  # noqa: BLE001
    st.error(
        f"No data available yet ({exc}). Run `mm ingest && mm forecast` locally or wait for the scheduled job."
    )
    st.stop()

meta = info["meta"]
gw, deadline = common.next_deadline()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Next gameweek", f"GW{gw}" if gw else "—")
c2.metric(
    "Deadline in",
    common.countdown(deadline),
    help=deadline.strftime("%a %d %b %H:%M UTC") if deadline else None,
)
gen = pd.Timestamp(meta["generated_at"])
c3.metric("Forecast updated", gen.strftime("%d %b %H:%M"), help="UTC")
c4.metric("Data source", info["source"])

st.subheader("Your team this week")
team_id = st.session_state.get("team_id") or common.SETTINGS.team_id
plan = common.output(f"plan_{team_id}.json") if team_id else None
if plan and plan.get("weeks"):
    wk = plan["weeks"][0]
    moves = (
        ", ".join(
            f"{o['name']} → {i['name']}"
            for o, i in zip(wk["transfers_out"], wk["transfers_in"], strict=False)
        )
        or "Roll the transfer"
    )
    a, b, c = st.columns([2, 1, 1])
    a.markdown(f"**Transfers:** {moves}" + (f"  \n**Hits:** −{4 * wk['hits']}" if wk["hits"] else ""))
    b.metric("Captain", wk["captain"]["name"])
    c.metric(f"GW{wk['gw']} xPts", f"{wk['xpts']:.1f}")
    st.caption(
        f"From the scheduled plan for team {team_id} ({plan['state']['name']}). "
        "Open **My team** to re-plan with your latest changes."
    )
else:
    st.info(
        "Open **My team**, enter your FPL team ID and run the planner. Set `FPL_TEAM_ID` for the "
        "scheduled job to precompute it."
    )

st.subheader(f"Top projected players · GW{meta['next_gw']}")
proj = common.projections()
top = proj[proj["gw"] == meta["next_gw"]].nlargest(20, "xpts")
st.dataframe(
    top[
        [
            "name",
            "team_short",
            "position",
            "now_cost",
            "fixtures",
            "xpts",
            "xmins",
            "e_goals",
            "e_assists",
            "p_cs",
        ]
    ].assign(now_cost=lambda d: d["now_cost"] / 10, p_cs=lambda d: d["p_cs"] * 100),
    hide_index=True,
    width="stretch",
    column_config={
        "name": "Player",
        "team_short": "Team",
        "position": "Pos",
        "now_cost": st.column_config.NumberColumn("Price", format="£%.1fm"),
        "fixtures": "Fixture",
        "xpts": st.column_config.NumberColumn("xPts", format="%.2f"),
        "xmins": st.column_config.NumberColumn("xMins", format="%.0f"),
        "e_goals": st.column_config.NumberColumn("xGoals", format="%.2f"),
        "e_assists": st.column_config.NumberColumn("xAssists", format="%.2f"),
        "p_cs": st.column_config.NumberColumn("CS %", format="%.0f%%"),
    },
)

with st.expander("Refresh data now"):
    st.write("Pulls fresh FPL data and odds, re-runs the forecast and best squads (about a minute).")
    if st.button("Refresh", type="primary"):
        from midweek_merchant import service
        from midweek_merchant.data.ingest import ingest
        from midweek_merchant.forecast import run_forecast

        with st.spinner("Ingesting…"):
            ingest(common.SETTINGS, history_refresh=False)
        with st.spinner("Forecasting…"):
            run_forecast(common.SETTINGS)
        with st.spinner("Optimising best squads…"):
            service.save_best_squads(common.SETTINGS, service.best_squads(common.SETTINGS))
        common.clear_caches()
        st.success("Updated.")
        st.rerun()
