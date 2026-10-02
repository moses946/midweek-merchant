import json

import pandas as pd
import streamlit as st

from components import charts, common
from midweek_merchant import service
from midweek_merchant.team.reconstruct import TeamState

common.page_setup("Mini-league")
st.caption(
    "Win your league, not just the gameweek. Rivals' squads are read from FPL; every candidate plan "
    "is scored against them on the same correlated simulations, so shared players cancel out and "
    "differentials show their true risk and reward."
)

c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
league_id = c1.number_input(
    "Classic league ID",
    min_value=0,
    step=1,
    value=int(st.session_state.get("league_id") or common.SETTINGS.league_id or 0),
    help="From the league URL: /leagues/<ID>/standings/c",
)
team_id = c2.number_input(
    "Your team ID",
    min_value=0,
    step=1,
    value=int(st.session_state.get("team_id") or common.SETTINGS.team_id or 0),
)
horizon = c3.selectbox("Horizon", [1, 2, 3, 4, 5], index=2, help="Gameweeks simulated in detail")
n_sims = c4.selectbox("Simulations", [1000, 2000, 4000], index=1)


@st.cache_data(show_spinner=False, max_entries=8, ttl=1800)
def report(league_id: int, team_id: int, state_json: str | None, horizon: int, n_sims: int, gen: str) -> dict:
    my_state = TeamState.from_dict(json.loads(state_json)) if state_json else None
    return service.league_report(
        common.SETTINGS, league_id, team_id, my_state, horizon=horizon, n_sims=n_sims
    )


if st.button("Analyse league", type="primary", disabled=not (league_id and team_id)):
    st.session_state.league_id, st.session_state.team_id = int(league_id), int(team_id)
    ts = st.session_state.get("team_state")
    use_state = json.dumps(ts, sort_keys=True) if ts and ts.get("entry_id") == int(team_id) else None
    with st.spinner("Loading rivals, planning and simulating (~30–60 s)…"):
        try:
            st.session_state.league_report = report(
                int(league_id),
                int(team_id),
                use_state,
                horizon,
                n_sims,
                common.ensure_data()["meta"]["generated_at"],
            )
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))
rep = st.session_state.get("league_report")
if not rep:
    st.info("Enter your classic league ID and team ID, then press **Analyse league**.")
    st.stop()

st.subheader(f"{rep['league']['name']} · GW{rep['gws'][0]}–{rep['gws'][-1]}")
z = rep["z"]
stance = "Chasing" if z <= -0.75 else ("Protecting a lead" if z >= 0.75 else "Close race")
a, b = st.columns([1, 3])
a.metric("Stance", stance, help=f"Gap to the leader/second place in units of outcome spread: z = {z:+.2f}")
b.info(rep["advice"])

stand = pd.DataFrame(rep["standings"])
s1, s2 = st.columns([3, 2])
s1.dataframe(
    stand.drop(columns=["is_me"]),
    hide_index=True,
    width="stretch",
    column_config={
        "manager": "Manager",
        "now": "Points now",
        "projected": st.column_config.NumberColumn("Projected", format="%.0f"),
        "p_lead_after_horizon": st.column_config.NumberColumn("P(lead after horizon)", format="percent"),
        "p_win_league": st.column_config.NumberColumn("P(win league)", format="percent"),
    },
)
s2.plotly_chart(
    charts.bar(
        stand.assign(p=stand["p_win_league"] * 100),
        "manager",
        "p",
        "Chance of winning the league (%)",
        height=320,
    ),
    width="stretch",
    theme=None,
)

st.subheader("Your options, ranked by chance of winning the league")
plans = pd.DataFrame(rep["plans"]).sort_values("p_first_season", ascending=False)
st.dataframe(
    plans,
    hide_index=True,
    width="stretch",
    column_config={
        "option": "#",
        "type": "Strategy",
        "this_week": "This week",
        "hits": "Hits",
        "captain": "Captain",
        "chip": "Chip",
        "xpts_horizon": st.column_config.NumberColumn("xPts (horizon)", format="%.1f"),
        "mean_rank_horizon": st.column_config.NumberColumn("Mean rank", format="%.2f"),
        "p_first_horizon": st.column_config.NumberColumn("P(1st after horizon)", format="percent"),
        "p_first_season": st.column_config.NumberColumn("P(win league)", format="percent"),
    },
)
best = rep["plans"][rep["best_plan"]]
st.success(
    f"Recommended: **{best['type']}** · {best['this_week']} · captain {best['captain']} "
    f"(P(win league) {best['p_first_season']:.1%})."
)
st.caption(
    "Differences under ~1 percentage point are within simulation noise; prefer the higher-xPts option then."
)

t1, t2, t3, t4 = st.tabs(["Effective ownership", "Captaincy", "Head to head", "Rivals' chips"])
with t1:
    eo = pd.DataFrame(rep["eo"])
    st.dataframe(
        eo.drop(columns=["element"]),
        hide_index=True,
        width="stretch",
        column_config={
            "xpts": st.column_config.NumberColumn("xPts", format="%.2f"),
            "league_eo": st.column_config.NumberColumn("League EO %", format="%.0f"),
            "my_mult": "Your multiplier",
            "net_exposure": st.column_config.NumberColumn("Net exposure %", format="%+.0f"),
            "role": "Role",
        },
    )
    st.caption(
        "EO counts each rival starter once and their captain twice. Net exposure > 0 means you gain "
        "relative to the league when that player scores; < 0 means you lose ground."
    )
with t2:
    st.dataframe(
        pd.DataFrame(rep["captains"]),
        hide_index=True,
        width="stretch",
        column_config={
            "my_gw_xpts": st.column_config.NumberColumn("Your GW xPts", format="%.1f"),
            "league_eo": st.column_config.NumberColumn("League EO %", format="%.0f"),
            "p_beat_rival_avg": st.column_config.NumberColumn("P(beat a rival this GW)", format="percent"),
            "p_top_score_gw": st.column_config.NumberColumn("P(top league score this GW)", format="percent"),
            "p_lead_after_gw": st.column_config.NumberColumn("P(lead after GW)", format="percent"),
        },
    )
with t3:
    st.dataframe(
        pd.DataFrame(rep["head_to_head"]),
        hide_index=True,
        width="stretch",
        column_config={
            "p_outscore_this_gw": st.column_config.NumberColumn("P(outscore this GW)", format="percent"),
            "exp_margin_this_gw": st.column_config.NumberColumn("Expected margin", format="%+.1f"),
        },
    )
with t4:
    names = {"wildcard": "WC", "freehit": "FH", "bboost": "BB", "3xc": "TC"}
    rows = [
        {
            "manager": r["manager"],
            "bank": r["bank"],
            "FTs": r["free_transfers"],
            "chips left": ", ".join(f"{names[c]}×{len(h)}" for c, h in r["chips_left"].items()),
        }
        for r in rep["rival_chips"]
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(
        "Rivals with chips in hand can swing a gameweek: plan cover before likely Bench Boost / "
        "Triple Captain weeks (doubles)."
    )
