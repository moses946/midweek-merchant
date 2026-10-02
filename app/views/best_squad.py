import streamlit as st

from components import common
from components.pitch import render_week

common.page_setup("Best squad")
st.caption(
    "The best possible squad for each gameweek within the budget (what a Free Hit would pick), "
    "and the best squad to build now and manage with one free transfer a week (a Wildcard draft)."
)

data = common.output("best_squads.json")
budget = st.slider("Budget (£m)", 80.0, 105.0, float(data["budget"]) if data else 100.0, 0.5)
stale = data is None or abs(budget - data["budget"]) > 1e-6
if stale and (data is None or st.button("Optimise for this budget", type="primary")):
    from midweek_merchant import service

    with st.spinner("Optimising…"):
        data = service.best_squads(common.SETTINGS, common.projections(), budget=int(round(budget * 10)))

tab_gw, tab_wc = st.tabs(["Best squad per gameweek", "Wildcard draft"])
with tab_gw:
    gws = sorted(int(g) for g in data["per_gw"])
    gw = st.radio("Gameweek", gws, horizontal=True, format_func=lambda g: f"GW{g}")
    wk = data["per_gw"][str(gw)] if str(gw) in data["per_gw"] else data["per_gw"][gw]
    a, b, c = st.columns(3)
    a.metric("Expected points", f"{wk['xpts']:.1f}")
    b.metric("Captain", wk["captain"]["name"])
    cost = sum(p["price"] for p in wk["lineup"] + wk["bench"])
    c.metric("Squad cost", f"£{cost:.1f}m")
    render_week(wk)

with tab_wc:
    wc = data["wildcard"]
    st.metric("Expected points over the horizon", f"{wc['total_xpts']:.1f}")
    first = wc["weeks"][0]
    render_week(first, title=f"Squad for GW{first['gw']}")
    st.markdown("**Planned moves afterwards**")
    for w in wc["weeks"][1:]:
        moves = (
            ", ".join(
                f"{o['name']} → {i['name']}"
                for o, i in zip(w["transfers_out"], w["transfers_in"], strict=False)
            )
            or "roll transfer"
        )
        st.write(f"GW{w['gw']}: {moves} · captain {w['captain']['name']} · {w['xpts']:.1f} xPts")
