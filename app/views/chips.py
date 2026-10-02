import pandas as pd
import streamlit as st

from components import charts, common, pitch
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


def show_timing(rep: dict) -> None:
    st.metric("No-chip plan, expected points over the horizon", f"{rep['baseline_xpts']:.1f}")
    ex = pd.DataFrame(rep["exact"])
    if len(ex):
        ex["chip_name"] = ex["chip"].map(NAMES)
        ex["option_value"] = ex["chip"].map(rep["option_values"])
        ex["net"] = ex["gain"] - ex["option_value"]
        best = ex.sort_values("gain", ascending=False).groupby("chip").head(1)
        cols = st.columns(len(best))
        for col, r in zip(cols, best.itertuples(), strict=True):
            verdict = (
                "play now" if r.gw == min(ex["gw"]) and r.net > 0 else ("worth it" if r.net > 0 else "hold")
            )
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


if rep := st.session_state.get("chip_report"):
    show_timing(rep)

# ------------------------------------------------------------------ chase a big week
st.subheader("Chase a big week")
st.caption(
    "Expected points win seasons, but a 100-point week is a tail event: it needs a Bench Boost or "
    "Triple Captain, a squad built for that week, and a captain picked for upside. Each chip schedule "
    "is solved for expected points over 8 gameweeks (so later weeks are not wrecked), then scored on "
    "correlated simulations. In every week the captain is re-chosen to maximise the chance of reaching the target."
)
c1, c2 = st.columns(2)
target = c1.number_input("Target points in one gameweek", min_value=50, max_value=200, value=100, step=5)
n_weeks = c2.slider("Within the next N gameweeks", 1, 6, 4)


@st.cache_data(show_spinner=False, max_entries=4)
def ceiling(state_json: str, target: float, weeks: int, generated_at: str) -> dict:
    import json

    return service.ceiling_report(common.SETTINGS, TeamState.from_dict(json.loads(state_json)), target, weeks)


saved = common.output(f"ceiling_{state.entry_id}.json") if state.entry_id else None
if saved and (saved["target"] != target or len(saved["target_gws"]) != n_weeks):
    saved = None
if st.button("Find the best shot (about 3–5 minutes)"):
    import json

    with st.spinner("Solving about 30 chip schedules and simulating 5,000 seasons…"):
        st.session_state.ceiling_report = ceiling(
            json.dumps(state.to_dict(), sort_keys=True),
            float(target),
            n_weeks,
            common.ensure_data()["meta"]["generated_at"],
        )
cr = st.session_state.get("ceiling_report") or saved
if cr and (cr["target"] != target or len(cr["target_gws"]) != n_weeks):
    cr = None
if cr:
    gws = cr["target_gws"]
    tab = pd.DataFrame(cr["table"])
    best, ref = tab.iloc[0], tab[tab["plan"] == cr["reference"]].iloc[0]
    m1, m2, m3 = st.columns(3)
    m1.metric(f"Best chance of {target:g}+ in GW{gws[0]}–{gws[-1]}", f"{best['p_any']:.1%}")
    m1.caption(best["label"])
    m2.metric("Best plan for expected points", f"{ref['p_any']:.1%}")
    m2.caption(ref["label"] if ref["plan"] != best["plan"] else "the same plan")
    m3.metric("Expected points given up", f"{best['cost_vs_best']:.1f}")
    m3.caption("over 8 gameweeks, counting the value of chips kept")
    show = tab[
        [
            "label",
            "p_any",
            "p_any_raw",
            *[f"p_gw{g}" for g in gws],
            "e_best_week",
            "p99_best_week",
            "e_total",
            "cost_vs_best",
        ]
    ]
    st.dataframe(
        show,
        hide_index=True,
        width="stretch",
        column_config={
            "label": st.column_config.TextColumn("Plan", width="large"),
            "p_any": st.column_config.NumberColumn(f"P(any {target:g}+)", format="percent"),
            "p_any_raw": st.column_config.NumberColumn("uncalibrated", format="percent"),
            **{f"p_gw{g}": st.column_config.NumberColumn(f"GW{g}", format="percent") for g in gws},
            "e_best_week": st.column_config.NumberColumn("E[best week]", format="%.1f"),
            "p99_best_week": st.column_config.NumberColumn("1-in-100 best week", format="%.0f"),
            "e_total": st.column_config.NumberColumn(f"E[GW{gws[0]}–{gws[-1]} total]", format="%.1f"),
            "cost_vs_best": st.column_config.NumberColumn("xPts cost (8 GWs)", format="%.1f"),
        },
    )
    cal = cr.get("calibration")
    if cal:
        f = cal["fitted"]
        st.caption(
            f"Tail calibration: the simulator's spread is scaled by k = {cr['scale']:g}, fitted by CRPS on "
            f"{cal['gameweeks']} blind hindcast gameweeks ({', '.join(cal['seasons'])}). With it, those weeks "
            f"expected {f['n80_expected']:.1f} scores of 80+ (observed {f['n80_observed']}) and "
            f"{f['n100_expected']:.1f} of 100+ (observed {f['n100_observed']}). Cost = expected points given up "
            "over 8 gameweeks versus the best expected-points plan tested, counting the value of chips kept."
        )
    plan = cr["plans"][str(int(best["plan"]))]
    st.markdown(f"**{plan['label']}**, week by week (captain chosen for the target)")
    weeks = [w for w in plan["weeks"] if "sim" in w]
    for t_, w in zip(st.tabs([f"GW{w['gw']}" for w in weeks]), weeks, strict=True):
        with t_:
            sim = w["sim"]
            chip = NAMES.get(w["chip"], "no chip") if w["chip"] else "no chip"
            moves = ", ".join(
                f"{o['name']} → {i['name']}"
                for o, i in zip(w["transfers_out"], w["transfers_in"], strict=False)
            )
            st.write(
                f"{chip} · simulated mean {sim['mean']:.1f} · P({target:g}+) {sim['p_target']:.1%} · "
                f"1-in-100 week {sim['p99']:.0f} · hits {w['hits']} · "
                + (f"transfers: {moves}" if moves else "no transfers")
            )
            pitch.render_week(w)
