import json

import pandas as pd
import streamlit as st

from components import common
from components.pitch import render_week
from midweek_merchant import service
from midweek_merchant.forecast import load_rules
from midweek_merchant.team.reconstruct import TeamState, apply_overrides, validate_squad

common.page_setup("My team")
proj_base = common.projections()
players = common.table("players")
info = proj_base.drop_duplicates("element").set_index("element")
labels = {int(e): common.player_label(r) for e, r in info.iterrows()}
next_gw = int(proj_base["gw"].min())
CHIP_NAMES = {"wildcard": "Wildcard", "freehit": "Free Hit", "bboost": "Bench Boost", "3xc": "Triple Captain"}

# ------------------------------------------------------------------ load team
c1, c2 = st.columns([3, 1])
default_id = st.session_state.get("team_id") or common.SETTINGS.team_id or 0
team_id = c1.number_input(
    "FPL team ID",
    min_value=0,
    value=int(default_id),
    step=1,
    help="The number in your FPL points-page URL: /entry/<ID>/event/…",
)
if c2.button("Load team", type="primary", width="stretch") and team_id:
    with st.spinner("Rebuilding your squad from FPL…"):
        try:
            st.session_state.team_state = service.team_state(
                common.SETTINGS, int(team_id), overrides={}
            ).to_dict()
            st.session_state.team_id = int(team_id)
            st.session_state.pop("plan_result", None)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not load team {team_id}: {exc}")

if "team_state" not in st.session_state:
    st.info(
        "Enter your team ID and press **Load team**. Your squad, selling prices, bank, free transfers "
        "and remaining chips are rebuilt from public FPL data; no login needed."
    )
    st.stop()

base_state = TeamState.from_dict(st.session_state.team_state)

# ------------------------------------------------------------------ corrections
with st.expander("Corrections and transfers already made this week", expanded=False):
    st.caption(
        "Transfers you have already made for the upcoming deadline are not public yet. Add them here, "
        "and correct bank/free transfers/chips if needed."
    )
    squad_ids = [p.element for p in base_state.squad]
    pend = st.session_state.setdefault("pending", [])
    pc1, pc2, pc3 = st.columns([2, 2, 1])
    out_el = pc1.selectbox("Sold", squad_ids, format_func=lambda e: labels.get(e, str(e)), key="p_out")
    in_el = pc2.selectbox(
        "Bought", sorted(labels, key=lambda e: labels[e]), format_func=lambda e: labels[e], key="p_in"
    )
    if pc3.button("Add transfer", width="stretch"):
        pend.append({"out": int(out_el), "in": int(in_el)})
    for k, t in enumerate(pend):
        a, b = st.columns([5, 1])
        a.write(f"{labels.get(t['out'])} → {labels.get(t['in'])}")
        if b.button("Remove", key=f"rm{k}"):
            pend.pop(k)
            st.rerun()
    o1, o2 = st.columns(2)
    bank_ov = o1.number_input("Bank (£m)", 0.0, 100.0, base_state.bank / 10, 0.1)
    ft_ov = o2.number_input("Free transfers", 0, 5, base_state.free_transfers, 1)
    st.markdown("**Chips still available**")
    chip_cols = st.columns(4)
    chips_ov: dict[str, list[int]] = {}
    for col, (chip, label) in zip(chip_cols, CHIP_NAMES.items(), strict=True):
        halves = []
        for half in (1, 2):
            if col.checkbox(
                f"{label} ({'GW1–19' if half == 1 else 'GW20–38'})",
                value=half in base_state.chips_available.get(chip, []),
                key=f"chip_{chip}_{half}",
            ):
                halves.append(half)
        if halves:
            chips_ov[chip] = halves

overrides = {"pending": pend, "chips_available": chips_ov}
if abs(bank_ov * 10 - base_state.bank) > 0.5 or pend:
    overrides["bank"] = int(round(bank_ov * 10)) if abs(bank_ov * 10 - base_state.bank) > 0.5 else None
if overrides.get("bank") is None:
    overrides.pop("bank", None)
if ft_ov != base_state.free_transfers:
    overrides["free_transfers"] = int(ft_ov)
state = apply_overrides(TeamState.from_dict(st.session_state.team_state), players, overrides)

# ------------------------------------------------------------------ state summary
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Team", state.name or "—")
m2.metric("Bank", f"£{state.bank / 10:.1f}m")
m3.metric("Free transfers", state.free_transfers)
m4.metric("Squad value", f"£{state.squad_value / 10:.1f}m")
m5.metric("Overall rank", f"{state.overall_rank:,}" if state.overall_rank else "—")
avail = [f"{CHIP_NAMES[c]} ({'/'.join('H' + str(h) for h in hs)})" for c, hs in state.chips_available.items()]
st.caption("Chips available: " + (", ".join(avail) if avail else "none"))
for n in state.notes:
    st.caption(f"Note: {n}")
