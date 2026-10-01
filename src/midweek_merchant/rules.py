"""FPL game rules for the 2026/27 season.

Values are read from ``bootstrap-static`` (``game_config``) when available so that a
mid-season rule tweak by FPL is picked up automatically; the defaults below match
the live 2026/27 configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
POS_IDS = {v: k for k, v in POSITIONS.items()}

# Defensive contribution thresholds (not exposed in game_config).
DEFCON_THRESHOLD = {"GKP": None, "DEF": 10, "MID": 12, "FWD": 12}


@dataclass(frozen=True)
class ChipWindow:
    chip_id: int
    name: str  # wildcard | freehit | bboost | 3xc
    start_event: int
    stop_event: int


@dataclass(frozen=True)
class Rules:
    goal_pts: dict[str, int] = field(default_factory=lambda: {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4})
    cs_pts: dict[str, int] = field(default_factory=lambda: {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0})
    gc_pts: dict[str, int] = field(default_factory=lambda: {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0})
    defcon_pts: dict[str, int] = field(default_factory=lambda: {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2})
    assist_pts: int = 3
    long_play: int = 2
    short_play: int = 1
    save_pts: int = 1
    saves_per_point: int = 3
    goals_conceded_per_point: int = 2
    pen_save_pts: int = 5
    pen_miss_pts: int = -2
    yellow_pts: int = -1
    red_pts: int = -3
    own_goal_pts: int = -2
    squad_size: int = 15
    squad_play: int = 11
    team_limit: int = 3
    budget: int = 1000  # tenths of £m
    squad_select: dict[str, int] = field(default_factory=lambda: {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3})
    play_min: dict[str, int] = field(default_factory=lambda: {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1})
    play_max: dict[str, int] = field(default_factory=lambda: {"GKP": 1, "DEF": 5, "MID": 5, "FWD": 3})
    max_free_transfers: int = 5
    transfers_cap: int = 20
    hit_cost: int = 4
    sell_on_fee: float = 0.5
    chips: tuple[ChipWindow, ...] = ()

    # ------------------------------------------------------------------ scoring
    def minutes_points(self, minutes: float) -> int:
        if minutes >= 60:
            return self.long_play
        return self.short_play if minutes > 0 else 0

    def defcon_points(self, position: str, count: float) -> int:
        thr = DEFCON_THRESHOLD[position]
        return self.defcon_pts[position] if thr is not None and count >= thr else 0

    def identifier_points(self, identifier: str, value: float, position: str) -> int:
        """Points for one ``explain`` identifier of one fixture (mirrors FPL scoring)."""
        v = int(value)
        match identifier:
            case "minutes":
                return self.minutes_points(v)
            case "goals_scored":
                return v * self.goal_pts[position]
            case "assists":
                return v * self.assist_pts
            case "clean_sheets":
                return v * self.cs_pts[position]
            case "goals_conceded":
                return (v // self.goals_conceded_per_point) * self.gc_pts[position]
            case "saves":
                return (v // self.saves_per_point) * self.save_pts if position == "GKP" else 0
            case "penalties_saved":
                return v * self.pen_save_pts
            case "penalties_missed":
                return v * self.pen_miss_pts
            case "yellow_cards":
                return v * self.yellow_pts
            case "red_cards":
                return v * self.red_pts
            case "own_goals":
                return v * self.own_goal_pts
            case "bonus":
                return v
            case "defensive_contribution":
                return self.defcon_points(position, v)
        return 0

    def match_points(self, position: str, s: dict[str, float]) -> int:
        """Points for a single match from raw stat counts."""
        pts = self.minutes_points(s.get("minutes", 0))
        for ident in (
            "goals_scored",
            "assists",
            "goals_conceded",
            "saves",
            "penalties_saved",
            "penalties_missed",
            "yellow_cards",
            "red_cards",
            "own_goals",
            "bonus",
            "defensive_contribution",
        ):
            pts += self.identifier_points(ident, s.get(ident, 0), position)
        if s.get("minutes", 0) >= 60:
            pts += self.identifier_points("clean_sheets", s.get("clean_sheets", 0), position)
        return pts

    # ------------------------------------------------------------------ prices
    @staticmethod
    def selling_price(purchase: int, now: int) -> int:
        """Selling price in tenths: keep half of any rise (rounded down), absorb all falls."""
        if now <= purchase:
            return now
        return purchase + (now - purchase) // 2

    # ------------------------------------------------------------------ chips
    def chip_windows(self, name: str) -> list[ChipWindow]:
        return [c for c in self.chips if c.name == name]

    def chip_half(self, gw: int) -> int:
        """1 for the first chip window (GW1-19), 2 for the second (GW20-38)."""
        return 1 if gw <= 19 else 2


DEFAULT_CHIPS = (
    ChipWindow(1, "wildcard", 2, 19),
    ChipWindow(2, "wildcard", 20, 38),
    ChipWindow(3, "freehit", 2, 19),
    ChipWindow(6, "freehit", 20, 38),
    ChipWindow(4, "bboost", 1, 19),
    ChipWindow(7, "bboost", 20, 38),
    ChipWindow(5, "3xc", 1, 19),
    ChipWindow(8, "3xc", 20, 38),
)


def rules_from_bootstrap(bootstrap: dict[str, Any] | None) -> Rules:
    """Build :class:`Rules` from a ``bootstrap-static`` payload (falls back to defaults)."""
    if not bootstrap:
        return Rules(chips=DEFAULT_CHIPS)
    sc = bootstrap.get("game_config", {}).get("scoring", {})
    gs = bootstrap.get("game_settings", {})
    types = {t["singular_name_short"]: t for t in bootstrap.get("element_types", [])}

    def by_pos(key: str, default: dict[str, int]) -> dict[str, int]:
        val = sc.get(key)
        return {p: int(val.get(p, default[p])) for p in default} if isinstance(val, dict) else default

    base = Rules()
    chips = (
        tuple(
            ChipWindow(c["id"], c["name"], c["start_event"], c["stop_event"])
            for c in bootstrap.get("chips", [])
        )
        or DEFAULT_CHIPS
    )
    return Rules(
        goal_pts=by_pos("goals_scored", base.goal_pts),
        cs_pts=by_pos("clean_sheets", base.cs_pts),
        gc_pts=by_pos("goals_conceded", base.gc_pts),
        defcon_pts=by_pos("defensive_contribution", base.defcon_pts),
        assist_pts=int(sc.get("assists", base.assist_pts)),
        long_play=int(sc.get("long_play", base.long_play)),
        short_play=int(sc.get("short_play", base.short_play)),
        save_pts=int(sc.get("saves", base.save_pts)),
        pen_save_pts=int(sc.get("penalties_saved", base.pen_save_pts)),
        pen_miss_pts=int(sc.get("penalties_missed", base.pen_miss_pts)),
        yellow_pts=int(sc.get("yellow_cards", base.yellow_pts)),
        red_pts=int(sc.get("red_cards", base.red_pts)),
        own_goal_pts=int(sc.get("own_goals", base.own_goal_pts)),
        squad_size=int(gs.get("squad_squadsize", base.squad_size)),
        squad_play=int(gs.get("squad_squadplay", base.squad_play)),
        team_limit=int(gs.get("squad_team_limit", base.team_limit)),
        budget=int(gs.get("squad_total_spend", base.budget)),
        squad_select={p: int(types[p]["squad_select"]) for p in types} or base.squad_select,
        play_min={p: int(types[p]["squad_min_play"]) for p in types} or base.play_min,
        play_max={p: int(types[p]["squad_max_play"]) for p in types} or base.play_max,
        max_free_transfers=1 + int(gs.get("max_extra_free_transfers", 4)),
        transfers_cap=int(gs.get("transfers_cap", base.transfers_cap)),
        sell_on_fee=float(gs.get("transfers_sell_on_fee", base.sell_on_fee)),
        chips=chips,
    )
