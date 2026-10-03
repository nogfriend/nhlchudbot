"""
Team filter configuration.

Set FILTER_TEAMS in the environment (or .env) to a comma-separated list of
NHL team abbreviations. Example:

    FILTER_TEAMS=TOR,MTL,BOS

When set:
  - Only games involving those teams are tracked.
  - Every goal in those games is posted (scored by your team OR against your team).

When empty or unset, every team is included (original behaviour).
"""

from __future__ import annotations

import os
from typing import FrozenSet, Optional

from dotenv import load_dotenv

from src.logger import log

VALID_ABBREVS = frozenset({
    "ANA", "BOS", "BUF", "CGY", "CAR", "CHI", "COL", "CBJ", "DAL", "DET",
    "EDM", "FLA", "LAK", "MIN", "MTL", "NSH", "NJD", "NYI", "NYR", "OTT",
    "PHI", "PIT", "SJS", "SEA", "STL", "TBL", "TOR", "UTA", "VAN", "VGK",
    "WSH", "WPG", "CAN", "USA", "SWE", "FIN",
})

_cached: Optional[FrozenSet[str]] = None
_logged_once = False


def get_filter_teams() -> FrozenSet[str]:
    """
    Return the set of team abbreviations the bot should care about.
    Empty set means "all teams".
    """
    global _cached, _logged_once
    if _cached is not None:
        return _cached

    load_dotenv()
    raw = os.getenv("FILTER_TEAMS", "") or ""
    # Strip quotes/spaces people accidentally paste into Render
    raw = raw.strip().strip('"').strip("'").strip()
    if not _logged_once:
        log.info("FILTER_TEAMS raw value: " + repr(raw if raw else "(empty)"))
        _logged_once = True

    if not raw:
        _cached = frozenset()
        log.info("FILTER_TEAMS not set — posting goals for ALL teams.")
        return _cached

    teams: set[str] = set()
    for part in raw.replace(";", ",").split(","):
        abbrev = part.strip().upper()
        if not abbrev:
            continue
        if abbrev not in VALID_ABBREVS:
            log.warning(
                f"FILTER_TEAMS: unknown abbreviation {abbrev!r} — ignored. "
                f"Valid examples: TOR, MTL, BOS, NYR, DET"
            )
            continue
        teams.add(abbrev)

    _cached = frozenset(teams)
    if _cached:
        log.info("FILTER_TEAMS active — only these teams: " + ", ".join(sorted(_cached)))
    else:
        log.info("FILTER_TEAMS was set but no valid abbreviations found — posting all teams.")
    return _cached


def is_team_filtered(abbreviation: Optional[str]) -> bool:
    """Return True if this team should be included (or no filter is set)."""
    teams = get_filter_teams()
    if not teams:
        return True
    if not abbreviation:
        return False
    return abbreviation.upper() in teams


def game_involves_filtered_team(home_abbrev: Optional[str], away_abbrev: Optional[str]) -> bool:
    """Return True if the game should be tracked."""
    teams = get_filter_teams()
    if not teams:
        return True
    home = (home_abbrev or "").upper()
    away = (away_abbrev or "").upper()
    return home in teams or away in teams