errs = validate_squad(state, load_rules(common.SETTINGS))
for e in errs:
    st.error(e)

sq = pd.DataFrame([vars(p) for p in state.squad])
nxt = proj_base[proj_base["gw"] == next_gw].set_index("element")
sq["xpts_next"] = sq["element"].map(nxt["xpts"])
sq["fixture"] = sq["element"].map(nxt["fixtures"])
sq["horizon_xpts"] = sq["element"].map(proj_base.groupby("element")["xpts"].sum())
sq["status"] = sq["element"].map(info["news"]).fillna("")
order = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
sq = sq.sort_values(["position", "xpts_next"], key=lambda s: s.map(order) if s.name == "position" else -s)
with st.expander("Current squad", expanded=False):
    st.dataframe(
        sq[
            [
                "name",
                "position",
                "team",
                "fixture",
                "xpts_next",
                "horizon_xpts",
                "purchase_price",
                "now_cost",
                "selling_price",
                "status",
            ]
        ].assign(
            purchase_price=lambda d: d["purchase_price"] / 10,
            now_cost=lambda d: d["now_cost"] / 10,
            selling_price=lambda d: d["selling_price"] / 10,
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "xpts_next": st.column_config.NumberColumn(f"xPts GW{next_gw}", format="%.2f"),
            "horizon_xpts": st.column_config.NumberColumn("xPts horizon", format="%.1f"),
            "purchase_price": st.column_config.NumberColumn("Bought", format="£%.1f"),
            "now_cost": st.column_config.NumberColumn("Now", format="£%.1f"),
            "selling_price": st.column_config.NumberColumn("Sell", format="£%.1f"),
        },
    )

# ------------------------------------------------------------------ planner settings
with st.expander("Planner settings", expanded=True):
    s1, s2, s3, s4 = st.columns(4)
    horizon = s1.slider("Horizon (GWs)", 1, min(8, len(proj_base["gw"].unique())), 6)
    decay = s2.slider(
        "Future-week weight (decay)",
        0.6,
        1.0,
        common.SETTINGS.optimizer.decay,
        0.01,
        help="How much less a point next week is worth than one this week.",
    )
    max_hits = s3.slider("Max hits per GW", 0, 3, common.SETTINGS.optimizer.max_hits_per_gw)
    allow_chips = s4.toggle(
        "Let the solver play chips",
        value=False,
        help="Slower. Or force a chip below, or use the Chips page to compare timings.",
    )
    t1, t2, t3 = st.columns(3)
    gw_opts = sorted(proj_base["gw"].unique())[:horizon]
    force_chip = t1.selectbox(
        "Force a chip",
        ["none", *state.chips_available.keys()],
        format_func=lambda c: CHIP_NAMES.get(c, "None"),
    )
    force_gw = (
        t1.selectbox("…in gameweek", gw_opts, format_func=lambda g: f"GW{g}")
        if force_chip != "none"
        else None
    )
    locks = t2.multiselect(
        "Keep / buy (lock)", sorted(labels, key=lambda e: labels[e]), format_func=lambda e: labels[e]
    )
    bans = t3.multiselect(
        "Avoid (ban)", sorted(labels, key=lambda e: labels[e]), format_func=lambda e: labels[e]
    )
    roll = t2.toggle(f"No transfers in GW{next_gw}")
    st.markdown("**Availability overrides** (news the model has not seen yet)")
    ov_players = st.multiselect(
        "Players", sorted(labels, key=lambda e: labels[e]), format_func=lambda e: labels[e], key="ov_players"
    )
    minutes_ov = {}
    if ov_players:
        cols = st.columns(min(4, len(ov_players)))
        for k, e in enumerate(ov_players):
            minutes_ov[int(e)] = {
                "p_start": cols[k % len(cols)].slider(
                    f"P(start) {info.loc[e, 'name']}", 0.0, 1.0, 0.0, 0.05, key=f"ps{e}"
                )
            }


@st.cache_data(show_spinner=False, max_entries=8)
def projections_with(minutes_json: str, generated_at: str) -> pd.DataFrame:
    from midweek_merchant.forecast import run_forecast

    fc = run_forecast(
        common.SETTINGS,
        minutes_overrides={int(k): v for k, v in json.loads(minutes_json).items()},
        save=False,
    )
    return fc.projections


