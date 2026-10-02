import pandas as pd
import streamlit as st

from components import charts, common
from components.pitch import render_week

common.page_setup("Hindcast")
st.caption(
    "The honest test: for a gameweek that has already been played, the model picks its best XI, captain and "
    "bench using only what was known before that deadline (earlier results, opening odds, injury news and "
    "prices from the snapshot taken after the previous gameweek). Then the real points are revealed. FPL's "
    "own pre-deadline predictions and recent form pick under the same rules (£100m, max 3 per club) for "
    "comparison, alongside the best XI that was possible in hindsight."
)

SEASONS = [common.SETTINGS.season, "2025-26"]
LABEL = {"model": "Model", "fpl_ep": "FPL ep", "form": "Form (last 4)", "hindsight": "Hindsight best"}
season = st.radio("Season", SEASONS, horizontal=True)
data = common.output(f"hindcast_{season}.json")
if data is None or not data.get("gameweeks"):
    st.info(
        "No hindcast for this season yet. Run `mm hindcast --season "
        f"{season} --gws 2-38` or compute it here (about 3 seconds per gameweek)."
    )
    if st.button("Compute now", type="primary"):
        from midweek_merchant.backtest.hindcast import hindcast_season
        from midweek_merchant.data.store import read_table

        pm = read_table(common.SETTINGS, "player_matches")
        last = int(pm.loc[pm["season"] == season, "gw"].max())
        with st.spinner("Picking blind and scoring every gameweek…"):
            hindcast_season(common.SETTINGS, season, list(range(2, last + 1)))
        common.clear_caches()
        st.rerun()
    st.stop()

gws = data["gameweeks"]
summary = pd.DataFrame(data["summary"]).dropna(axis=1, how="all")  # e.g. no manager averages for 2025-26
st.subheader(f"Season so far · {len(gws)} gameweeks")
st.dataframe(
    summary,
    hide_index=True,
    width="stretch",
    column_config={
        "pick": "Picked by",
        "gameweeks": "GWs",
        "mean_points": st.column_config.NumberColumn("Avg points / GW", format="%.1f"),
        "total_points": st.column_config.NumberColumn("Total", format="%.0f"),
        "mean_captain_points": st.column_config.NumberColumn("Avg captain pts", format="%.1f"),
        "beats_average_manager": st.column_config.NumberColumn("Beats avg manager", format="percent"),
        "beats_fpl_ep_pick": st.column_config.NumberColumn("Beats FPL-ep pick", format="percent"),
        "share_of_hindsight": st.column_config.NumberColumn("Share of best possible", format="percent"),
    },
)
rows = []
for r in gws:
    for k in ("model", "fpl_ep", "form"):
        if k in r["scores"]:
            rows.append({"gw": r["gw"], "pick": LABEL[k], "points": r["scores"][k]})
    if r.get("average_manager") is not None:
        rows.append({"gw": r["gw"], "pick": "Average manager", "points": r["average_manager"]})
trend = pd.DataFrame(rows)
st.plotly_chart(
    charts.lines(
        trend,
        "gw",
        "points",
        "pick",
        "Actual points of each blind pick by gameweek",
        order=["Model", "FPL ep", "Form (last 4)", "Average manager"],
        highlight="Model",
        height=380,
    ),
    width="stretch",
    theme=None,
)
st.caption(
    "Every pick is a fresh Free-Hit-style squad each week, so the average manager (who carries a squad "
    "and pays for transfers) is a looser comparison than FPL ep and form, which play by the same rules."
)

st.subheader("One gameweek in detail")
gw = st.select_slider(
    "Gameweek", options=[r["gw"] for r in gws], value=gws[-1]["gw"], format_func=lambda g: f"GW{g}"
)
r = next(x for x in gws if x["gw"] == gw)
cols = st.columns(5)
for col, key in zip(cols, ("model", "fpl_ep", "form", "hindsight"), strict=False):
    if key in r["scores"]:
        pick = r["picks"][key]
        col.metric(
            LABEL[key],
            f"{r['scores'][key]:.0f}",
            help=f"Captain {pick['score']['captain']} ({pick['score']['captain_points']:.0f} pts); "
            f"predicted {pick['predicted']:.1f}",
        )
cols[4].metric(
    "Average manager",
    f"{r['average_manager']:.0f}" if r.get("average_manager") is not None else "—",
    help=f"Highest: {r['highest_manager']:.0f}" if r.get("highest_manager") else None,
)
st.caption(
    f"Deadline {r['deadline'][:16].replace('T', ' ')} UTC · team news snapshot: "
    f"{'yes' if r['snapshot_used'] else 'no (everyone assumed available)'}. "
    "Points include the captain (vice if the captain did not play) and automatic bench substitutions."
)
left, right = st.columns(2)
with left:
    render_week(r["picks"]["model"], title=f"Model's pick, made before the GW{gw} deadline")
with right:
    render_week(r["picks"]["hindsight"], title="Best XI possible in hindsight")
with st.expander("FPL ep and form picks"):
    a, b = st.columns(2)
    for col, key in ((a, "fpl_ep"), (b, "form")):
        if key in r["picks"]:
            with col:
                render_week(r["picks"][key], title=f"{LABEL[key]} pick")

# ------------------------------------------------------------------ your own team, blind
st.subheader("Your team, picked blind")
team_id = (st.session_state.get("team_state") or {}).get("entry_id") or common.SETTINGS.team_id
if season != common.SETTINGS.season or not team_id:
    st.caption("Load your team on **My team** (or set `team_id`) to replay your own squad for this season.")
    st.stop()
st.caption(
    "Same test, starting from the squad, bank and free transfers you actually had at that deadline. Every "
    "option is picked from the model's pre-deadline predictions only, then scored on the real points "
    "(captain, vice and automatic substitutions). The hindsight rows are for reference."
)
gw_t = st.selectbox(
    "Gameweek", [r["gw"] for r in gws][::-1], format_func=lambda g: f"GW{g}", key="team_hindcast_gw"
)
yt = common.output(f"hindcast_team_{team_id}_gw{gw_t}.json")
if yt is None:
    if st.button(f"Replay my GW{gw_t} (about 1 minute)", type="primary"):
        from midweek_merchant.backtest.hindcast import hindcast_team

        with st.spinner("Rebuilding your squad at the deadline and picking blind…"):
            hindcast_team(common.SETTINGS, int(team_id), season, int(gw_t))
        common.clear_caches()
        st.rerun()
    st.stop()
st_ = yt["state"]
st.write(
    f"**{yt['team']}** at the GW{gw_t} deadline: bank £{st_['bank']:.1f}m, {st_['free_transfers']} free "
    f"transfer(s), squad value £{st_['squad_value']:.1f}m. FPL scored you **{yt['fpl_points']}**."
)
ladder = pd.DataFrame(yt["rows"])
st.dataframe(
    ladder[["label", "moves", "captain", "predicted", "actual"]],
    hide_index=True,
    width="stretch",
    column_config={
        "label": st.column_config.TextColumn("Option", width="medium"),
        "moves": st.column_config.TextColumn("Transfers", width="medium"),
        "captain": "Captain",
        "predicted": st.column_config.NumberColumn("Predicted", format="%.1f"),
        "actual": st.column_config.NumberColumn("Actual", format="%.0f"),
    },
)
left, right = st.columns(2)
with left:
    render_week(yt["weeks"]["ft"], title="Model's pick with your free transfer")
with right:
    render_week(yt["weeks"]["actual"], title="What you fielded")
