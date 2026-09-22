"""Parsers for Cricsheet ball-by-ball JSON.

Each function turns one part of a Cricsheet match file into warehouse rows.
The cricket rules encoded here are not obvious from the JSON - see the
docstrings for why each one exists.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.transformers import normalise_format

# Dismissals credited to the bowler. Run outs are not - the bowler had
# nothing to do with them. Retirements are not dismissals at all.
BOWLER_CREDITED = {"bowled", "caught", "lbw", "stumped",
                   "caught and bowled", "hit wicket"}

NOT_DISMISSALS = {"retired hurt", "retired not out"}

# One team, two names. Swaziland renamed itself Eswatini in 2018, and the
# T20I files use both (5 matches as Swaziland in 2021, the rest as
# Eswatini). Left alone they would be two teams in every head-to-head.
# Applied wherever a team NAME is turned into a team_id (03 and 04).
TEAM_ALIASES = {
    "Swaziland": "Eswatini",
}


def parse_outcome(outcome: dict) -> dict:
    """Flatten Cricsheet's outcome object into fact_match columns.

    Six shapes appear across the ODI archive:
        by + winner                   normal win           2767
        by + method + winner          win on D/L            260
        result only                   no winner             140
        eliminator + result           super over win          9
        method + result               no winner, D/L          5
        eliminator + method + result  super over on D/L       1

    An 'eliminator' match DOES have a winner - the tie was broken by a
    super over - but carries no 'winner' key. The 2019 World Cup Final is
    one of these. Reading only 'winner' silently discards ten real results.
    """
    winner = outcome.get("winner")
    eliminator = outcome.get("eliminator")
    method = outcome.get("method")
    result = outcome.get("result")
    by = outcome.get("by") or {}

    if winner:
        # 'by' always holds exactly one key: runs or wickets.
        victory_type, margin = next(iter(by.items()), (None, None))
        return {"winner": winner, "victory_type": victory_type,
                "victory_margin": margin, "victory_method": method}

    if eliminator:
        return {"winner": eliminator, "victory_type": "super over",
                "victory_margin": None, "victory_method": method}

    return {"winner": None, "victory_type": result,
            "victory_margin": None, "victory_method": method}


def parse_match_info(info: dict, match_id: int) -> dict:
    """Flatten Cricsheet's info block into one fact_match row.

    match_id comes from the filename - Cricsheet stores no id inside the file.
    """
    outcome = parse_outcome(info.get("outcome", {}))
    event = info.get("event") or {}
    toss = info.get("toss") or {}
    teams = info.get("teams") or []
    player_of_match = info.get("player_of_match") or []
    dates = info.get("dates") or [None]

    return {
        "match_id": match_id,
        "match_format": normalise_format(info.get("match_type")),
        "match_type_number": info.get("match_type_number"),
        "gender": info.get("gender"),
        "team_type": info.get("team_type"),
        # Cricsheet writes '2016/17' for split seasons and 2017 for single-year
        # ones. It's a label, not a number - coerce to string so the column has
        # one type.
        "season": (str(info["season"])
                   if info.get("season") is not None else None),
        "match_date": dates[0],          # Tests span days; [0] is the start
        "end_date": dates[-1],
        "venue": info.get("venue"),
        "city": info.get("city"),        # NULL on ~10% of matches
        "team1": teams[0] if len(teams) > 0 else None,
        "team2": teams[1] if len(teams) > 1 else None,
        "toss_winner": toss.get("winner"),
        "toss_decision": toss.get("decision"),
        "winner": outcome["winner"],
        "victory_type": outcome["victory_type"],
        "victory_margin": outcome["victory_margin"],
        "victory_method": outcome["victory_method"],
        "player_of_match": player_of_match[0] if player_of_match else None,
        "series_name": event.get("name"),
        "event_match_number": event.get("match_number"),
        "balls_per_over": info.get("balls_per_over"),
        "scheduled_overs": info.get("overs"),
    }


def parse_innings(innings: dict, innings_no: int) -> tuple[list, list]:
    """Aggregate one innings of deliveries into batting and bowling rows.

    Returns (batting_rows, bowling_rows) - one row per player per innings,
    the grain of fact_batting and fact_bowling.

    Six cricket rules are encoded here, none of them visible in the JSON:
      - a batter's runs are runs.batter, never runs.total
      - a wide is not a ball faced
      - a wide or no-ball is not a legal delivery
      - byes, leg-byes and penalties are not charged to the bowler
      - run outs are not credited to the bowler
      - retired hurt is not a dismissal
    """
    # A super over is a tiebreak, not an innings. Rows from it would give
    # players extra "innings" and corrupt every batting average.
    if innings.get("super_over"):
        return [], []

    batting_team = innings["team"]

    batting: dict[str, dict] = {}
    bowling: dict[str, dict] = {}
    order: list[str] = []

    def batter_row(name: str) -> dict:
        """Get or create a batter's row. Position = order of first appearance."""
        if name not in batting:
            order.append(name)
            batting[name] = {
                "player": name,
                "team": batting_team,
                "innings_no": innings_no,
                "batting_position": len(order),
                "runs_scored": 0,
                "balls_faced": 0,
                "fours": 0,
                "sixes": 0,
                "dismissal_kind": None,
                "dismissed_by": None,
                "fielder": None,
                "is_not_out": True,
            }
        return batting[name]

    def bowler_row(name: str) -> dict:
        if name not in bowling:
            bowling[name] = {
                "player": name,
                "innings_no": innings_no,
                "balls_bowled": 0,
                "runs_conceded": 0,
                "wickets": 0,
                "maidens": 0,
                "dots": 0,
            }
        return bowling[name]

    for over in innings.get("overs", []):
        over_runs_off_bat = 0
        over_illegal_balls = 0
        over_bowlers = set()

        for delivery in over["deliveries"]:
            runs = delivery["runs"]
            extras = delivery.get("extras", {})

            is_wide = "wides" in extras
            is_noball = "noballs" in extras

            striker = batter_row(delivery["batter"])
            batter_row(delivery["non_striker"])   # registers batting position
            bowler = bowler_row(delivery["bowler"])
            over_bowlers.add(delivery["bowler"])

            # ---- batting ------------------------------------------------
            striker["runs_scored"] += runs["batter"]

            if not is_wide:
                striker["balls_faced"] += 1

            # non_boundary marks 4s and 6s that were run, not hit to the rope
            if not runs.get("non_boundary"):
                if runs["batter"] == 4:
                    striker["fours"] += 1
                elif runs["batter"] == 6:
                    striker["sixes"] += 1

            # ---- bowling ------------------------------------------------
            if is_wide or is_noball:
                over_illegal_balls += 1
            else:
                bowler["balls_bowled"] += 1
                if runs["total"] == 0:
                    bowler["dots"] += 1

            bowler["runs_conceded"] += (runs["batter"]
                                        + extras.get("wides", 0)
                                        + extras.get("noballs", 0))

            over_runs_off_bat += runs["batter"]

            # ---- wickets ------------------------------------------------
            for wicket in delivery.get("wickets", []):
                kind = wicket["kind"]

                if kind in NOT_DISMISSALS:
                    continue

                dismissed = batter_row(wicket["player_out"])
                dismissed["is_not_out"] = False
                dismissed["dismissal_kind"] = kind

                fielders = wicket.get("fielders") or []
                if fielders:
                    first = fielders[0]
                    dismissed["fielder"] = (first.get("name")
                                            if isinstance(first, dict) else first)

                if kind in BOWLER_CREDITED:
                    dismissed["dismissed_by"] = delivery["bowler"]
                    bowler["wickets"] += 1

        # A maiden allows byes and leg-byes - not the bowler's fault - but
        # not wides or no-balls.
        if (over_runs_off_bat == 0 and over_illegal_balls == 0
                and len(over_bowlers) == 1):
            bowling[next(iter(over_bowlers))]["maidens"] += 1

    return list(batting.values()), list(bowling.values())