@st.cache_data(show_spinner=False, max_entries=16)
def run_plan(state_json: str, opts_json: str, minutes_json: str, generated_at: str, k_alt: int) -> dict:
    from midweek_merchant.optimize import planner
    from midweek_merchant.optimize.milp import PlanOptions

    st_ = TeamState.from_dict(json.loads(state_json))
    o = json.loads(opts_json)
    proj = projections_with(minutes_json, generated_at) if json.loads(minutes_json) else common.projections()
    rules = load_rules(common.SETTINGS)
    opts = PlanOptions.from_config(
        common.SETTINGS.optimizer,
        horizon=o["horizon"],
        decay=o["decay"],
        max_hits_per_gw=o["max_hits"],
        allow_chips=o["allow_chips"],
        forced_chips={int(k): v for k, v in o["forced"].items()},
        locked=set(o["locks"]),
        banned=set(o["bans"]),
        no_transfer_gws=set(o["roll"]),
        last_gw_chip=service.last_chip(st_),
    )
    plans = (
        planner.alternatives(proj, st_, rules, opts, k=k_alt)
        if k_alt > 1
        else [planner.plan_transfers(proj, st_, rules, opts)]
    )
    return {
        "plans": [
            {"status": p.status, "total": p.total_xpts, "weeks": service.plan_table(p, proj)}
            for p in plans
            if p.weeks
        ]
    }


opts_payload = {
    "horizon": horizon,
    "decay": decay,
    "max_hits": max_hits,
    "allow_chips": allow_chips,
    "forced": {str(force_gw): force_chip} if force_gw else {},
    "locks": [int(x) for x in locks],
    "bans": [int(x) for x in bans],
    "roll": [next_gw] if roll else [],
}
b1, b2 = st.columns([1, 1])
go_plan = b1.button("Plan my transfers", type="primary", width="stretch", disabled=bool(errs))
go_alt = b2.button("Plan + 3 alternatives", width="stretch", disabled=bool(errs))
if go_plan or go_alt:
    with st.spinner("Optimising (usually 5–30 s)…"):
        st.session_state.plan_result = run_plan(
            json.dumps(state.to_dict(), sort_keys=True),
            json.dumps(opts_payload, sort_keys=True),
            json.dumps(minutes_ov, sort_keys=True),
            common.ensure_data()["meta"]["generated_at"],
            4 if go_alt else 1,
        )

res = st.session_state.get("plan_result")
if not res:
    st.stop()
if not res["plans"]:
    st.error("No feasible plan found. Loosen locks/bans or check the squad corrections.")
    st.stop()

plans = res["plans"]
best = plans[0]
st.subheader("Recommended plan")
first = best["weeks"][0]
k1, k2, k3, k4 = st.columns(4)
k1.metric(f"GW{first['gw']} expected points", f"{first['xpts']:.1f}")
k2.metric("Horizon expected points", f"{best['total']:.1f}")
k3.metric("Captain", first["captain"]["name"], help=f"Vice: {first['vice']['name']}")
k4.metric("Chip", CHIP_NAMES.get(first["chip"], "None"))

tabs = st.tabs([f"GW{w['gw']}" + (f" · {CHIP_NAMES[w['chip']]}" if w["chip"] else "") for w in best["weeks"]])
for tab, w in zip(tabs, best["weeks"], strict=True):
    with tab:
        moves = list(zip(w["transfers_out"], w["transfers_in"], strict=False))
        if w["chip"] == "freehit":
            st.write("Free Hit: the whole squad below is temporary and reverts next week.")
        elif moves:
            for o, i in moves:
                st.write(
                    f"**Out** {o['name']} ({o['team']}, £{o['price']:.1f}m, {o['xpts']:.1f} xPts) → "
                    f"**In** {i['name']} ({i['team']}, £{i['price']:.1f}m, {i['xpts']:.1f} xPts)"
                )
        else:
            st.write("No transfer: roll it.")
        st.caption(
            f"Free transfers available: {w['free_transfers']} · hits: {w['hits']} "
            f"(−{4 * w['hits']}) · bank after: £{w['bank']:.1f}m · expected points: {w['xpts']:.1f}"
        )
        render_week(w, highlight={p["element"] for p in w["transfers_in"]})

if len(plans) > 1:
    st.subheader("Alternatives")
    rows = []
    for k, p in enumerate(plans):
        w0 = p["weeks"][0]
        moves = (
            ", ".join(
                f"{o['name']} → {i['name']}"
                for o, i in zip(w0["transfers_out"], w0["transfers_in"], strict=False)
            )
            or "roll"
        )
        rows.append(
            {
                "option": k + 1,
                "this week": moves,
                "captain": w0["captain"]["name"],
                f"GW{w0['gw']} xPts": round(w0["xpts"], 2),
                "horizon xPts": round(p["total"], 1),
                "vs best": round(p["total"] - best["total"], 1),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(
        "Plans within ~1 xPt of each other are effectively equal; prefer the one that keeps options open."
    )
