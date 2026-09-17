"""
Build the five conformed dimensions from the parsed Cricsheet output.

Reads
-----
data/processed/matches.parquet          one row per match  (02_parse_matches.py)
data/processed/squads.parquet           one row per team-sheet entry
data/processed/batting.parquet          one row per player innings
data/processed/bowling.parquet          one row per bowling spell
data/processed/people.parquet           Cricsheet player registry
etl/reference/venues_manual.csv         hand-corrected venue names/cities/countries
etl/reference/venue_capacity.csv        frozen Wikipedia capacity snapshot
etl/reference/venue_capacity_manual.csv capacities researched by hand

Writes
------
data/processed/dim_venue.parquet
data/processed/dim_team.parquet
data/processed/dim_series.parquet
data/processed/dim_date.parquet
data/processed/dim_player.parquet
data/processed/matches_keyed.parquet    matches with every foreign key attached

Design notes
------------
* No network access. Capacities were fetched from Wikipedia once and frozen
  into etl/reference/. An ETL that reads a live web page produces different
  answers on different days, which is not an ETL. Delete the snapshot and
  re-run the notebook step to deliberately refresh it.
* Every lookup table below encodes a decision that was verified against the
  data. The comments say WHY; the what is already obvious from the code.
* verify() runs every time and NOTHING is written if it fails. A pipeline
  that writes bad data and reports it afterwards is worse than one that
  refuses.
* Run with:  python etl/03_build_dimensions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------

def find_root(start: Path | None = None) -> Path:
    """Walk up until we find the folder containing data/processed.

    A relative path is relative to where the program was STARTED, not to
    where the file lives, so the same string means different folders when
    run from a notebook versus from the repo root. Resolving the root once
    removes the whole class of problem.
    """
    here = (start or Path(__file__).resolve()).parent
    for candidate in [here, *here.parents]:
        if (candidate / "data" / "processed").exists():
            return candidate
    raise FileNotFoundError("could not locate data/processed above " + str(here))


ROOT = find_root()
PROCESSED = ROOT / "data" / "processed"
REFERENCE = ROOT / "etl" / "reference"

# The largest cricket ground in the world holds 132,000. Anything above this
# is a source error - usually a record attendance typed into the capacity
# column. Bad data arrives looking exactly like good data, so external
# figures get a plausibility bound.
MAX_PLAUSIBLE_CAPACITY = 150_000


# --------------------------------------------------------------------------
# venue lookup tables
# --------------------------------------------------------------------------

# Three separate failure modes live in the city column, each needing a
# different judgement. Grouped so the reasoning survives.
CITY_ALIASES = {
    # (1) an island or country written where a city belongs - all Caribbean
    "Jamaica": "Kingston",
    "Barbados": "Bridgetown",
    "Trinidad": "Port of Spain",
    "Grenada": "St George's",
    "Guyana": "Providence",
    "Antigua": "North Sound",
    "St Kitts": "Basseterre",
    "St Lucia": "Gros Islet",
    "St Vincent": "Kingstown",

    # (2) real-world renames - we keep the current official name
    "Bangalore": "Bengaluru",
    "Port Elizabeth": "Gqeberha",
    "Chittagong": "Chattogram",
    "Dharmasala": "Dharamsala",          # spelling drift, not a rename

    # (3) a neighbourhood recorded instead of its city
    "Mirpur": "Dhaka",
    "Brighton": "Hove",                  # the ground is always called Hove
}

# Punctuation drift that splitting on the comma cannot see.
VENUE_NAME_ALIASES = {
    "M.Chinnaswamy Stadium": "M Chinnaswamy Stadium",
    "R.Premadasa Stadium": "R Premadasa Stadium",
}

# One ground, one loosely recorded match. A global "Toronto" -> "King City"
# rule would be wrong (Toronto is a real city), so this is keyed on the
# venue AND the city together. Narrow rules for narrow problems.
VENUE_CITY_OVERRIDES = {
    ("Maple Leaf North-West Ground", "Toronto"): "King City",
}

# Same ground recorded under two names.
VENUE_MERGES = {
    # --- sponsor names ---
    "The Royal & Sun Alliance County Ground": "County Ground",
    "The Cooper Associates County Ground": "County Ground",
    "De Beers Diamond Oval": "Diamond Oval",
    "Boland Bank Park": "Boland Park",
    "Sedgars Park": "Senwes Park",
    "AMI Stadium": "Jade Stadium",
    "Sky Stadium": "Westpac Stadium",
    "Choice Moosa Stadium": "Moosa Cricket Stadium",
    "Bundaberg Rum Stadium": "Cazaly's Stadium",

    # Bloemfontein: one ground, four sponsors over twenty years.
    "Goodyear Park": "Mangaung Oval",
    "Chevrolet Park": "Mangaung Oval",
    "OUTsurance Oval": "Mangaung Oval",

    # --- official renames ---
    "Khettarama Stadium": "R Premadasa Stadium",
    "Punjab Cricket Association Stadium":
        "Punjab Cricket Association IS Bindra Stadium",
    "Sharjah Cricket Association Stadium": "Sharjah Cricket Stadium",
    "Narayanganj Osmani Stadium": "Khan Shaheb Osman Ali Stadium",
    "Feroz Shah Kotla": "Arun Jaitley Stadium",
    "Sardar Patel Stadium": "Narendra Modi Stadium",
    "Malahide": "The Village",
    "North West Cricket Stadium": "Senwes Park",
    "Westpac Park": "Seddon Park",
    "Queen's Park (New)": "Queen's Park",

    # Renamed in 2016 for St Lucia's World Cup-winning captain. Zero string
    # similarity to its old name - only domain knowledge finds this one.
    "Beausejour Stadium": "Daren Sammy National Cricket Stadium",

    # --- spelling ---
    "Darren Sammy National Cricket Stadium":
        "Daren Sammy National Cricket Stadium",
    "Bharat Ratna Shri Atal Bihari Vajpai Ekana Cricket Stadium":
        "Bharat Ratna Shri Atal Bihari Vajpayee Ekana Cricket Stadium",
    "Zohur Ahmed Chowdhury Stadium": "Zahur Ahmed Chowdhury Stadium",
    "Sher-e-Bangla National Cricket Stadium": "Shere Bangla National Stadium",
    "Vidarbha C.A. Ground": "Vidarbha Cricket Association Ground",

    # --- same name, extra or missing words ---
    "Sinhalese Sports Club": "Sinhalese Sports Club Ground",
    "Grange Cricket Club": "Grange Cricket Club Ground",
    "VRA Cricket Ground": "VRA Ground",
    "Sardar Patel (Gujarat) Stadium": "Sardar Patel Stadium",
    "ICC Global Cricket Academy": "ICC Academy",
    "New Wanderers Stadium": "The Wanderers Stadium",
    "Zayed Cricket Stadium": "Sheikh Zayed Stadium",
    "Dubai Sports City Cricket Stadium": "Dubai International Cricket Stadium",
    "Davies Park": "John Davies Oval",
}

# Ten Caribbean nations field one international side. country says where the
# ground IS; home_nation says who plays there. Keeping them apart lets the
# geography stay honest and the join stay reliable.
WEST_INDIES = {
    "Antigua and Barbuda", "Barbados", "Dominica", "Grenada", "Guyana",
    "Jamaica", "Saint Kitts and Nevis", "Saint Lucia",
    "Saint Vincent and the Grenadines", "Trinidad and Tobago",
}

# The venue country spelling must match the team name or the home-advantage
# join silently returns nothing - no error, just a wrong answer.
HOME_NATION_FIXES = {
    "The Netherlands": "Netherlands",
    "United States": "United States of America",
}

# Hosts that field no ODI side. NULL is the honest value: a string that
# looks joinable and never joins is worse than a blank.
NO_HOME_SIDE = {"Spain", "Malaysia"}


# --------------------------------------------------------------------------
# series lookup tables
# --------------------------------------------------------------------------

# Cricsheet changed its own naming convention over the years. The seasons do
# not overlap, so these are the same competitions, not different ones.
SERIES_ALIASES = {
    "ICC World Cup": "ICC Cricket World Cup",
    "World Cup": "ICC Cricket World Cup",
    "ICC World Cup Qualifiers": "ICC Cricket World Cup Qualifier",
    "ICC Cricket World Cup Qualifier (ICC Trophy)":
        "ICC Cricket World Cup Qualifier",
    "ICC Women's Cricket World Cup Qualifier": "ICC Women's World Cup Qualifier",
    "ICC Women's World Cup Qualifying Series": "ICC Women's World Cup Qualifier",
}

UNKNOWN_SERIES_ID = 0
UNKNOWN_SERIES_NAME = "No series recorded"


# --------------------------------------------------------------------------
# venue dimension
# --------------------------------------------------------------------------

def build_venue(matches: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (dim_venue, matches) with venue_id attached.

    382 raw venue strings collapse to 226 real grounds. The strings carry
    the city, and sometimes the country, after a comma - which is where most
    of the apparently-missing city values were hiding.
    """
    manual = pd.read_csv(REFERENCE / "venues_manual.csv")
    manual["venue"] = manual["venue"].str.strip()

    country_map = manual.drop_duplicates("venue").set_index("venue")["country"]
    city_map = (manual.dropna(subset=["city"])
                      .drop_duplicates("venue")
                      .set_index("venue")["city"])

    # 1. "Sabina Park, Kingston, Jamaica" -> "Sabina Park"
    base_name = matches["venue"].str.split(",").str[0].str.strip()

    # 2. Country comes from the hand-corrected file, keyed on that name.
    matches["venue_country"] = base_name.map(country_map)

    # 3. City: three sources, best first. The match record, then the venue
    #    string's own second comma-part, then the spreadsheet.
    city_from_string = matches["venue"].str.split(",").str[1].str.strip()
    matches["city_final"] = (matches["city"]
                             .fillna(city_from_string)
                             .fillna(base_name.map(city_map))
                             .replace(CITY_ALIASES))

    # 4. Name: punctuation drift, then same-ground merges. Applied
    #    repeatedly until nothing changes, because pandas replace does ONE
    #    pass: a two-step rename (Sardar Patel (Gujarat) -> Sardar Patel ->
    #    Narendra Modi) would otherwise stop halfway.
    name = base_name.replace(VENUE_NAME_ALIASES)
    for _ in range(5):
        stepped = name.replace(VENUE_MERGES)
        if stepped.equals(name):
            break
        name = stepped
    matches["venue_clean"] = name

    # 5. Venue-specific city corrections, after the merges so the key on the
    #    left-hand side is the final venue name.
    matches["city_final"] = [
        VENUE_CITY_OVERRIDES.get((v, c), c)
        for v, c in zip(matches["venue_clean"], matches["city_final"])
    ]

    dim = (matches
           .groupby(["venue_clean", "city_final", "venue_country"], dropna=False)
           .agg(matches_played=("match_id", "size"))
           .reset_index()
           .sort_values(["venue_clean", "city_final"])
           .reset_index(drop=True))

    dim["home_nation"] = (dim["venue_country"]
                          .apply(lambda c: "West Indies" if c in WEST_INDIES else c)
                          .replace(HOME_NATION_FIXES))
    dim.loc[dim["home_nation"].isin(NO_HOME_SIDE), "home_nation"] = None

    # --- capacity, pass 1: the frozen Wikipedia snapshot, name + city ---
    cap = pd.read_csv(REFERENCE / "venue_capacity.csv")
    cap_lookup = cap.set_index(["venue_name", "city"])
    idx = pd.MultiIndex.from_arrays([dim["venue_clean"], dim["city_final"]])
    dim["capacity"] = pd.Series(idx.map(cap_lookup["capacity"]), index=dim.index)
    dim["capacity_source"] = pd.Series(idx.map(cap_lookup["capacity_source"]),
                                       index=dim.index)

    absurd = dim["capacity"] > MAX_PLAUSIBLE_CAPACITY
    if absurd.any():
        print(f"    dropped {int(absurd.sum())} implausible capacity values")
    dim.loc[absurd, "capacity"] = None
    dim.loc[absurd, "capacity_source"] = None

    # Sorted first, so re-running the ETL always produces the same ids. An
    # id that shuffles between runs breaks every foreign key.
    dim.insert(0, "venue_id", range(1, len(dim) + 1))

    # Former names, built from the DATA rather than the merge table: for
    # each ground, the names it was actually recorded under. Keyed on
    # (venue, city), so Taunton does not inherit Bristol's sponsor.
    seen = (matches.assign(_orig=base_name)
            .groupby(["venue_clean", "city_final"])["_orig"]
            .agg(lambda s: sorted(set(s)))
            .to_dict())
    dim["former_names"] = [
        ", ".join(n for n in seen.get((v, c), []) if n != v) or None
        for v, c in zip(dim["venue_clean"], dim["city_final"])
    ]

    # A ground whose name is not unique needs its city shown alongside, or a
    # dropdown lists "County Ground" seven times.
    ambiguous = set(dim["venue_clean"].value_counts().loc[lambda s: s > 1].index)
    dim["venue_display"] = [
        f"{v}, {c}" if v in ambiguous else v
        for v, c in zip(dim["venue_clean"], dim["city_final"])
    ]

    # --- capacity, pass 2: researched by hand where Wikipedia has nothing ---
    # Keyed on venue_display, because that is what a human reads: it carries
    # the city for the seven County Grounds and four Nehru Stadiums, which a
    # bare name cannot tell apart.
    manual_path = REFERENCE / "venue_capacity_manual.csv"
    if manual_path.exists():
        man = pd.read_csv(manual_path)
        before = int(dim["capacity"].notna().sum())
        gap = dim["capacity"].isna()
        dim.loc[gap, "capacity"] = dim.loc[gap, "venue_display"].map(
            man.set_index("venue_display")["capacity"])
        dim.loc[gap, "capacity_source"] = dim.loc[gap, "venue_display"].map(
            man.set_index("venue_display")["capacity_source"])
        print(f"    filled {int(dim['capacity'].notna().sum()) - before} "
              f"capacities by hand")

        # A manual row matching no venue is a typo - and a silent one,
        # because a failed lookup just leaves the capacity blank.
        stray = sorted(set(man["venue_display"]) - set(dim["venue_display"]))
        if stray:
            print(f"    WARNING: {len(stray)} manual rows matched no venue:")
            for s in stray:
                print(f"      {s}")

    lookup = dim.set_index(["venue_clean", "city_final"])["venue_id"]
    matches["venue_id"] = pd.MultiIndex.from_arrays(
        [matches["venue_clean"], matches["city_final"]]).map(lookup)

    dim = dim.rename(columns={"venue_clean": "venue_name",
                              "city_final": "city",
                              "venue_country": "country"})
    dim = dim[["venue_id", "venue_name", "venue_display", "former_names",
               "city", "country", "home_nation", "capacity",
               "capacity_source", "matches_played"]]
    return dim, matches


