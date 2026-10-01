import pandas as pd
import streamlit as st

from components import charts, common
from midweek_merchant import service
from midweek_merchant.team.reconstruct import TeamState

common.page_setup("Chips")
st.caption(
    "When to play Wildcard, Free Hit, Bench Boost and Triple Captain. 2026/27 has two of each: "
    "one usable GW1–19 (expires at the GW19 deadline) and one GW20–38. One chip per gameweek, "
    "and no Free Hit in consecutive gameweeks."
)
NAMES = {"wildcard": "Wildcard", "freehit": "Free Hit", "bboost": "Bench Boost", "3xc": "Triple Captain"}

# ------------------------------------------------------------------ fixture calendar (blanks / doubles)
st.subheader("Blank and double gameweeks")
fx = common.table("fixtures")
teams = common.table("teams")
remaining = fx[~fx["finished"]]
counts = pd.concat(
    [
        remaining[["gw", "home"]].rename(columns={"home": "team"}),
        remaining[["gw", "away"]].rename(columns={"away": "team"}),
    ]
)
per = counts.dropna(subset=["gw"]).groupby(["gw", "team"]).size().unstack(fill_value=0)
per = per.reindex(columns=teams["team"], fill_value=0)
cal = pd.DataFrame({"blank teams": (per == 0).sum(axis=1), "double teams": (per >= 2).sum(axis=1)})
special = cal[(cal["blank teams"] > 0) | (cal["double teams"] > 0)]
unscheduled = int(remaining["gw"].isna().sum())
if len(special):
    st.dataframe(special.reset_index().rename(columns={"gw": "Gameweek"}), hide_index=True)
else:
    st.write("No blank or double gameweeks are scheduled yet.")
st.caption(
    f"{unscheduled} fixture(s) have no gameweek yet (postponed or cup-affected); they usually become "
    "doubles. Expected this season: blanks around GW30 (League Cup final) and GW33 (FA Cup semi-finals), "
    "doubles around GW32 and GW35–36. Projections cover the next 8 gameweeks only."
)

# ------------------------------------------------------------------ chip evaluation for my team
st.subheader("Chip timing for your team")
if "team_state" not in st.session_state:
    st.info("Load your team on **My team** first.")
    st.stop()
state = TeamState.from_dict(st.session_state.team_state)
avail = state.chips_available
if not avail:
    st.write("You have no chips left in the current windows.")
    st.stop()
st.write(
    "Available: "
    + ", ".join(
        f"{NAMES[c]} ({'/'.join('GW1–19' if h == 1 else 'GW20–38' for h in hs)})" for c, hs in avail.items()
    )
)
horizon = st.slider("Horizon (GWs)", 3, 8, 6)
exact = st.toggle("Exact evaluation (re-solve the full plan for every chip × gameweek, ~30–60 s)", value=True)


@st.cache_data(show_spinner=False, max_entries=8)
def report(state_json: str, horizon: int, exact: bool, generated_at: str) -> dict:
    import json

    return service.chip_report(common.SETTINGS, TeamState.from_dict(json.loads(state_json)), horizon, exact)


if st.button("Evaluate chips", type="primary"):
    import json

    with st.spinner("Solving…"):
        st.session_state.chip_report = report(
            json.dumps(state.to_dict(), sort_keys=True),
            horizon,
            exact,
            common.ensure_data()["meta"]["generated_at"],
        )
rep = st.session_state.get("chip_report")
if not rep:
    st.stop()

st.metric("No-chip plan, expected points over the horizon", f"{rep['baseline_xpts']:.1f}")
ex = pd.DataFrame(rep["exact"])
if len(ex):
    ex["chip_name"] = ex["chip"].map(NAMES)
    ex["option_value"] = ex["chip"].map(rep["option_values"])
    ex["net"] = ex["gain"] - ex["option_value"]
    best = ex.sort_values("gain", ascending=False).groupby("chip").head(1)
    cols = st.columns(len(best))
    for col, r in zip(cols, best.itertuples(), strict=True):
        verdict = "play now" if r.gw == min(ex["gw"]) and r.net > 0 else ("worth it" if r.net > 0 else "hold")
        col.metric(f"Best {r.chip_name}", f"GW{r.gw}", f"{r.gain:+.1f} xPts · {verdict}")
    for chip, g in ex.groupby("chip"):
        st.plotly_chart(
            charts.bar(
                g.sort_values("gw").assign(gw_label=lambda d: "GW" + d["gw"].astype(str)),
                "gw_label",
                "gain",
                f"{NAMES[chip]}: extra expected points vs no chip",
                horizontal=False,
                height=260,
            ),
            width="stretch",
            theme=None,
        )
    st.caption(
        "Gains include knock-on effects on later transfers. Holding a chip has value too "
        f"(assumed: {', '.join(f'{NAMES[c]} {v:g}' for c, v in rep['option_values'].items())} points); "
        "play it when the gain clearly beats that, or before it expires at GW19."
    )
q = pd.DataFrame(rep["quick"]).rename(
    columns={
        "bboost": "Bench Boost (bench xPts)",
        "3xc": "Triple Captain (captain xPts)",
        "freehit": "Free Hit (gain vs planned XI)",
        "planned_xpts": "Planned",
    }
)
st.markdown("**Quick single-week chip values** (from the no-chip plan)")
for c in q.columns:
    if c != "gw":
        q[c] = q[c].map(lambda v: f"{v:.2f}" if pd.notna(v) else "—")
st.dataframe(q, hide_index=True, width="stretch")
st.caption("— means the chip is not available in that gameweek.")
