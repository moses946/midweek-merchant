"""Next-gameweek points calibration: the curve, where it applies and how it is fitted."""

import numpy as np
import pandas as pd

from midweek_merchant.backtest.points_calibration import fit_points_curve
from midweek_merchant.models.xpts import PTS_COLS, calibrate_points, points_curve

KNOTS = [[0.0, 0.0], [2.0, 1.8], [4.0, 4.4]]


def test_points_curve_interpolates_and_extrapolates_by_ratio() -> None:
    x = np.array([0.0, 1.0, 3.0, 4.0, 8.0])
    assert np.allclose(points_curve(x, None), x)
    assert np.allclose(points_curve(x, KNOTS), [0.0, 0.9, 3.1, 4.4, 8.8])


def test_calibrate_points_scales_selected_rows_and_components() -> None:
    comps = {c: [0.5, 0.5] for c in PTS_COLS}
    df = pd.DataFrame({"gw": [6, 7], **comps})
    df["xpts"] = df[PTS_COLS].sum(axis=1)  # 4.5 each
    out = calibrate_points(df, KNOTS, df["gw"] == 6)
    assert np.isclose(out.loc[0, "xpts"], 4.95) and np.isclose(out.loc[0, "pts_scale"], 1.1)
    assert np.isclose(out.loc[1, "xpts"], 4.5) and out.loc[1, "pts_scale"] == 1.0  # later week untouched
    assert np.allclose(out[PTS_COLS].sum(axis=1), out["xpts"])  # components still add up
    assert np.allclose(out["xpts_raw"], 4.5)


def test_fit_points_curve_recovers_compression() -> None:
    rng = np.random.default_rng(3)
    p = rng.gamma(2.0, 1.2, 60_000)
    y = rng.poisson(np.maximum(1.15 * p - 0.35, 0.01))  # the best players outscore their projection
    knots = fit_points_curve(pd.Series(p), pd.Series(y.astype(float)))
    xs, ys = np.array(knots).T
    assert xs[0] == 0 and np.all(np.diff(xs) > 0) and np.all(np.diff(ys) >= 0)
    assert np.allclose(points_curve(np.array([1.0, 5.0]), knots), [0.8, 5.4], atol=0.15)
