"""Canonical team identity.

The canonical team key is the football-data.co.uk name (e.g. ``"Man United"``) because
it also covers Championship sides, which the team-strength model uses to rate
promoted clubs. FPL team ``code`` values are persistent across seasons and map
onto these names.
"""

from __future__ import annotations

FPL_CODE_TO_TEAM: dict[int, str] = {
    1: "Man United",
    2: "Leeds",
    3: "Arsenal",
    4: "Newcastle",
    6: "Tottenham",
    7: "Aston Villa",
    8: "Chelsea",
    9: "Coventry",
    11: "Everton",
    13: "Leicester",
    14: "Liverpool",
    17: "Nott'm Forest",
    20: "Southampton",
    21: "West Ham",
    31: "Crystal Palace",
    36: "Brighton",
    39: "Wolves",
    40: "Ipswich",
    43: "Man City",
    49: "Sheffield United",
    54: "Fulham",
    56: "Sunderland",
    88: "Hull",
    90: "Burnley",
    91: "Bournemouth",
    94: "Brentford",
    102: "Luton",
}

# the-odds-api team names -> canonical
ODDS_API_ALIASES: dict[str, str] = {
    "Arsenal": "Arsenal",
    "Aston Villa": "Aston Villa",
    "AFC Bournemouth": "Bournemouth",
    "Bournemouth": "Bournemouth",
    "Brentford": "Brentford",
    "Brighton and Hove Albion": "Brighton",
    "Brighton & Hove Albion": "Brighton",
    "Burnley": "Burnley",
    "Chelsea": "Chelsea",
    "Coventry City": "Coventry",
    "Crystal Palace": "Crystal Palace",
    "Everton": "Everton",
    "Fulham": "Fulham",
    "Hull City": "Hull",
    "Ipswich Town": "Ipswich",
    "Leeds United": "Leeds",
    "Leicester City": "Leicester",
    "Liverpool": "Liverpool",
    "Luton Town": "Luton",
    "Manchester City": "Man City",
    "Manchester United": "Man United",
    "Newcastle United": "Newcastle",
    "Nottingham Forest": "Nott'm Forest",
    "Sheffield United": "Sheffield United",
    "Southampton": "Southampton",
    "Sunderland": "Sunderland",
    "Tottenham Hotspur": "Tottenham",
    "West Ham United": "West Ham",
    "Wolverhampton Wanderers": "Wolves",
}


def team_from_code(code: int, fallback: str | None = None) -> str:
    try:
        return FPL_CODE_TO_TEAM[int(code)]
    except (KeyError, ValueError, TypeError):
        if fallback is None:
            raise KeyError(f"Unknown FPL team code {code}; add it to FPL_CODE_TO_TEAM") from None
        return fallback


def team_from_odds_api(name: str) -> str:
    return ODDS_API_ALIASES.get(name, name)
