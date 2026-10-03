"""Property tests: every plan the optimiser returns must be a legal FPL plan."""

from collections import Counter

import numpy as np
import pandas as pd
import pytest

from midweek_merchant.optimize.milp import PlanOptions
from midweek_merchant.optimize.planner import best_squad_per_gw, plan_transfers
from midweek_merchant.rules import Rules, rules_from_bootstrap
from midweek_merchant.team.reconstruct import SquadPlayer, TeamState

RULES: Rules = rules_from_bootstrap(None)
GWS = [10, 11, 12, 13]
COUNTS = {"GKP": 6, "DEF": 16, "MID": 16, "FWD": 10}


def make_proj(seed: int = 1, gws: list[int] = GWS) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    el = 1
    for pos, n in COUNTS.items():
        for k in range(n):
            price = int(rng.integers(40, 75 if pos != "GKP" else 56))
            base = price / 15 + rng.normal(0, 0.6)
            for gw in gws:
                rows.append(
                    {
                        "element": el,
                        "gw": gw,
                        "position": pos,
                        "team": f"T{(el * 7 + k) % 10}",
                        "now_cost": price,
                        "xpts": max(0.0, base + rng.normal(0, 0.8)),
                        "xmins": 80.0,
                        "name": f"P{el}",
                        "team_short": f"T{(el * 7 + k) % 10}",
                        "fixtures": "X(H)",
                    }
                )
            el += 1
    return pd.DataFrame(rows)


def initial_state(proj: pd.DataFrame, chips: dict | None = None, ft: int = 1, bank: int = 20) -> TeamState:
    """A legal (cheap) starting squad from the synthetic universe."""
    info = proj.drop_duplicates("element").sort_values("now_cost")
    squad, clubs = [], Counter()
    for pos, need in RULES.squad_select.items():
        for r in info[info["position"] == pos].itertuples():
            if need == 0:
                break
            if clubs[r.team] >= RULES.team_limit:
                continue
            squad.append(
                SquadPlayer(
                    r.element,
                    r.name,
                    pos,
                    r.team,
                    r.now_cost - 1,
                    r.now_cost,
                    RULES.selling_price(r.now_cost - 1, r.now_cost),
                )
            )
            clubs[r.team] += 1
            need -= 1
    return TeamState(1, "test", GWS[0], squad, bank, ft, chips or {})


def check_plan(plan, proj: pd.DataFrame, state: TeamState, opts: PlanOptions) -> None:
    info = proj.drop_duplicates("element").set_index("element")
    assert plan.weeks, plan.status
    prev = set(state.elements)
    ft = state.free_transfers
    chips_seen = Counter()
    last_fh = None
    for w in plan.weeks:
        squad = set(w.squad)
        assert len(squad) == 15
        pos = Counter(info.loc[e, "position"] for e in squad)
        assert pos == Counter(RULES.squad_select)
        assert max(Counter(info.loc[e, "team"] for e in squad).values()) <= RULES.team_limit
        assert w.bank >= 0
        lineup = set(w.lineup)
        n_line = 15 if w.chip == "bboost" else 11
        assert len(lineup) == n_line and lineup <= squad
        lp = Counter(info.loc[e, "position"] for e in lineup)
        if w.chip != "bboost":
            assert lp["GKP"] == 1 and lp["DEF"] >= 3 and lp["MID"] >= 2 and lp["FWD"] >= 1
            assert len(w.bench) == 4 and info.loc[w.bench[0], "position"] == "GKP"
            assert set(w.bench) | lineup == squad
        assert w.captain in lineup and w.vice in lineup and w.captain != w.vice
        if w.chip:
            chips_seen[w.chip] += 1
        if w.chip == "freehit":
            assert last_fh != w.gw - 1
            last_fh = w.gw
            assert not w.transfers_in
            continue  # main squad unchanged; FH squad is temporary
        main = (prev - set(w.transfers_out)) | set(w.transfers_in)
        assert main == squad
        assert w.free_transfers == ft
        n = len(w.transfers_in)
        if w.chip == "wildcard":
            assert w.hits == 0
        else:
            assert w.hits == max(0, n - ft)
            assert w.hits <= opts.max_hits_per_gw
            ft = min(5, max(0, ft - n) + 1)
        prev = squad
    assert all(v <= 1 for v in chips_seen.values())


@pytest.fixture(scope="module")
def proj() -> pd.DataFrame:
    return make_proj()


def test_plan_without_chips_is_legal(proj: pd.DataFrame) -> None:
    st = initial_state(proj, ft=2)
    opts = PlanOptions(horizon=4, allow_chips=False, time_limit=30)
    plan = plan_transfers(proj, st, RULES, opts)
    check_plan(plan, proj, st, opts)
    # a cheap starting squad should be upgraded
    assert sum(len(w.transfers_in) for w in plan.weeks) >= 2


