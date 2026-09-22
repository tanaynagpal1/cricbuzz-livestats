"""
Load fact_over into PostgreSQL — and ONLY fact_over.

The other ten tables are already loaded and verified. This script adds one
table without touching them:

    1. pre-flight checks in pandas, before a single row is sent
    2. sql/03_fact_over.sql          drop and recreate fact_over
    3. COPY the rows
    4. sql/04_fact_over_indexes.sql  indexes and ANALYZE
    5. verification read back from the database, including a
       reconciliation against fact_innings done by PostgreSQL itself

Safe to run again: step 2 drops and recreates the one table.

Run with:  python etl/07_load_fact_over.py
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

COLUMNS = ["match_id", "innings_no", "over_no", "batting_team_id",
           "bowling_team_id", "bowler_id", "bowlers_used", "phase",
           "runs", "runs_off_bat", "extras", "wides", "noballs",
           "legal_balls", "dots", "fours", "sixes", "wickets",
           "bowler_wickets", "bowler_runs",
           "cum_runs", "cum_wickets", "cum_legal_balls"]


def preflight(df: pd.DataFrame) -> bool:
    ok = True

    def check(label: str, actual: int, expected: int = 0):
        nonlocal ok
        good = actual == expected
        ok = ok and good
        print(f"  [{'PASS' if good else 'FAIL'}] {label}: {actual}")

    print("pre-flight")
    check("columns missing from parquet", len([c for c in COLUMNS if c not in df]))
    check("blank values in any column", int(df[COLUMNS].isna().any(axis=1).sum()))
    check("runs <> off the bat + extras",
          int((df["runs"] != df["runs_off_bat"] + df["extras"]).sum()))
    check("cum_wickets above 10", int((df["cum_wickets"] > 10).sum()))
    check("unknown phase", int((~df["phase"].isin(["powerplay", "middle", "death"])).sum()))
    return ok


def run_sql_file(conn, path: Path) -> None:
    print(f"\nrunning {path.name}")
    with conn.cursor() as cur:
        cur.execute(path.read_text(encoding="utf-8"))
    conn.commit()


def main() -> int:
    if not DATABASE_URL:
        print("DATABASE_URL is not set in .env")
        return 1

    df = pd.read_parquet(PROCESSED / "fact_over.parquet")
    print(f"fact_over.parquet: {len(df):,} rows\n")

    if not preflight(df):
        print("\npre-flight FAILED - nothing sent to the database")
        return 1

    print("\nconnecting")
    conn = psycopg2.connect(DATABASE_URL)
    print("connected")

    try:
        run_sql_file(conn, SQL / "03_fact_over.sql")

        buf = io.StringIO()
        df[COLUMNS].to_csv(buf, index=False, header=False, na_rep="")
        buf.seek(0)
        started = time.perf_counter()
        with conn.cursor() as cur:
            cur.copy_expert(f"COPY fact_over ({', '.join(COLUMNS)}) "
                            f"FROM STDIN WITH (FORMAT csv, NULL '')", buf)
        conn.commit()
        print(f"\nloaded {len(df):,} rows in {time.perf_counter() - started:.1f}s")

        run_sql_file(conn, SQL / "04_fact_over_indexes.sql")

        # --- verification, done by the DATABASE, not by pandas -------------
        print("\nverification (read from PostgreSQL)")
        ok = True
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM fact_over")
            got = cur.fetchone()[0]
            good = got == len(df)
            ok = ok and good
            print(f"  [{'PASS' if good else 'FAIL'}] rows: {got:,} (expected {len(df):,})")

            # The overs must add up to every innings total already in the
            # warehouse. If this is 0, two independent parsers agree.
            cur.execute("""
                SELECT count(*)
                FROM fact_innings i
                JOIN (SELECT match_id, innings_no, sum(runs) AS runs,
                             sum(wickets) AS wkts, sum(legal_balls) AS balls
                      FROM fact_over GROUP BY match_id, innings_no) o
                  USING (match_id, innings_no)
                WHERE o.runs  <> i.runs_total
                   OR o.wkts  <> i.wickets_lost
                   OR o.balls <> i.legal_balls
            """)
            bad = cur.fetchone()[0]
            ok = ok and bad == 0
            print(f"  [{'PASS' if bad == 0 else 'FAIL'}] innings where overs "
                  f"don't add up: {bad}")

            # One real question, to prove the table answers things.
            cur.execute("""
                SELECT p.player_name, count(*) AS overs,
                       round(sum(o.bowler_runs) * 6.0 / sum(o.legal_balls), 2) AS economy
                FROM fact_over o
                JOIN dim_player p ON p.player_id = o.bowler_id
                JOIN fact_match m ON m.match_id  = o.match_id
                WHERE o.phase = 'death' AND m.gender = 'male' AND m.match_format = 'ODI'
                GROUP BY p.player_name
                HAVING count(*) >= 100
                ORDER BY economy
                LIMIT 5
            """)
            best = cur.fetchall()

            cur.execute("SELECT pg_size_pretty(pg_total_relation_size('fact_over'))")
            size = cur.fetchone()[0]

        print(f"\nfact_over size in the database: {size}")
        print("\nmost economical death bowlers, men's ODIs (100+ death overs):")
        for name, overs, econ in best:
            print(f"  {name:24s} {overs:>4} overs   economy {econ}")

        print("\ndone" if ok else "\nverification FAILED")
        return 0 if ok else 1

    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())