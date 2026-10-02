"""Ceiling planner checks: tail metrics, ceiling captaincy, chip lineups and tail calibration."""

from dataclasses import replace

import numpy as np

from midweek_merchant.backtest.tails import SCALES, crps_scaled
from midweek_merchant.models.simulate import SimResult, rescale
from midweek_merchant.optimize.milp import Plan, WeekPlan
from midweek_merchant.optimize.planner import empty_state
from midweek_merchant.rules import rules_from_bootstrap
from midweek_merchant.strategy.ceiling import ceiling_captain, reference_schedules, schedules, tail_metrics
from midweek_merchant.strategy.league import Lineup, plan_lineups, score_lineup

RULES = rules_from_bootstrap(None)


def toy_sim(points: np.ndarray, gw: int = 1) -> SimResult:
    """Simulations x players matrix, everyone 'played' when they scored anything or always."""
    n = points.shape[1]
    return SimResult(
        [gw], np.arange(1, n + 1), {gw: points.astype(np.float32)}, {gw: np.ones_like(points, bool)}
    )


def test_tail_metrics_any_week() -> None:
    w1 = np.array([100.0, 50, 50, 120])
    w2 = np.array([50.0, 110, 50, 90])
    m = tail_metrics({1: w1, 2: w2}, 100)
    assert m["p_any"] == 0.75
    assert m["p_week"] == {1: 0.5, 2: 0.25}
    assert np.isclose(m["e_best_week"], (100 + 110 + 50 + 120) / 4)
    assert np.isclose(m["e_total"], (w1 + w2).mean())


def _captain_case() -> tuple[SimResult, Lineup]:
    # 9 players on a steady 5, player 10 a steady 8, player 11 either 0 or 16 (also mean 8)
    S = 1000
    pts = np.full((S, 11), 5.0)
    pts[:, 9] = 8.0
    pts[:, 10] = np.where(np.arange(S) % 2 == 0, 0.0, 16.0)
    return toy_sim(pts), Lineup(list(range(1, 12)), [], captain=10, vice=11)


def test_ceiling_captain_prefers_upside_for_a_high_target() -> None:
    sim, lu = _captain_case()
    # captain 10 -> 61 or 77; captain 11 -> 53 or 85: equal means, only 11 can reach 80
    chosen, s = ceiling_captain(sim, 1, lu, target=80)
    assert chosen.captain == 11 and chosen.vice == 10
    assert np.isclose((s >= 80).mean(), 0.5)


def test_ceiling_captain_prefers_safety_for_a_low_target() -> None:
    sim, lu = _captain_case()
    chosen, s = ceiling_captain(sim, 1, replace(lu, captain=11, vice=10), target=60)
    assert chosen.captain == 10
    assert (s >= 60).all()


def test_ceiling_captain_ignores_noise_level_gains() -> None:
    # two captains with identical, independent distributions: any gap in P(target) is noise
    rng = np.random.default_rng(3)
    S = 4000
    pts = np.full((S, 11), 5.0)
    pts[:, 9] = rng.choice([2.0, 15.0], S, p=[0.8, 0.2])
    pts[:, 10] = rng.choice([2.0, 15.0], S, p=[0.8, 0.2])
    lu = Lineup(list(range(1, 12)), [], captain=10, vice=11)
    chosen, _ = ceiling_captain(toy_sim(pts), 1, lu, target=70)  # P = 0.2 for either captain
    assert chosen.captain == 10


def _week(chip: str | None) -> WeekPlan:
    squad = list(range(1, 16))
    return WeekPlan(
        gw=1,
        chip=chip,
        transfers_in=[],
        transfers_out=[],
        squad=squad,
        lineup=squad[:11],
        bench=squad[11:],
        captain=1,
        vice=2,
        free_transfers=1,
        hits=0,
        bank=0,
        xpts=0.0,
        xpts_lineup=0.0,
    )


def test_triple_captain_and_bench_boost_scoring() -> None:
    pts = np.tile(np.arange(1, 16, dtype=float), (10, 1))  # player e scores e points
    sim = toy_sim(pts)
    starters = sum(range(1, 12))
    plain = plan_lineups(Plan("ok", 0, 0, 0, [_week(None)], 0))[1]
    tc = plan_lineups(Plan("ok", 0, 0, 0, [_week("3xc")], 0))[1]
    bb = plan_lineups(Plan("ok", 0, 0, 0, [_week("bboost")], 0))[1]
    assert np.allclose(score_lineup(sim, 1, plain), starters + 1)  # captain (1 pt) doubled
    assert np.allclose(score_lineup(sim, 1, tc), starters + 2)  # tripled
    assert np.allclose(score_lineup(sim, 1, bb), sum(range(1, 16)) + 1)  # all 15 count


def test_schedules_follow_chip_rules() -> None:
    state = empty_state(6, chips={c: [1, 2] for c in ("wildcard", "freehit", "bboost", "3xc")})
    gws = [6, 7, 8, 9]
    sch = schedules(state, RULES, gws)
    labels = [s.label for s in sch]
    assert len(labels) == len(set(labels))
    for s in sch:
        chips = [c for _, c in s.chips]
        assert len(chips) == len(set(chips))  # each chip at most once in the window
        assert all(g in gws for g, _ in s.chips)
        assert all(g == 6 for g, c in s.chips if c == "wildcard")  # wildcard builds for later weeks
    no_bb = empty_state(6, chips={"wildcard": [1, 2], "3xc": [1, 2]})
    assert not any(c == "bboost" for s in schedules(no_bb, RULES, gws) for _, c in s.chips)


def test_rescale_keeps_mean_and_scales_spread() -> None:
    x = np.random.default_rng(0).normal(60, 15, 20_000)
    y = rescale(x, 0.8)
    assert np.isclose(y.mean(), x.mean())
    assert np.isclose(y.std(), 0.8 * x.std())


def test_crps_recovers_the_spread_factor() -> None:
    rng = np.random.default_rng(1)
    samples = rng.normal(0, 2.0, 4000)  # simulator twice as wide as reality
    obs = rng.normal(0, 1.0, 400)
    crps = np.mean([crps_scaled(samples, y, SCALES) for y in obs], axis=0)
    assert SCALES[int(np.argmin(crps))] == 0.6  # the narrowest grid value is closest to 0.5
    wide = rng.normal(0, 1.0, 4000)
    crps = np.mean([crps_scaled(wide, y, SCALES) for y in obs], axis=0)
    assert abs(SCALES[int(np.argmin(crps))] - 1.0) <= 0.1


def test_reference_schedules_keep_bench_boost_for_later() -> None:
    state = empty_state(6, chips={c: [1, 2] for c in ("wildcard", "freehit", "bboost", "3xc")})
    refs = reference_schedules(state, RULES, [6, 7, 8, 9], list(range(6, 14)))
    assert [s.chip_map for s in refs] == [{6: "wildcard", g: "bboost"} for g in range(10, 14)]
