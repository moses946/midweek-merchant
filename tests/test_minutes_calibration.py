"""Minutes calibration: the monotone curve fit and its application."""

import numpy as np
import pandas as pd

from midweek_merchant.backtest.minutes_calibration import _pava, fit_curve
from midweek_merchant.models.minutes import apply_curve


def test_apply_curve_identity_and_interpolation() -> None:
    x = np.array([0.0, 0.3, 0.8, 0.99])
    assert np.allclose(apply_curve(x, None), x)
    knots = [[0.0, 0.0], [0.5, 0.6], [0.9, 0.95]]
    assert np.allclose(apply_curve(x, knots), [0.0, 0.36, 0.8625, 0.95])


def test_pava_is_monotone_and_weight_preserving() -> None:
    y, w = np.array([0.1, 0.5, 0.3, 0.7, 0.6]), np.array([1.0, 1.0, 1.0, 2.0, 2.0])
    fit = _pava(y, w)
    assert np.all(np.diff(fit) >= -1e-12)
    assert np.isclose((fit * w).sum(), (y * w).sum())


def test_fit_curve_recovers_an_under_confident_predictor() -> None:
    rng = np.random.default_rng(1)
    p = rng.uniform(0, 0.99, 40_000)
    truth = np.clip(p * 1.08, 0, 0.995)  # outcomes happen more often than predicted
    y = (rng.uniform(size=p.size) < truth).astype(float)
    knots = fit_curve(pd.Series(p), pd.Series(y))
    xs, ys = np.array(knots).T
    assert xs[0] == 0 and ys[0] == 0 and np.all(np.diff(ys) >= 0)
    assert np.allclose(apply_curve(np.array([0.5, 0.8]), knots), [0.54, 0.864], atol=0.03)


def test_attrition_lowers_availability_per_week_ahead() -> None:
    from datetime import UTC, datetime

    from midweek_merchant.models.minutes import fixture_minutes

    players = pd.DataFrame(
        {
            "element": [1],
            "status": ["a"],
            "chance_next": [np.nan],
            "news": [""],
            "scout_risk_gws": ["[]"],
            "can_select": [True],
            "removed": [False],
        }
    )
    profiles = pd.DataFrame(
        {
            "element": [1],
            "p_start_long": [0.9],
            "p_start_recent": [0.9],
            "returning": [False],
            "q60": [0.9],
            "p_sub": [0.5],
            "m_start60": [88.0],
            "m_start_lt": [45.0],
            "m_sub": [20.0],
        }
    )
    rows = pd.DataFrame(
        {
            "element": [1, 1, 1],
            "gw": [6, 7, 9],
            "fixture": [1, 2, 3],
            "kickoff_time": pd.to_datetime(["2026-10-04", "2026-10-18", "2026-11-01"], utc=True),
        }
    )
    now = datetime(2026, 10, 3, tzinfo=UTC)
    plain = fixture_minutes(profiles, players, rows, 6, now)
    worn = fixture_minutes(profiles, players, rows, 6, now, attrition=0.02)
    assert np.allclose(worn["p_start"] / plain["p_start"], [1.0, 0.98, 0.98**3])
    assert np.allclose(worn["xmins"] / plain["xmins"], [1.0, 0.98, 0.98**3])
