"""
Load the warehouse into PostgreSQL.

Runs the whole thing end to end:
    1. pre-flight checks in pandas, before a single row is sent
    2. sql/01_schema.sql   — drop and recreate all ten tables
    3. bulk load           — dimensions first, then facts, in key order
    4. sql/02_indexes.sql  — indexes and ANALYZE
    5. verification        — row counts read back from the database

Idempotent by construction: the schema drops and recreates, so running this
twice leaves exactly the same database. Re-running is the normal way to
apply a change, not an emergency.

Needs DATABASE_URL in .env.

Run with:  python etl/05_load_postgres.py
"""

from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv


# --------------------------------------------------------------------------
# paths and config
# --------------------------------------------------------------------------

def find_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__).resolve()).parent
    for candidate in [here, *here.parents]:
        if (candidate / "data" / "processed").exists():
            return candidate
    raise FileNotFoundError("could not locate data/processed above " + str(here))


ROOT = find_root()
PROCESSED = ROOT / "data" / "processed"
SQL = ROOT / "sql"

load_dotenv(ROOT / ".env")
DATABASE_URL = os.getenv("DATABASE_URL")


# --------------------------------------------------------------------------
# what to load, in dependency order
#
# The column list for each table is explicit rather than "whatever is in the
# parquet". The parquet files carry working columns the warehouse does not
# want, and an implicit list would either load them or fail confusingly.
# --------------------------------------------------------------------------

TABLES: list[tuple[str, list[str]]] = [
    ("dim_date", [
        "date_key", "full_date", "year", "quarter", "month",
        "month_name", "day", "day_name", "is_weekend"]),

    ("dim_player", [
        "player_id", "player_name", "gender", "primary_team",
        "teams_played_for", "debut", "last_match", "playing_role",
        "bowl_share", "avg_position", "dismissal_rate",
        "batting_style", "bowling_style"]),

    ("dim_team", [
        "team_id", "team_name", "gender", "team_display"]),

    ("dim_venue", [
        "venue_id", "venue_name", "venue_display", "former_names",
        "city", "country", "home_nation", "capacity", "capacity_source"]),

    ("dim_series", [
        "series_id", "series_name", "season", "gender",
        "season_start", "first_match", "last_match"]),

    ("fact_match", [
        "match_id", "date_key", "match_date", "venue_id", "series_id",
        "team1_id", "team2_id", "toss_winner_id", "winner_id",
        "player_of_match_id", "toss_decision", "victory_type",
        "victory_margin", "victory_method", "gender", "match_format",
        "match_type_number", "season", "scheduled_overs", "balls_per_over",
        "event_stage", "event_group", "event_match_number"]),

    ("fact_innings", [
        "match_id", "innings_no", "batting_team_id", "bowling_team_id",
        "runs_total", "wickets_lost", "legal_balls", "runs_off_bat",
        "extras_total", "extras_wides", "extras_noballs", "extras_byes",
        "extras_legbyes", "extras_penalty", "fours", "sixes", "dots",
        "target_runs", "target_overs", "penalty_runs", "absent_hurt",
        "overs_recorded",
        "pp_runs", "pp_balls", "pp_wickets",
        "middle_runs", "middle_balls", "middle_wickets",
        "death_runs", "death_balls", "death_wickets"]),

    ("fact_batting", [
        "match_id", "innings_no", "player_id", "team_id",
        "batting_position", "runs_scored", "balls_faced", "fours", "sixes",
        "is_not_out", "dismissal_kind", "dismissed_by_id", "fielder_id"]),

    ("fact_bowling", [
        "match_id", "innings_no", "player_id", "team_id",
        "balls_bowled", "runs_conceded", "wickets", "maidens", "dots"]),

    ("fact_partnership", [
        "match_id", "innings_no", "wicket_no", "batting_team_id",
        "batter1_id", "batter2_id", "runs", "balls", "unbroken"]),
]


# --------------------------------------------------------------------------
# pre-flight
# --------------------------------------------------------------------------

def preflight(frames: dict[str, pd.DataFrame]) -> bool:
    """Check in pandas what the database is about to check in SQL.

    A constraint violation halfway through a COPY rolls the whole load back
    and reports one row with no context. The same problem found here names
    the table, the rule and the number of offending rows.
    """
    ok = True

    def check(label: str, actual: int, expected: int = 0):
        nonlocal ok
        good = actual == expected
        ok = ok and good
        print(f"  [{'PASS' if good else 'FAIL'}] {label}: {actual}")

    print("pre-flight")

    for name, cols in TABLES:
        df = frames[name]
        missing = [c for c in cols if c not in df.columns]
        check(f"{name}: columns missing from parquet", len(missing))
        if missing:
            print(f"        {missing}")

    fb = frames["fact_batting"]
    # The CHECK on fact_batting: out with a recorded dismissal, or not out
    # with none. Anything else is a parsing bug, not a data quirk.
    bad = int((fb["is_not_out"] & fb["dismissal_kind"].notna()).sum()
              + (~fb["is_not_out"] & fb["dismissal_kind"].isna()).sum())
    check("fact_batting: is_not_out agrees with dismissal_kind", bad)

    fi = frames["fact_innings"]
    check("fact_innings: runs_total = off the bat + extras",
          int((fi["runs_total"] != fi["runs_off_bat"] + fi["extras_total"]).sum()))
    check("fact_innings: phase runs sum to the total",
          int((fi["runs_total"]
               != fi[["pp_runs", "middle_runs", "death_runs"]].sum(axis=1)).sum()))
    check("fact_innings: wickets_lost never above 10",
          int((fi["wickets_lost"] > 10).sum()))
    check("fact_innings: batting and bowling teams differ",
          int((fi["batting_team_id"] == fi["bowling_team_id"]).sum()))

    fm = frames["fact_match"]
    check("fact_match: team1 differs from team2",
          int((fm["team1_id"] == fm["team2_id"]).sum()))
    check("fact_match: toss_decision is bat or field",
          int((~fm["toss_decision"].isin(["bat", "field"])
               & fm["toss_decision"].notna()).sum()))

    fp = frames["fact_partnership"]
    check("fact_partnership: two different batters",
          int((fp["batter1_id"] == fp["batter2_id"]).sum()))

    fw = frames["fact_bowling"]
    check("fact_bowling: wickets never above 10",
          int((fw["wickets"] > 10).sum()))

    return ok


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

