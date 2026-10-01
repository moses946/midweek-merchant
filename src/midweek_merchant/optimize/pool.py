"""Candidate-pool filtering to keep the MILP small."""

from __future__ import annotations

import numpy as np
import pandas as pd

QUOTA = {"GKP": 18, "DEF": 55, "MID": 65, "FWD": 32}


def select_pool(
    proj: pd.DataFrame,
    gws: list[int],
    decay: float,
    must_include: set[int] | None = None,
    quota: dict[str, int] | None = None,
    exclude: set[int] | None = None,
) -> list[int]:
    """Pick candidate elements: best by decayed xPts and by xPts per £ in each position,
    the cheapest playing options (bench fodder), plus anything that must be included."""
    quota = quota or QUOTA
    must = set(must_include or ())
    exclude = set(exclude or ()) - must
    p = proj[proj["gw"].isin(gws)].copy()
    p["w"] = decay ** (p["gw"] - min(gws))
    agg = (
        p.assign(wx=p["xpts"] * p["w"])
        .groupby(["element", "position", "now_cost"], as_index=False)
        .agg(ev=("wx", "sum"), xmins=("xmins", "sum"))
    )
    agg = agg[~agg["element"].isin(exclude)]
    keep: set[int] = set(must)
    for pos, n in quota.items():
        a = agg[agg["position"] == pos]
        keep |= set(a.nlargest(n, "ev")["element"])
        a = a.assign(value=a["ev"] / np.maximum(a["now_cost"], 1))
        keep |= set(a.nlargest(max(5, n // 4), "value")["element"])
        playing = a[a["xmins"] >= 30 * len(gws)]
        keep |= set(playing.nsmallest(4, "now_cost")["element"])
    return sorted(keep)