# --------------------------------------------------------------------------
# team dimension
# --------------------------------------------------------------------------

def build_team(matches: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (dim_team, matches) with the four team foreign keys attached.

    Keyed on (team_name, gender). "England" is two different international
    sides; merging them would blend two separate competitions in every
    head-to-head and home-advantage answer. Thailand proves the point from
    the other direction: 17 women's matches and no men's side at all.
    """
    long = pd.concat([
        matches[["team1", "gender"]].rename(columns={"team1": "team_name"}),
        matches[["team2", "gender"]].rename(columns={"team2": "team_name"}),
    ])

    dim = (long.dropna(subset=["team_name"])
           .groupby(["team_name", "gender"]).size()
           .reset_index(name="matches_played")
           .sort_values(["team_name", "gender"])
           .reset_index(drop=True))

    dim.insert(0, "team_id", range(1, len(dim) + 1))
    dim["team_display"] = [
        n if g == "male" else f"{n} Women"
        for n, g in zip(dim["team_name"], dim["gender"])
    ]

    lookup = dim.set_index(["team_name", "gender"])["team_id"]
    for col in ["team1", "team2", "toss_winner", "winner"]:
        matches[f"{col}_id"] = pd.MultiIndex.from_arrays(
            [matches[col], matches["gender"]]).map(lookup)

    return dim, matches


# --------------------------------------------------------------------------
# series dimension
# --------------------------------------------------------------------------

def build_series(matches: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (dim_series, matches) with series_id attached.

    Grain is one row per EDITION - (series, season, gender) - so the 2011
    and 2023 World Cups are separate rows rather than one bucket.

    The 14 matches with no series are genuine one-off fixtures. They get an
    Unknown member rather than a NULL foreign key, because an INNER JOIN to
    a NULL key drops those rows silently: no error, just 3,168 rows where
    there should be 3,182.
    """
    matches["series_clean"] = matches["series_name"].replace(SERIES_ALIASES)
    matches["season_start"] = (matches["season"].astype(str)
                               .str.slice(0, 4).astype(int))

    named = matches[matches["series_name"].notna()]

    dim = (named.groupby(["series_clean", "season", "gender"])
           .agg(matches_played=("match_id", "size"),
                season_start=("season_start", "first"),
                first_match=("match_date", "min"),
                last_match=("match_date", "max"))
           .reset_index()
           .sort_values(["season_start", "series_clean"])
           .reset_index(drop=True))
    dim.insert(0, "series_id", range(1, len(dim) + 1))

    unknown = pd.DataFrame([{
        "series_id": UNKNOWN_SERIES_ID,
        "series_clean": UNKNOWN_SERIES_NAME,
        "season": None,
        "gender": None,
        "matches_played": int(matches["series_name"].isna().sum()),
        "season_start": None,
        "first_match": None,
        "last_match": None,
    }])
    dim = pd.concat([unknown, dim], ignore_index=True)

    lookup = dim.set_index(["series_clean", "season", "gender"])["series_id"]
    matches["series_id"] = pd.MultiIndex.from_arrays(
        [matches["series_clean"], matches["season"], matches["gender"]]
    ).map(lookup)
    matches["series_id"] = (matches["series_id"]
                            .fillna(UNKNOWN_SERIES_ID).astype(int))

    dim = dim.rename(columns={"series_clean": "series_name"})
    return dim, matches


# --------------------------------------------------------------------------
# date dimension
# --------------------------------------------------------------------------

def build_date(matches: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (dim_date, matches) with date_key attached.

    One row per CALENDAR DAY across the whole range, not one per day that
    had a match. That is what lets "matches per quarter" show a quarter with
    zero matches instead of skipping it entirely.
    """
    matches["match_date"] = pd.to_datetime(matches["match_date"])

    rng = pd.date_range(matches["match_date"].min().normalize(),
                        matches["match_date"].max().normalize(), freq="D")

    dim = pd.DataFrame({"full_date": rng})
    dim.insert(0, "date_key", dim["full_date"].dt.strftime("%Y%m%d").astype(int))
    dim["year"] = dim["full_date"].dt.year
    dim["quarter"] = dim["full_date"].dt.quarter
    dim["month"] = dim["full_date"].dt.month
    dim["month_name"] = dim["full_date"].dt.month_name()
    dim["day"] = dim["full_date"].dt.day
    dim["day_name"] = dim["full_date"].dt.day_name()
    dim["is_weekend"] = dim["full_date"].dt.dayofweek >= 5

    matches["date_key"] = (matches["match_date"].dt.strftime("%Y%m%d")
                           .astype("Int64"))
    return dim, matches


# --------------------------------------------------------------------------
# player dimension
# --------------------------------------------------------------------------

def classify_role(row) -> str:
    """Order matters.

    Bowling is checked first because a keeper cannot bowl while keeping, so
    a high bowl_share means the gloves were incidental.

    Keepers are identified by dismissal RATE, not by stumpings. Stumpings
    only happen off spin, so a stumping count measures how much spin a team
    bowled rather than who kept wicket - tested, and it demoted a dozen
    genuine keepers (Pant, Pooran, Bairstow) to fix one debatable case.

    Known limitation: AB de Villiers classifies as a keeper at 0.84. Any
    threshold that excludes him also excludes Liton Das, Umar Akmal,
    Brendan Taylor and Kusal Mendis, who are specialists. Fixing one
    debatable case by breaking four clear ones is a bad trade.
    """
    if row["matches_batted"] == 0 and row["matches_bowled"] == 0:
        return "Unknown"
    if row["bowl_share"] >= 0.40:
        return "All-rounder" if row["avg_position"] <= 7 else "Bowler"
    if row["dismissal_rate"] >= 0.70:
        return "Wicket-keeper"
    return "Batsman"


def build_player(matches: pd.DataFrame) -> pd.DataFrame:
    """Return dim_player, keyed on Cricsheet's own stable player_id.

    The registry must NOT define the population: it also contains umpires
    and match referees, which is where a 568-row discrepancy came from.

    But team sheets alone are not enough either. They say who was SELECTED,
    and a substitute fielder can take a catch without being in the XI - 17
    such players, 23 catches. So the population is every player the FACTS
    refer to, with matches_played = 0 marking those never selected.
    """
    squads = pd.read_parquet(PROCESSED / "squads.parquet")
    people = pd.read_parquet(PROCESSED / "people.parquet")
    batting = pd.read_parquet(PROCESSED / "batting.parquet")
    bowling = pd.read_parquet(PROCESSED / "bowling.parquet")

    referenced = pd.unique(pd.concat([
        squads["player_id"],
        batting["player_id"], batting["dismissed_by_id"], batting["fielder_id"],
        bowling["player_id"],
    ]).dropna())

    appearances = (squads.groupby("player_id")["match_id"]
                   .nunique().rename("matches_played"))

    dim = pd.DataFrame({"player_id": sorted(referenced)})
    dim = dim.merge(appearances, left_on="player_id",
                    right_index=True, how="left")
    dim["matches_played"] = dim["matches_played"].fillna(0).astype(int)

    # unique_name from the register is unique by construction; the squad
    # spelling is the fallback for anyone the register misses.
    name_map = people.set_index("cricsheet_id")["player_name"]
    fallback = squads.groupby("player_id")["player_name"].agg(
        lambda s: s.value_counts().index[0])
    dim["player_name"] = (dim["player_id"].map(name_map)
                          .fillna(dim["player_id"].map(fallback)))

    squads["gender"] = squads["match_id"].map(
        matches.set_index("match_id")["gender"])
    squads["match_date"] = squads["match_id"].map(
        matches.set_index("match_id")["match_date"])

    agg = (squads.groupby("player_id")
           .agg(gender=("gender", lambda s: s.mode().iloc[0]),
                primary_team=("team", lambda s: s.value_counts().index[0]),
                teams_played_for=("team", "nunique"),
                debut=("match_date", "min"),
                last_match=("match_date", "max"))
           .reset_index())
    dim = dim.merge(agg, on="player_id", how="left")

    # Substitutes have no squad row, so their gender comes from the match
    # they actually appeared in. Left NULL, the men's/women's filter would
    # silently drop their catches.
    sub_ctx = (batting.dropna(subset=["fielder_id"])[["fielder_id", "match_id"]]
               .rename(columns={"fielder_id": "player_id"}))
    sub_ctx["gender"] = sub_ctx["match_id"].map(
        matches.set_index("match_id")["gender"])
    sub_gender = sub_ctx.groupby("player_id")["gender"].agg(
        lambda s: s.mode().iloc[0] if len(s.mode()) else None)
    dim["gender"] = dim["gender"].fillna(dim["player_id"].map(sub_gender))

    signals = [
        bowling.groupby("player_id")["match_id"].nunique().rename("matches_bowled"),
        batting.groupby("player_id")["match_id"].nunique().rename("matches_batted"),
        batting.groupby("player_id")["batting_position"].mean().rename("avg_position"),
        (batting[batting["dismissal_kind"].isin(["caught", "stumped"])]
         .groupby("fielder_id").size().rename("catches_stumpings")),
    ]
    for s in signals:
        dim = dim.merge(s, left_on="player_id", right_index=True, how="left")

    counts = ["matches_bowled", "matches_batted", "catches_stumpings"]
    dim[counts] = dim[counts].fillna(0)

    # A substitute has matches_played = 0, and 0/0 is not a ratio - it is
    # unknown. A NULL denominator gives NULL, which is the honest answer.
    denom = dim["matches_played"].replace(0, pd.NA)
    dim["bowl_share"] = dim["matches_bowled"] / denom
    dim["dismissal_rate"] = dim["catches_stumpings"] / denom
    dim["playing_role"] = dim.apply(classify_role, axis=1)

    # Deferred to Day 12 - Wikipedia / Wikidata enrichment via cricinfo id.
    dim["batting_style"] = None
    dim["bowling_style"] = None

    return dim.sort_values("player_name").reset_index(drop=True)


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

def verify(matches, dim_venue, dim_team, dim_series, dim_date, dim_player) -> bool:
    """Every check that has caught a real bug during development.

    These are the same constraints Postgres will enforce on load, run early
    so a failure reads as a sentence rather than as a constraint violation
    halfway through a bulk insert. A silent wrong answer is the expensive
    failure mode, so they run every time.
    """
    ok = True

    def check(label: str, actual: int, expected: int = 0):
        nonlocal ok
        good = actual == expected
        ok = ok and good
        print(f"  [{'PASS' if good else 'FAIL'}] {label}: {actual}")

    def fk(label: str, child, parent):
        """Valid when every non-null child value exists in the parent."""
        missing = set(pd.Series(child).dropna()) - set(parent)
        check(label, len(missing))

    print("\nverification")

    # --- keys attached to every match ---
    check("matches with no venue_id", int(matches["venue_id"].isna().sum()))
    check("matches with no date_key", int(matches["date_key"].isna().sum()))
    check("matches with no series_id", int(matches["series_id"].isna().sum()))
    for col in ["team1", "team2", "toss_winner", "winner"]:
        unresolved = int((matches[col].notna() & matches[f"{col}_id"].isna()).sum())
        check(f"{col} unresolved", unresolved)

    # --- referential integrity, match level ---
    fk("matches.venue_id -> dim_venue", matches["venue_id"], dim_venue["venue_id"])
    fk("matches.series_id -> dim_series", matches["series_id"], dim_series["series_id"])
    fk("matches.date_key -> dim_date", matches["date_key"], dim_date["date_key"])

    # --- referential integrity, fact level ---
    batting = pd.read_parquet(PROCESSED / "batting.parquet")
    bowling = pd.read_parquet(PROCESSED / "bowling.parquet")
    players = dim_player["player_id"]

    fk("batting.match_id -> matches", batting["match_id"], matches["match_id"])
    fk("bowling.match_id -> matches", bowling["match_id"], matches["match_id"])
    fk("batting.player_id -> dim_player", batting["player_id"], players)
    fk("batting.dismissed_by_id -> dim_player", batting["dismissed_by_id"], players)
    fk("batting.fielder_id -> dim_player", batting["fielder_id"], players)
    fk("bowling.player_id -> dim_player", bowling["player_id"], players)

    # --- totals and sanity bounds ---
    check("venue match total", int(dim_venue["matches_played"].sum()), len(matches))
    check("capacities above the plausible maximum",
          int((dim_venue["capacity"] > MAX_PLAUSIBLE_CAPACITY).sum()))
    check("duplicate venue (name, city)",
          int(dim_venue.duplicated(["venue_name", "city"]).sum()))
    check("duplicate player_id", int(dim_player.duplicated("player_id").sum()))
    check("players with no name", int(dim_player["player_name"].isna().sum()))

    return ok


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> int:
    print(f"project root: {ROOT}")
    matches = pd.read_parquet(PROCESSED / "matches.parquet")
    print(f"loaded {len(matches):,} matches")

    dim_venue, matches = build_venue(matches)
    print(f"  dim_venue  {len(dim_venue):>6,} rows "
          f"(from {matches['venue'].nunique()} raw venue strings)")

    dim_team, matches = build_team(matches)
    print(f"  dim_team   {len(dim_team):>6,} rows")

    dim_series, matches = build_series(matches)
    print(f"  dim_series {len(dim_series):>6,} rows")

    dim_date, matches = build_date(matches)
    print(f"  dim_date   {len(dim_date):>6,} rows")

    dim_player = build_player(matches)
    print(f"  dim_player {len(dim_player):>6,} rows")

    if not verify(matches, dim_venue, dim_team, dim_series, dim_date, dim_player):
        print("\nverification FAILED - nothing written")
        return 1

    outputs = {
        "dim_venue": dim_venue,
        "dim_team": dim_team,
        "dim_series": dim_series,
        "dim_date": dim_date,
        "dim_player": dim_player,
        "matches_keyed": matches,
    }
    print()
    for name, df in outputs.items():
        path = PROCESSED / f"{name}.parquet"
        df.to_parquet(path, index=False)
        print(f"  wrote {name}.parquet  {len(df):>6,} rows "
              f"{path.stat().st_size / 1_048_576:5.1f} MB")

    print("\ndone")
    return 0


if __name__ == "__main__":
    sys.exit(main())