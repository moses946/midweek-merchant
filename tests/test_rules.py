import json
from pathlib import Path

import pytest

from midweek_merchant.rules import POSITIONS, Rules, rules_from_bootstrap

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def rules() -> Rules:
    return rules_from_bootstrap(None)


def test_explain_points_match_fpl(rules: Rules) -> None:
    """Every explain line in real 2026/27 data must be reproduced by our scoring rules."""
    data = json.loads((FIXTURES / "live_sample.json").read_text())
    checked = 0
    for el in data["elements"]:
        pos = POSITIONS[data["element_types"][str(el["id"])]]
        total = 0
        for fx in el["explain"]:
            for s in fx["stats"]:
                expected = s["points"] - s.get("points_modification", 0)
                assert rules.identifier_points(s["identifier"], s["value"], pos) == expected, (el, s)
                total += s["points"]
                checked += 1
        assert total == el["total_points"]
    assert checked > 1000


def test_match_points_examples(rules: Rules) -> None:
    # Defender: 90 mins, clean sheet, goal, 11 CBIT -> 2 + 4 + 6 + 2 = 14 (+bonus 3)
    s = {"minutes": 90, "clean_sheets": 1, "goals_scored": 1, "defensive_contribution": 11, "bonus": 3}
    assert rules.match_points("DEF", s) == 17
    # Midfielder with 11 CBIRT gets no DefCon (threshold 12)
    assert rules.match_points("MID", {"minutes": 90, "defensive_contribution": 11}) == 2
    # Goalkeeper: 7 saves, 3 conceded, 75 mins -> 2 + 2 - 1
    assert rules.match_points("GKP", {"minutes": 75, "saves": 7, "goals_conceded": 3}) == 3
    # GK goal is worth 10 in 2026/27
    assert rules.match_points("GKP", {"minutes": 90, "goals_scored": 1}) == 12
    # Clean sheet ignored under 60 minutes
    assert rules.match_points("DEF", {"minutes": 45, "clean_sheets": 1}) == 1


@pytest.mark.parametrize(
    ("buy", "now", "sell"),
    [(75, 78, 76), (75, 77, 76), (75, 76, 75), (75, 75, 75), (75, 72, 72), (50, 59, 54), (100, 101, 100)],
)
def test_selling_price(buy: int, now: int, sell: int) -> None:
    assert Rules.selling_price(buy, now) == sell


def test_rules_from_bootstrap_defaults() -> None:
    r = rules_from_bootstrap(None)
    assert r.max_free_transfers == 5
    assert r.squad_select == {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
    assert len(r.chips) == 8
    assert r.chip_half(19) == 1 and r.chip_half(20) == 2
