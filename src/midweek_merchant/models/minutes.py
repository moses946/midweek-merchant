"""Minutes model: probability of starting, lasting 60', coming off the bench, and availability.

v1 is a transparent heuristic:
* recency-weighted start / 60+ / bench-appearance rates, empirical-Bayes shrunk
  towards position×price priors learnt from the current season;
* runs of 3+ zero-minute matches by an otherwise regular starter are treated as
  absences (injury/suspension) rather than evidence of rotation;
* FPL status, ``chance_of_playing``, "Expected back <date>" / "Suspended until <date>"
  news and loan ineligibility (``scout_risks``) set per-fixture availability;
* far-horizon start probabilities regress towards the long-run rate.

Manual overrides (YAML/UI) take precedence.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime

import numpy as np
import pandas as pd

MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1
    )
}
DATE_RE = re.compile(r"(?:expected back|suspended until|until)\s+(\d{1,2})\s+([A-Za-z]{3})", re.I)

PRICE_BINS = {
    "GKP": [0, 45, 50, 999],
    "DEF": [0, 45, 50, 55, 999],
    "MID": [0, 50, 60, 75, 95, 999],
    "FWD": [0, 55, 65, 80, 999],
}


def _price_band(position: str, cost: float) -> int:
    bins = PRICE_BINS[position]
    return int(np.searchsorted(bins, cost, side="right") - 1)


def _ewm(values: np.ndarray, half_life: float) -> tuple[float, float]:
    """Weighted sum and weight total with most recent value last."""
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    w = 0.5 ** (np.arange(n)[::-1] / half_life)
    return float(np.sum(w * values)), float(np.sum(w))


def _absence_mask(minutes: np.ndarray, starts: np.ndarray) -> np.ndarray:
    """True for rows inside 3+ zero-minute runs when the player is otherwise a regular."""
    mask = np.zeros(len(minutes), dtype=bool)
    if starts.sum() < 3:
        return mask
    i = 0
    while i < len(minutes):
        if minutes[i] == 0:
            j = i
            while j < len(minutes) and minutes[j] == 0:
                j += 1
            if j - i >= 3:
                mask[i:j] = True
            i = j
        else:
            i += 1
    return mask


def start_priors(panel: pd.DataFrame, players: pd.DataFrame, season: str) -> dict[tuple[str, int], float]:
    cur = panel[panel["season"] == season]
    agg = cur.groupby("code").agg(n=("minutes", "size"), st=("starts", "sum")).reset_index()
    agg = agg[agg["n"] >= 2].merge(players[["code", "position", "now_cost"]], on="code")
    agg["band"] = [_price_band(p, c) for p, c in zip(agg["position"], agg["now_cost"], strict=True)]
    agg["rate"] = agg["st"] / agg["n"]
    pri = agg.groupby(["position", "band"])["rate"].mean().to_dict()
    for pos, bins in PRICE_BINS.items():
        for b in range(len(bins) - 1):
            pri.setdefault((pos, b), 0.15 + 0.12 * b)
    return pri


def minutes_profiles(
    panel: pd.DataFrame, players: pd.DataFrame, season: str, window: int = 20
) -> pd.DataFrame:
    """Per-player start/60/sub rates from recent team matches."""
    priors = start_priors(panel, players, season)
    by_code = {c: g for c, g in panel.groupby("code")}
    out = []
    for p in players.itertuples(index=False):
        g = by_code.get(p.code)
        band = _price_band(p.position, p.now_cost)
        prior = priors[(p.position, band)]
        rec = {"element": p.element, "code": p.code, "prior_start": prior}
        if g is None or len(g) == 0:
            rec.update(
                p_start_recent=prior,
                p_start_long=prior,
                q60=0.8,
                p_sub=0.3,
                m_start60=87.0,
                m_start_lt=55.0,
                m_sub=18.0,
                n_obs=0,
                returning=False,
                last_minutes=np.nan,
            )
            out.append(rec)
            continue
        g = g.tail(window)
        mins = g["minutes"].to_numpy(float)
        starts = g["starts"].fillna((g["minutes"] >= 45).astype(float)).to_numpy(float)
        absent = _absence_mask(mins, starts)
        keep = ~absent
        m_k, s_k = mins[keep], starts[keep]
        ss, sw = _ewm(s_k, 4.0)
        ls, lw = _ewm(s_k, 15.0)
        a = 1.0
        p_recent = (a * prior + ss) / (a + sw)
        p_long = (a * prior + ls) / (a + lw)
        started = s_k > 0
        q_num, q_w = _ewm((m_k[started] >= 60).astype(float), 8.0)
        q60 = (2 * 0.8 + q_num) / (2 + q_w)
        non_start = ~started
        sub_num, sub_w = _ewm((m_k[non_start] > 0).astype(float), 6.0)
        p_sub = (2 * 0.3 + sub_num) / (2 + sub_w)
        m60 = m_k[started & (m_k >= 60)]
        mlt = m_k[started & (m_k < 60)]
        msub = m_k[non_start & (m_k > 0)]
        rec.update(
            p_start_recent=p_recent,
            p_start_long=p_long,
            q60=q60,
            p_sub=p_sub,
            m_start60=float(np.clip((np.sum(m60) + 3 * 87) / (len(m60) + 3), 60, 95)),
            m_start_lt=float(np.clip((np.sum(mlt) + 3 * 55) / (len(mlt) + 3), 1, 59)),
            m_sub=float(np.clip((np.sum(msub) + 3 * 18) / (len(msub) + 3), 1, 45)),
            n_obs=int(keep.sum()),
            returning=bool(absent[-1]) if len(absent) else False,
            last_minutes=float(mins[-1]),
        )
        out.append(rec)
    return pd.DataFrame(out)


def _parse_return_date(news: str, ref: datetime) -> date | None:
    m = DATE_RE.search(news or "")
    if not m:
        return None
    day, mon = int(m.group(1)), MONTHS.get(m.group(2).lower()[:3])
    if not mon:
        return None
    year = ref.year + (1 if mon < ref.month - 6 else 0)
    try:
        return date(year, mon, day)
    except ValueError:
        return None


def availability(players: pd.DataFrame, fixture_rows: pd.DataFrame, next_gw: int, ref: datetime) -> pd.Series:
    """Availability multiplier per (element, fixture) row of ``fixture_rows``.

    ``fixture_rows`` needs element, gw, kickoff_time.
    """
    info = players.set_index("element")
    vals = np.ones(len(fixture_rows))
    for i, r in enumerate(fixture_rows.itertuples(index=False)):
        p = info.loc[r.element]
        k = int(r.gw) - next_gw
        status, chance = p["status"], p["chance_next"]
        kick = pd.Timestamp(r.kickoff_time).tz_convert("Europe/London").date()
        risk_gws = json.loads(p["scout_risk_gws"] or "[]")
        if int(r.gw) in risk_gws:
            vals[i] = 0.0
            continue
        if status == "a":
            c = 1.0 if pd.isna(chance) else float(chance) / 100
            vals[i] = c if k == 0 else 1 - (1 - c) * 0.5**k
        elif status == "d":
            c = 0.5 if pd.isna(chance) else float(chance) / 100
            vals[i] = c if k == 0 else 1 - (1 - c) * 0.5**k
        elif status in ("i", "s"):
            back = _parse_return_date(p["news"], ref)
            if back is not None:
                vals[i] = 0.0 if kick < back else (0.75 if (kick - back).days < 7 else 0.95)
            elif status == "s":
                vals[i] = 0.0 if k == 0 else 1.0
            else:
                vals[i] = 0.0 if k == 0 else float(1 - np.exp(-k / 3.0))
        else:  # u (left club / on loan), n (not available)
            vals[i] = 0.0
        if not p["can_select"] or p["removed"]:
            vals[i] = 0.0
    return pd.Series(vals, index=fixture_rows.index)


def fixture_minutes(
    profiles: pd.DataFrame,
    players: pd.DataFrame,
    fixture_rows: pd.DataFrame,
    next_gw: int,
    ref: datetime,
    overrides: dict[int, dict] | None = None,
) -> pd.DataFrame:
    """Per (element, fixture) state probabilities and minutes.

    States: S60 (start, 60+), SLT (start, <60), SUB (bench appearance), none.
    """
    df = fixture_rows.merge(profiles, on="element", how="left")
    df["avail"] = availability(players, df, next_gw, ref).to_numpy()
    k = (df["gw"].astype(int) - next_gw).clip(lower=0)
    base = df["p_start_long"] + (df["p_start_recent"] - df["p_start_long"]) * 0.85**k
    # A regular returning from a long absence starts less often at first.
    base = np.where(df["returning"] & (k == 0), base * 0.75, base)
    df["p_start"] = np.clip(base, 0, 0.99) * df["avail"]
    df["p_sub_app"] = (1 - np.clip(base, 0, 0.99)) * df["p_sub"] * df["avail"]
    if overrides:
        for el, ov in overrides.items():
            m = df["element"] == int(el)
            if "p_start" in ov:
                df.loc[m, "p_start"] = float(ov["p_start"])
                df.loc[m, "p_sub_app"] = (1 - float(ov["p_start"])) * df.loc[m, "p_sub"]
            if "avail" in ov:
                df.loc[m, ["p_start", "p_sub_app"]] *= float(ov["avail"])
    df["p_s60"] = df["p_start"] * df["q60"]
    df["p_slt"] = df["p_start"] * (1 - df["q60"])
    df["p_play"] = df["p_start"] + df["p_sub_app"]
    df["xmins"] = (
        df["p_s60"] * df["m_start60"] + df["p_slt"] * df["m_start_lt"] + df["p_sub_app"] * df["m_sub"]
    )
    return df
