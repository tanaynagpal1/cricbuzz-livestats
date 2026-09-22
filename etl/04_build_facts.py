"""
Assemble the five fact tables, ready for loading into PostgreSQL.

Everything up to now has produced parser output: tables that still carry
player and team NAMES. This script replaces every name with the id of the
dimension row it refers to, and drops the names. After this, a name appears
in exactly one place in the warehouse — the dimension that owns it.

Reads
-----
data/processed/matches_keyed.parquet   matches with venue/series/team/date keys
data/processed/match_extra.parquet     event stage and group
data/processed/innings.parquet         innings totals, extras, phases
data/processed/batting.parquet         player innings
data/processed/bowling.parquet         bowling spells
data/processed/partnerships.parquet    partnerships
data/processed/squads.parquet          team sheets, for player_of_match
data/processed/dim_team.parquet
data/processed/dim_player.parquet
data/processed/dim_venue.parquet
data/processed/dim_series.parquet
data/processed/dim_date.parquet

Writes
------
data/processed/fact_match.parquet
data/processed/fact_innings.parquet
data/processed/fact_batting.parquet
data/processed/fact_bowling.parquet
data/processed/fact_partnership.parquet

Run with:  python etl/04_build_facts.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from etl.cricsheet import TEAM_ALIASES


# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------

def find_root(start: Path | None = None) -> Path:
    """Walk up until we find the folder containing data/processed."""
    here = (start or Path(__file__).resolve()).parent
    for candidate in [here, *here.parents]:
        if (candidate / "data" / "processed").exists():
            return candidate
    raise FileNotFoundError("could not locate data/processed above " + str(here))


ROOT = find_root()
PROCESSED = ROOT / "data" / "processed"


def read(name: str) -> pd.DataFrame:
    return pd.read_parquet(PROCESSED / f"{name}.parquet")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def team_key(dim_team: pd.DataFrame) -> pd.Series:
    """(team_name, gender) -> team_id.

    Gender is part of the key because "England" is two international sides.
    A lookup on the name alone would merge them.
    """
    return dim_team.set_index(["team_name", "gender"])["team_id"]


def map_team(names: pd.Series, genders: pd.Series, lookup: pd.Series) -> pd.Series:
    # Same one-team-one-name rule as 03 (Swaziland -> Eswatini), applied
    # here because every fact table's team name passes through this line.
    names = names.replace(TEAM_ALIASES)
    idx = pd.MultiIndex.from_arrays([names, genders])
    return pd.Series(idx.map(lookup), index=names.index).astype("Int64")


# --------------------------------------------------------------------------
# fact_match
# --------------------------------------------------------------------------

def build_fact_match(mk: pd.DataFrame, extra: pd.DataFrame,
                     squads: pd.DataFrame) -> pd.DataFrame:
    """One row per match.

    match_id is Cricsheet's own id, kept as the primary key — a degenerate
    dimension. Inventing a surrogate for it would add a lookup and buy
    nothing, because the natural key is already stable and unique.
    """
    df = mk.copy()

    # player_of_match is the last name-shaped column. It resolves INSIDE the
    # match, using that match's own team sheets: within one match a name is
    # unambiguous, and it is only across matches that SR Taylor becomes two
    # different cricketers.
    lookup = (squads.drop_duplicates(["match_id", "player_name"])
              .set_index(["match_id", "player_name"])["player_id"])
    df["player_of_match_id"] = pd.MultiIndex.from_arrays(
        [df["match_id"], df["player_of_match"]]).map(lookup)

    df = df.merge(extra[["match_id", "event_stage", "event_group",
                         "event_match_number"]],
                  on="match_id", how="left", suffixes=("", "_x"))

    cols = ["match_id", "date_key", "match_date",
            "venue_id", "series_id",
            "team1_id", "team2_id", "toss_winner_id", "winner_id",
            "player_of_match_id",
            "toss_decision", "victory_type", "victory_margin",
            "victory_method", "gender", "match_format", "match_type_number",
            "season", "scheduled_overs", "balls_per_over",
            "event_stage", "event_group", "event_match_number"]
    out = df[[c for c in cols if c in df.columns]].copy()

    # 18 T20Is carry "overs: 50" in their metadata - a source slip; every
    # one of them was bowled as a 20-over match (checked against the ball
    # counts). A T20I is 20 overs a side by definition.
    t20 = out["match_format"].eq("T20I") & out["scheduled_overs"].gt(20)
    out.loc[t20, "scheduled_overs"] = 20

    for c in ["venue_id", "series_id", "team1_id", "team2_id",
              "toss_winner_id", "winner_id", "victory_margin",
              "scheduled_overs", "balls_per_over", "match_type_number",
              "date_key"]:
        if c in out.columns:
            out[c] = out[c].astype("Int64")

    return out


# --------------------------------------------------------------------------
# fact_innings
# --------------------------------------------------------------------------

def build_fact_innings(inn: pd.DataFrame, fm: pd.DataFrame,
                       lookup: pd.Series) -> pd.DataFrame:
    """One row per team's innings.

    bowling_team_id is derived rather than parsed: it is whichever of the
    match's two teams is not batting. Deriving it here, once, is safer than
    trusting a separate parse to agree.
    """
    df = inn.merge(fm[["match_id", "team1_id", "team2_id", "gender"]],
                   on="match_id", how="left")

    df["batting_team_id"] = map_team(df["batting_team"], df["gender"], lookup)
    df["bowling_team_id"] = np.where(
        df["batting_team_id"] == df["team1_id"],
        df["team2_id"], df["team1_id"])
    df["bowling_team_id"] = df["bowling_team_id"].astype("Int64")

    drop = ["batting_team", "team1_id", "team2_id", "gender"]
    df = df.drop(columns=[c for c in drop if c in df.columns])

    lead = ["match_id", "innings_no", "batting_team_id", "bowling_team_id"]
    return df[lead + [c for c in df.columns if c not in lead]]


# --------------------------------------------------------------------------
# fact_batting / fact_bowling
# --------------------------------------------------------------------------

def build_fact_batting(bat: pd.DataFrame, fm: pd.DataFrame,
                       lookup: pd.Series) -> pd.DataFrame:
    df = bat.merge(fm[["match_id", "gender"]], on="match_id", how="left")
    df["team_id"] = map_team(df["team"], df["gender"], lookup)

    cols = ["match_id", "innings_no", "player_id", "team_id",
            "batting_position", "runs_scored", "balls_faced",
            "fours", "sixes", "is_not_out",
            "dismissal_kind", "dismissed_by_id", "fielder_id"]
    return df[cols].copy()


def build_fact_bowling(bwl: pd.DataFrame, fm: pd.DataFrame,
                       lookup: pd.Series) -> pd.DataFrame:
    df = bwl.merge(fm[["match_id", "gender"]], on="match_id", how="left")
    df["team_id"] = map_team(df["team"], df["gender"], lookup)

    cols = ["match_id", "innings_no", "player_id", "team_id",
            "balls_bowled", "runs_conceded", "wickets", "maidens", "dots"]
    return df[cols].copy()


# --------------------------------------------------------------------------
# fact_partnership
# --------------------------------------------------------------------------

def build_fact_partnership(pt: pd.DataFrame, fi: pd.DataFrame) -> pd.DataFrame:
    """One row per partnership, with the batting team attached.

    The team comes from fact_innings rather than being parsed again — one
    source, so the two cannot disagree.
    """
    df = pt.merge(fi[["match_id", "innings_no", "batting_team_id"]],
                  on=["match_id", "innings_no"], how="left")

    cols = ["match_id", "innings_no", "wicket_no", "batting_team_id",
            "batter1_id", "batter2_id", "runs", "balls", "unbroken"]
    return df[cols].copy()


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

def verify(facts: dict[str, pd.DataFrame], dims: dict[str, pd.DataFrame]) -> bool:
    """The constraints PostgreSQL will enforce on load, checked first.

    A failure here reads as a sentence. The same failure on Day 6 reads as a
    constraint violation halfway through a bulk insert, with the transaction
    rolled back and no clue which row caused it.
    """
    ok = True

    def check(label: str, actual: int, expected: int = 0):
        nonlocal ok
        good = actual == expected
        ok = ok and good
        print(f"  [{'PASS' if good else 'FAIL'}] {label}: {actual}")

    def fk(label: str, child, parent):
        missing = set(pd.Series(child).dropna()) - set(parent)
        check(label, len(missing))

    fm, fi = facts["fact_match"], facts["fact_innings"]
    fb, fw, fp = (facts["fact_batting"], facts["fact_bowling"],
                  facts["fact_partnership"])
    players = dims["dim_player"]["player_id"]
    teams = dims["dim_team"]["team_id"]

    print("\nverification")

    # --- primary keys ---
    check("fact_match duplicate match_id",
          int(fm.duplicated("match_id").sum()))
    check("fact_innings duplicate PK",
          int(fi.duplicated(["match_id", "innings_no"]).sum()))
    check("fact_batting duplicate PK",
          int(fb.duplicated(["match_id", "innings_no", "player_id"]).sum()))
    check("fact_bowling duplicate PK",
          int(fw.duplicated(["match_id", "innings_no", "player_id"]).sum()))
    check("fact_partnership duplicate PK",
          int(fp.duplicated(["match_id", "innings_no", "wicket_no"]).sum()))

    # --- foreign keys ---
    fk("fact_match.venue_id", fm["venue_id"], dims["dim_venue"]["venue_id"])
    fk("fact_match.series_id", fm["series_id"], dims["dim_series"]["series_id"])
    fk("fact_match.date_key", fm["date_key"], dims["dim_date"]["date_key"])
    for c in ["team1_id", "team2_id", "toss_winner_id", "winner_id"]:
        fk(f"fact_match.{c}", fm[c], teams)
    fk("fact_match.player_of_match_id", fm["player_of_match_id"], players)

    fk("fact_innings.match_id", fi["match_id"], fm["match_id"])
    fk("fact_innings.batting_team_id", fi["batting_team_id"], teams)
    fk("fact_innings.bowling_team_id", fi["bowling_team_id"], teams)

    fk("fact_batting.match_id", fb["match_id"], fm["match_id"])
    fk("fact_batting.player_id", fb["player_id"], players)
    fk("fact_batting.dismissed_by_id", fb["dismissed_by_id"], players)
    fk("fact_batting.fielder_id", fb["fielder_id"], players)
    fk("fact_batting.team_id", fb["team_id"], teams)

    fk("fact_bowling.match_id", fw["match_id"], fm["match_id"])
    fk("fact_bowling.player_id", fw["player_id"], players)
    fk("fact_bowling.team_id", fw["team_id"], teams)

    fk("fact_partnership.batter1_id", fp["batter1_id"], players)
    fk("fact_partnership.batter2_id", fp["batter2_id"], players)
    fk("fact_partnership.batting_team_id", fp["batting_team_id"], teams)

    # --- nothing unresolved ---
    check("fact_innings rows with no batting team",
          int(fi["batting_team_id"].isna().sum()))
    check("fact_batting rows with no team",
          int(fb["team_id"].isna().sum()))
    check("fact_bowling rows with no team",
          int(fw["team_id"].isna().sum()))

    # --- cross-table reconciliation ---
    # innings.runs_off_bat and the sum of every batter's runs in that innings
    # are produced by two separate scripts reading the same deliveries. If
    # they agree on every innings, both parsers are right.
    bat_runs = (fb.groupby(["match_id", "innings_no"])["runs_scored"]
                .sum().rename("bat_sum"))
    joined = fi.set_index(["match_id", "innings_no"])[["runs_off_bat"]].join(bat_runs)
    joined["bat_sum"] = joined["bat_sum"].fillna(0)
    check("innings runs_off_bat vs sum of batting rows",
          int((joined["runs_off_bat"] != joined["bat_sum"]).sum()))

    # Same idea for partnerships: they should sum to the innings total.
    part_runs = fp.groupby(["match_id", "innings_no"])["runs"].sum().rename("part_sum")
    j2 = fi.set_index(["match_id", "innings_no"])[["runs_total"]].join(part_runs)
    j2["part_sum"] = j2["part_sum"].fillna(0)
    check("innings runs_total vs sum of partnerships",
          int((j2["runs_total"] != j2["part_sum"]).sum()))

    return ok


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> int:
    print(f"project root: {ROOT}")

    mk = read("matches_keyed")
    extra = read("match_extra")
    inn = read("innings")
    bat = read("batting")
    bwl = read("bowling")
    pt = read("partnerships")
    squads = read("squads")

    dims = {name: read(name) for name in
            ["dim_player", "dim_team", "dim_venue", "dim_series", "dim_date"]}

    lookup = team_key(dims["dim_team"])

    fm = build_fact_match(mk, extra, squads)
    fi = build_fact_innings(inn, fm, lookup)
    fb = build_fact_batting(bat, fm, lookup)
    fw = build_fact_bowling(bwl, fm, lookup)
    fp = build_fact_partnership(pt, fi)

    facts = {
        "fact_match": fm,
        "fact_innings": fi,
        "fact_batting": fb,
        "fact_bowling": fw,
        "fact_partnership": fp,
    }

    for name, df in facts.items():
        print(f"  {name:18s} {len(df):>7,} rows  {len(df.columns):>2} columns")

    if not verify(facts, dims):
        print("\nverification FAILED - nothing written")
        return 1

    print()
    for name, df in facts.items():
        path = PROCESSED / f"{name}.parquet"
        df.to_parquet(path, index=False)
        print(f"  wrote {name}.parquet  {len(df):>7,} rows  "
              f"{path.stat().st_size / 1_048_576:5.1f} MB")

    total = sum((PROCESSED / f"{n}.parquet").stat().st_size
                for n in list(facts) + list(dims)) / 1_048_576
    print(f"\nwarehouse on disk (parquet): {total:.1f} MB")

    print("\ndone")
    return 0


if __name__ == "__main__":
    sys.exit(main())