def test_forced_wildcard_and_bench_boost(proj: pd.DataFrame) -> None:
    st = initial_state(proj, chips={"wildcard": [1], "bboost": [1]})
    opts = PlanOptions(horizon=4, forced_chips={10: "wildcard", 12: "bboost"}, time_limit=30)
    plan = plan_transfers(proj, st, RULES, opts)
    check_plan(plan, proj, st, opts)
    wc = plan.weeks[0]
    assert wc.chip == "wildcard" and len(wc.transfers_in) > st.free_transfers and wc.hits == 0
    assert plan.weeks[2].chip == "bboost"


def test_free_hit_reverts(proj: pd.DataFrame) -> None:
    st = initial_state(proj, chips={"freehit": [1]})
    opts = PlanOptions(horizon=3, forced_chips={11: "freehit"}, time_limit=30)
    plan = plan_transfers(proj, st, RULES, opts)
    check_plan(plan, proj, st, opts)
    fh = plan.weeks[1]
    assert fh.chip == "freehit"
    assert set(fh.squad) != set(plan.weeks[0].squad)  # a cheap squad always benefits from a free hit
    assert set(plan.weeks[2].squad) == (set(plan.weeks[0].squad) - set(plan.weeks[2].transfers_out)) | set(
        plan.weeks[2].transfers_in
    )


def test_chip_limits_and_triple_captain(proj: pd.DataFrame) -> None:
    st = initial_state(proj, chips={"3xc": [1], "bboost": [1], "wildcard": [1], "freehit": [1]})
    opts = PlanOptions(
        horizon=4,
        allow_chips=True,
        time_limit=60,
        mip_gap=0.02,
        chip_option_value={"wildcard": 0, "freehit": 0, "bboost": 0, "3xc": 0},
    )
    plan = plan_transfers(proj, st, RULES, opts)
    check_plan(plan, proj, st, opts)
    used = [w.chip for w in plan.weeks if w.chip]
    assert len(used) == len(set(used))  # each chip at most once
    assert "3xc" in used and "bboost" in used  # free value with zero option cost


def test_no_chips_when_unavailable(proj: pd.DataFrame) -> None:
    st = initial_state(proj, chips={})
    opts = PlanOptions(horizon=3, allow_chips=True, time_limit=30)
    plan = plan_transfers(proj, st, RULES, opts)
    check_plan(plan, proj, st, opts)
    assert all(w.chip is None for w in plan.weeks)


def test_best_squad_respects_budget(proj: pd.DataFrame) -> None:
    out = best_squad_per_gw(proj, RULES, PlanOptions(time_limit=30), budget=800, gws=[10])
    w = out[10].weeks[0]
    info = proj.drop_duplicates("element").set_index("element")
    assert info.loc[w.squad, "now_cost"].sum() <= 800
    assert len(set(w.squad)) == 15


def test_bought_player_sells_at_selling_price(proj: pd.DataFrame) -> None:
    """Owned players risen in price sell for less than their current price."""
    st = initial_state(proj, ft=5, bank=0)
    opts = PlanOptions(horizon=1, allow_chips=False, time_limit=30)
    plan = plan_transfers(proj, st, RULES, opts)
    w = plan.weeks[0]
    info = proj.drop_duplicates("element").set_index("element")
    sell = {p.element: p.selling_price for p in st.squad}
    spent = info.loc[w.transfers_in, "now_cost"].sum() if w.transfers_in else 0
    got = sum(sell[e] for e in w.transfers_out)
    assert w.bank == st.bank + got - spent


def test_best_chip_plan_search(proj: pd.DataFrame) -> None:
    from midweek_merchant.optimize.chips import best_chip_plan, exact_values

    st = initial_state(proj, chips={"wildcard": [1], "bboost": [1]})
    free = {"wildcard": 0.0, "freehit": 0.0, "bboost": 0.0, "3xc": 0.0}
    opts = PlanOptions(horizon=4, time_limit=30, mip_gap=0.01, chip_option_value=free)
    base, exact = exact_values(proj, st, RULES, opts, max_workers=2)
    found = best_chip_plan(proj, st, RULES, opts, exact, max_workers=2)
    assert found is not None
    plan, schedule = found
    check_plan(plan, proj, st, opts)
    assert {w.gw: w.chip for w in plan.weeks if w.chip} == schedule
    assert set(schedule.values()) == {"wildcard", "bboost"}  # both are free to play here
    assert plan.objective >= base.objective - 1e-6
    # chips worth less than keeping them are held
    dear = PlanOptions(horizon=4, time_limit=30, chip_option_value={"wildcard": 500.0, "bboost": 500.0})
    assert best_chip_plan(proj, st, RULES, dear, exact) is None
