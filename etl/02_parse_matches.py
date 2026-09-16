"""Parse the Cricsheet archive into warehouse-shaped tables.

Run from the project root, after 01_download_cricsheet.py:
    python etl/02_parse_matches.py

Writes four parquet files into data/processed/. Re-running overwrites them,
so the script is idempotent - run it as often as you like.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from etl.cricsheet import parse_innings, parse_match_info

RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

# Add tests_json.zip and t20s_json.zip once the ODI pipeline is proven.
ARCHIVES = ["odis_json.zip"]


def parse_archive(zip_path: Path) -> dict:
    """Parse every match in one Cricsheet archive.

    Failures are collected rather than raised, so one malformed file cannot
    abandon a run that has already processed three thousand good ones.
    """
    matches, batting, bowling = [], [], []
    # Keyed by id, not name - two different cricketers can share a name.
    people: dict[str, set] = {}
    conflicts: list[tuple] = []
    failures: list[tuple] = []

    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(n for n in archive.namelist() if n.endswith(".json"))
        total = len(names)

        for index, name in enumerate(names, start=1):
            match_id = int(name.removesuffix(".json"))

            try:
                with archive.open(name) as handle:
                    data = json.load(handle)

                info = data["info"]
                teams = info.get("teams") or []

                matches.append(parse_match_info(info, match_id))

                # Cricsheet's own name-to-id map. Collecting it across every
                # match gives us dim_player without any fuzzy name matching.
                registry = (info.get("registry") or {}).get("people", {})
                for person, identifier in registry.items():
                    people.setdefault(identifier, set()).add(person)

                for number, one_innings in enumerate(data.get("innings", []),
                                                     start=1):
                    bat_rows, bowl_rows = parse_innings(one_innings, number)

                    # The bowling side is whichever team isn't batting.
                    batting_team = one_innings.get("team")
                    fielding_team = next((t for t in teams if t != batting_team),
                                         None)

                    # Resolve names to ids using THIS match's registry, while
                    # it can still tell two same-named players apart.
                    for row in bat_rows:
                        row["match_id"] = match_id
                        row["player_id"] = registry.get(row["player"])
                        row["dismissed_by_id"] = registry.get(row["dismissed_by"])
                        row["fielder_id"] = registry.get(row["fielder"])

                    for row in bowl_rows:
                        row["match_id"] = match_id
                        row["team"] = fielding_team
                        row["player_id"] = registry.get(row["player"])

                    batting.extend(bat_rows)
                    bowling.extend(bowl_rows)

            except Exception as exc:
                failures.append((name, f"{type(exc).__name__}: {exc}"))

            if index % 500 == 0 or index == total:
                print(f"\r   {index:>5} / {total}", end="", flush=True)

    print()
    return {"matches": matches, "batting": batting, "bowling": bowling,
            "people": people, "conflicts": conflicts, "failures": failures}


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    all_matches, all_batting, all_bowling = [], [], []
    all_people: dict[str, set] = {}
    all_conflicts, all_failures = [], []

    for filename in ARCHIVES:
        zip_path = RAW_DIR / filename

        if not zip_path.exists():
            print(f"MISSING  {filename} - run etl/01_download_cricsheet.py first")
            continue

        print(f"\nparsing {filename}")
        result = parse_archive(zip_path)

        all_matches.extend(result["matches"])
        all_batting.extend(result["batting"])
        all_bowling.extend(result["bowling"])
        for identifier, names in result["people"].items():
            all_people.setdefault(identifier, set()).update(names)
        all_conflicts.extend(result["conflicts"])
        all_failures.extend(result["failures"])

    if not all_matches:
        print("\nnothing parsed - stopping")
        return

    matches_df = pd.DataFrame(all_matches)
    batting_df = pd.DataFrame(all_batting)
    bowling_df = pd.DataFrame(all_bowling)
    # One row per real person. 'aliases' holds any alternative spellings.
    people_df = pd.DataFrame([
        {"cricsheet_id": identifier,
         "player_name": sorted(names)[0],
         "aliases": "|".join(sorted(names)[1:]) or None,
         "name_count": len(names)}
        for identifier, names in sorted(all_people.items())
    ])

    outputs = {
        "matches.parquet": matches_df,
        "batting.parquet": batting_df,
        "bowling.parquet": bowling_df,
        "people.parquet": people_df,
    }

    print("\nwriting:")
    for filename, frame in outputs.items():
        path = PROCESSED_DIR / filename
        frame.to_parquet(path, index=False)
        size_mb = path.stat().st_size / 1e6
        print(f"   {filename:<18} {len(frame):>8,} rows   {size_mb:>6.1f} MB")

    print("\nchecks:")
    print(f"   failures          {len(all_failures)}")
    distinct_names = len({name for names in all_people.values()
                          for name in names})
    print(f"   distinct player ids   {len(all_people):,}")
    print(f"   distinct player names {distinct_names:,}")
    print(f"   ids with >1 name      "
          f"{sum(1 for n in all_people.values() if len(n) > 1)}")
    print(f"   distinct venues    {matches_df['venue'].nunique():,}")
    print(f"   distinct teams     "
          f"{len(set(matches_df['team1']) | set(matches_df['team2'])):,}")
    print(f"   date range         {matches_df['match_date'].min()}"
          f" to {matches_df['match_date'].max()}")

    for item in all_failures[:5]:
        print("   FAIL", item)
    for item in all_conflicts[:5]:
        print("   CONFLICT", item)


if __name__ == "__main__":
    main()