def run_sql_file(conn, path: Path) -> None:
    print(f"\nrunning {path.name}")
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def whole_floats_to_int(df: pd.DataFrame) -> pd.DataFrame:
    """Turn float columns that hold only whole numbers into integers.

    One blank anywhere in a pandas integer column silently promotes the
    whole column to float, so 1 becomes 1.0 — and PostgreSQL rejects "1.0"
    for a SMALLINT. This restores the integer form while keeping the blanks
    as nulls. Genuine decimals (bowl_share, avg_position) are untouched,
    because they are not whole numbers.
    """
    out = df.copy()
    for col in out.columns:
        s = out[col]
        if not pd.api.types.is_float_dtype(s):
            continue
        values = s.dropna()
        if len(values) and (values % 1 == 0).all():
            out[col] = s.astype("Int64")
    return out


def copy_frame(conn, table: str, df: pd.DataFrame, cols: list[str]) -> float:
    """Bulk-load one table with COPY.

    COPY streams a whole table in one statement. Row-by-row INSERTs would
    mean 56,052 round trips to Singapore; this is one. The DataFrame is
    written to an in-memory CSV buffer, never to disk.
    """
    buf = io.StringIO()
    whole_floats_to_int(df[cols]).to_csv(buf, index=False, header=False,
                                         na_rep="")
    buf.seek(0)

    started = time.perf_counter()
    with conn.cursor() as cur:
        cur.copy_expert(
            f"COPY {table} ({', '.join(cols)}) "
            f"FROM STDIN WITH (FORMAT csv, NULL '')",
            buf,
        )
    conn.commit()
    return time.perf_counter() - started


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> int:
    if not DATABASE_URL:
        print("DATABASE_URL is not set in .env")
        return 1

    print(f"project root: {ROOT}")

    frames = {name: pd.read_parquet(PROCESSED / f"{name}.parquet")
              for name, _ in TABLES}

    if not preflight(frames):
        print("\npre-flight FAILED - nothing sent to the database")
        return 1

    print("\nconnecting")
    conn = psycopg2.connect(DATABASE_URL)
    # Neon suspends compute after five minutes idle, so the first statement
    # after a pause is slow. That is the database waking, not a hang.
    print("connected")

    try:
        run_sql_file(conn, SQL / "01_schema.sql")

        print("\nloading")
        total_rows = 0
        for name, cols in TABLES:
            df = frames[name]
            secs = copy_frame(conn, name, df, cols)
            total_rows += len(df)
            print(f"  {name:18s} {len(df):>7,} rows  {secs:5.1f}s")

        run_sql_file(conn, SQL / "02_indexes.sql")

        # --- read the counts back OUT of the database ----------------------
        # Checking the DataFrames again would prove nothing. The only
        # meaningful confirmation is what the database itself now holds.
        print("\nverification (counts read from PostgreSQL)")
        ok = True
        with conn.cursor() as cur:
            for name, _ in TABLES:
                cur.execute(f"SELECT count(*) FROM {name}")
                got = cur.fetchone()[0]
                want = len(frames[name])
                good = got == want
                ok = ok and good
                print(f"  [{'PASS' if good else 'FAIL'}] {name:18s} "
                      f"{got:>7,} (expected {want:,})")

            cur.execute("""
                SELECT pg_size_pretty(pg_database_size(current_database()))
            """)
            size = cur.fetchone()[0]

            # One real query, to prove the warehouse answers questions and
            # not merely that rows arrived.
            cur.execute("""
                SELECT p.player_name,
                       sum(b.runs_scored) AS runs,
                       count(*)           AS innings
                FROM fact_batting b
                JOIN dim_player   p ON p.player_id = b.player_id
                JOIN fact_match   m ON m.match_id  = b.match_id
                WHERE m.gender = 'male' AND m.match_format = 'ODI' 
                GROUP BY p.player_name
                ORDER BY runs DESC
                LIMIT 5
            """)
            leaders = cur.fetchall()

        print(f"\ndatabase size: {size}")
        print("\nmost ODI runs, men's, 2002 onward:")
        for nm, runs, inns in leaders:
            print(f"  {nm:24s} {runs:>6,} runs in {inns:>3} innings")

        if not ok:
            print("\nrow counts do not match")
            return 1

        print(f"\nloaded {total_rows:,} rows across {len(TABLES)} tables")
        print("done")
        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())