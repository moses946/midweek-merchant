"""Rebuild a manager's current state from public FPL endpoints (no login needed).

From ``entry``, ``history``, ``transfers`` and the latest ``picks`` we derive:
squad, purchase and selling prices, bank, free transfers and the chips still available.
Transfers made since the last deadline are not public yet, so ``pending`` transfers and
manual corrections can be applied on top (see :func:`apply_overrides`).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from midweek_merchant.data.fpl_api import FPLClient, FPLNotFound
from midweek_merchant.rules import Rules

log = logging.getLogger(__name__)


@dataclass
class SquadPlayer:
    element: int
    name: str
    position: str
    team: str
    purchase_price: int
    now_cost: int
    selling_price: int


@dataclass
class TeamState:
    entry_id: int | None
    name: str
    next_gw: int
    squad: list[SquadPlayer]
    bank: int  # tenths of £m
    free_transfers: int
    chips_available: dict[str, list[int]]  # chip name -> list of halves (1/2) still available
    chips_used: list[dict[str, Any]] = field(default_factory=list)
    total_points: int = 0
    overall_rank: int | None = None
    last_gw_points: int | None = None
    ft_check: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def elements(self) -> list[int]:
        return [p.element for p in self.squad]

    @property
    def squad_value(self) -> int:
        return sum(p.selling_price for p in self.squad)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["squad_value"] = self.squad_value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TeamState:
        d = dict(d)
        d.pop("squad_value", None)
        d["squad"] = [SquadPlayer(**p) for p in d["squad"]]
        return cls(**d)


def chips_available(rules: Rules, used: list[dict[str, Any]], next_gw: int) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for c in rules.chips:
        if next_gw > c.stop_event:
            continue
        played = any(u["name"] == c.name and c.start_event <= u["event"] <= c.stop_event for u in used)
        if not played:
            out.setdefault(c.name, []).append(rules.chip_half(c.start_event))
    return out


def replay_free_transfers(
    history: list[dict[str, Any]],
    chips: list[dict[str, Any]],
    start_event: int,
    rules: Rules,
    ft_after_chip: str = "freeze",
) -> tuple[int, dict[str, Any]]:
    """Free transfers available for the next gameweek, plus a consistency report.

    The report flags gameweeks where FPL charged a hit that our count did not predict (or
    vice versa) - evidence for the freeze/accrue behaviour after a Wildcard/Free Hit.
    """
    chip_by_gw = {c["event"]: c["name"] for c in chips}
    ft = 0
    mismatches = []
    for row in sorted(history, key=lambda r: r["event"]):
        gw = row["event"]
        n, cost = row.get("event_transfers", 0), row.get("event_transfers_cost", 0)
        if gw <= start_event:  # initial squad selection: unlimited
            ft = 1
            continue
        chip = chip_by_gw.get(gw)
        if chip in ("wildcard", "freehit"):
            ft = min(rules.max_free_transfers, ft + 1) if ft_after_chip == "accrue" else ft
            continue
        expected_cost = rules.hit_cost * max(0, n - ft)
        if expected_cost != cost:
            mismatches.append(
                {"gw": gw, "transfers": n, "ft_model": ft, "cost": cost, "expected": expected_cost}
            )
        ft = min(rules.max_free_transfers, max(0, ft - n) + 1)
    return max(1, ft), {"mismatches": mismatches}


def reconstruct(
    client: FPLClient,
    entry_id: int,
    players: pd.DataFrame,
    rules: Rules,
    next_gw: int,
    ft_after_chip: str = "freeze",
) -> TeamState:
    entry = client.entry(entry_id)
    hist = client.entry_history(entry_id)
    transfers = client.entry_transfers(entry_id)
    current = hist.get("current", [])
    chips = hist.get("chips", [])
    notes: list[str] = []
    if not current:
        raise ValueError(f"Entry {entry_id} has no gameweek history yet")
    last_gw = max(r["event"] for r in current)
    start_event = entry.get("started_event") or min(r["event"] for r in current)
    picks = client.entry_picks(entry_id, last_gw)
    fh_gws = {c["event"] for c in chips if c["name"] == "freehit"}
    if picks.get("active_chip") == "freehit" or last_gw in fh_gws:
        notes.append(f"GW{last_gw} was a Free Hit; squad reverted to GW{last_gw - 1} picks")
        try:
            picks = client.entry_picks(entry_id, last_gw - 1)
        except FPLNotFound:
            notes.append("Could not load pre-Free-Hit picks")
    elements = [p["element"] for p in picks["picks"]]

    info = players.set_index("element")
    squad = []
    for el in elements:
        p = info.loc[el]
        buys = [t for t in transfers if t["element_in"] == el and t["event"] not in fh_gws]
        if buys:
            purchase = max(buys, key=lambda t: t["time"])["element_in_cost"]
        elif start_event <= 1:
            purchase = int(p["now_cost"] - p["cost_change_start"])
        else:
            purchase = _price_at_gw(client, el, start_event, int(p["now_cost"] - p["cost_change_start"]))
        now = int(p["now_cost"])
        squad.append(
            SquadPlayer(
                element=int(el),
                name=p["name"],
                position=p["position"],
                team=p["team"],
                purchase_price=int(purchase),
                now_cost=now,
                selling_price=Rules.selling_price(int(purchase), now),
            )
        )

    latest = max(current, key=lambda r: r["event"])
    bank = int(entry.get("last_deadline_bank", latest.get("bank", 0)) or 0)
    ft, report = replay_free_transfers(current, chips, start_event, rules, ft_after_chip)
    if report["mismatches"]:
        notes.append(
            f"FT replay disagreed with FPL hit charges in {len(report['mismatches'])} GW(s); check FTs"
        )
    return TeamState(
        entry_id=entry_id,
        name=entry.get("name", ""),
        next_gw=next_gw,
        squad=squad,
        bank=bank,
        free_transfers=ft,
        chips_available=chips_available(rules, chips, next_gw),
        chips_used=[{"name": c["name"], "event": c["event"]} for c in chips],
        total_points=entry.get("summary_overall_points", 0) or 0,
        overall_rank=entry.get("summary_overall_rank"),
        last_gw_points=latest.get("points"),
        ft_check=report,
        notes=notes,
    )


def _price_at_gw(client: FPLClient, element: int, gw: int, fallback: int) -> int:
    try:
        hist = client.element_summary(element)["history"]
    except Exception:  # noqa: BLE001
        return fallback
    rows = [h for h in hist if h["round"] >= gw]
    return int(rows[0]["value"]) if rows else fallback


def apply_overrides(state: TeamState, players: pd.DataFrame, overrides: dict[str, Any]) -> TeamState:
    """Apply pending transfers / manual corrections.

    ``overrides`` keys: ``pending`` (list of {"out": id, "in": id}), ``bank`` (tenths),
    ``free_transfers``, ``chips_available`` (dict), ``purchase_prices`` ({element: tenths}).
    """
    info = players.set_index("element")
    squad = {p.element: p for p in state.squad}
    bank = state.bank
    for el, price in (overrides.get("purchase_prices") or {}).items():
        el = int(el)
        if el in squad:
            sp = squad[el]
            sp.purchase_price = int(price)
            sp.selling_price = Rules.selling_price(sp.purchase_price, sp.now_cost)
    n_pending = 0
    for t in overrides.get("pending") or []:
        out_el, in_el = int(t["out"]), int(t["in"])
        if out_el not in squad or in_el in squad:
            state.notes.append(f"Ignored pending transfer {out_el}->{in_el}")
            continue
        bank += squad.pop(out_el).selling_price
        p = info.loc[in_el]
        squad[in_el] = SquadPlayer(
            int(in_el),
            p["name"],
            p["position"],
            p["team"],
            int(p["now_cost"]),
            int(p["now_cost"]),
            int(p["now_cost"]),
        )
        bank -= int(p["now_cost"])
        n_pending += 1
    state.squad = list(squad.values())
    state.bank = int(overrides.get("bank", bank))
    if "free_transfers" in overrides:
        state.free_transfers = int(overrides["free_transfers"])
    elif n_pending:
        state.free_transfers = max(0, state.free_transfers - n_pending)
        state.notes.append(f"{n_pending} pending transfer(s) applied; FTs now {state.free_transfers}")
    if "chips_available" in overrides:
        state.chips_available = {k: list(v) for k, v in overrides["chips_available"].items()}
    return state


def manual_state(
    players: pd.DataFrame,
    elements: list[int],
    bank: int,
    free_transfers: int,
    chips: dict[str, list[int]],
    next_gw: int,
    purchase: dict[int, int] | None = None,
) -> TeamState:
    info = players.set_index("element")
    squad = []
    for el in elements:
        p = info.loc[el]
        buy = int((purchase or {}).get(el, p["now_cost"]))
        squad.append(
            SquadPlayer(
                int(el),
                p["name"],
                p["position"],
                p["team"],
                buy,
                int(p["now_cost"]),
                Rules.selling_price(buy, int(p["now_cost"])),
            )
        )
    return TeamState(None, "Manual squad", next_gw, squad, bank, free_transfers, chips)


def validate_squad(state: TeamState, rules: Rules) -> list[str]:
    errs = []
    if len(state.squad) != rules.squad_size:
        errs.append(f"Squad has {len(state.squad)} players (need {rules.squad_size})")
    counts = pd.Series([p.position for p in state.squad]).value_counts().to_dict()
    for pos, n in rules.squad_select.items():
        if counts.get(pos, 0) != n:
            errs.append(f"{pos}: {counts.get(pos, 0)} (need {n})")
    clubs = pd.Series([p.team for p in state.squad]).value_counts()
    for club, n in clubs.items():
        if n > rules.team_limit:
            errs.append(f"{n} players from {club} (max {rules.team_limit})")
    return errs
