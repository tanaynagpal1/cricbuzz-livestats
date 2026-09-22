"""
Fill in batting and bowling styles for the players in dim_player.

Cricsheet's ball-by-ball files say who batted and bowled, but not HOW
(right- or left-handed, pace or spin). This step adds that from the
open-source `cricketdata` project (github.com/robjhyndman/cricketdata),
whose player_meta table maps Cricsheet ids to the styles published on
ESPNcricinfo.

    1. download player_meta.rda into data/raw/ (skipped if already there)
    2. read it, keep one row per Cricsheet id, tidy the wording so every
       style is spelled one way ("Right hand Bat" -> "Right-hand bat")
    3. copy the styles into a temporary table, then fill dim_player in
       ONE UPDATE inside one transaction
    4. print how many players now have styles, overall and for India

Only EMPTY styles are filled, so anything typed on the Manage Data page is
never overwritten. Safe to run again. Run it after 05_load_postgres.py,
because that step recreates dim_player with empty styles.

Needs: pip install pyreadr      Run with:  python etl/08_load_player_styles.py
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

import pandas as pd
import psycopg2
import pyreadr
import requests
from dotenv import load_dotenv
from psycopg2.extras import execute_values

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
META_FILE = RAW / "player_meta.rda"
META_URL = ("https://raw.githubusercontent.com/robjhyndman/cricketdata/"
            "master/data/player_meta.rda")

load_dotenv(ROOT / ".env")
# psycopg2 wants plain "postgresql://"; SQLAlchemy-style URLs name the driver.
DATABASE_URL = (os.getenv("DATABASE_URL") or "").replace("postgresql+psycopg2://", "postgresql://")


def download() -> None:
    if META_FILE.exists():
        print(f"  using saved {META_FILE.name}")
        return
    RAW.mkdir(parents=True, exist_ok=True)
    reply = requests.get(META_URL, timeout=60)
    reply.raise_for_status()
    META_FILE.write_bytes(reply.content)
    print(f"  downloaded {META_FILE.name} ({len(reply.content) / 1e6:.1f} MB)")


def tidy_batting(value) -> str | None:
    """'Right hand Bat' / 'Right-hand bat' -> 'Right-hand bat'. Anything
    else (a bowling style in the wrong column) is treated as unknown."""
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if text.startswith("right"):
        return "Right-hand bat"
    if text.startswith("left") and "bat" in text:
        return "Left-hand bat"
    return None


def tidy_bowling(value) -> str | None:
    """'Right arm Fast medium' -> 'Right-arm fast-medium',
    'Slow Left arm Orthodox' -> 'Slow left-arm orthodox'. Players with two
    styles keep both, comma-separated."""
    if not isinstance(value, str) or not value.strip():
        return None
    parts = []
    for part in value.split(","):
        text = part.strip().lower()
        text = re.sub(r"\b(right|left) arm\b", r"\1-arm", text)
        for a, b in (("fast medium", "fast-medium"), ("medium fast", "medium-fast"),
                     ("slow medium", "slow-medium"), ("wrist spin", "wrist-spin")):
            text = text.replace(a, b)
        text = text[:1].upper() + text[1:]
        if text and text not in parts:
            parts.append(text)
    return ", ".join(parts) or None


def load_styles() -> pd.DataFrame:
    meta = next(iter(pyreadr.read_r(str(META_FILE)).values()))
    styles = pd.DataFrame({
        "player_id": meta["cricsheet_id"],
        "batting_style": meta["batting_style"].map(tidy_batting),
        "bowling_style": meta["bowling_style"].map(tidy_bowling),
    }).dropna(subset=["player_id"])
    styles = styles[styles["batting_style"].notna() | styles["bowling_style"].notna()]
    # A handful of ids appear twice: keep the row with the most information.
    styles["filled"] = styles[["batting_style", "bowling_style"]].notna().sum(axis=1)
    styles = (styles.sort_values("filled", ascending=False)
                    .drop_duplicates("player_id").drop(columns="filled"))
    return styles


def main() -> None:
    if not DATABASE_URL:
        sys.exit("DATABASE_URL is not set - check your .env file")
    started = time.time()

    print("1. source file")
    download()

    print("2. read and tidy")
    styles = load_styles()
    print(f"  {len(styles):,} players with a known style in the source")

    print("3. update dim_player (one transaction)")
    # pandas marks "unknown" as NaN; the database must get a real NULL,
    # not the text 'NaN'.
    def value(v):
        return v if isinstance(v, str) else None
    rows = [(r.player_id, value(r.batting_style), value(r.bowling_style))
            for r in styles.itertuples(index=False)]
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TEMP TABLE style_src (
                player_id text PRIMARY KEY, batting_style text, bowling_style text
            ) ON COMMIT DROP
        """)
        execute_values(cur, "INSERT INTO style_src VALUES %s", rows, page_size=2000)
        cur.execute("""
            UPDATE dim_player p
            SET    batting_style = COALESCE(p.batting_style, s.batting_style),
                   bowling_style = COALESCE(p.bowling_style, s.bowling_style)
            FROM   style_src s
            WHERE  s.player_id = p.player_id
              AND  ((p.batting_style IS NULL AND s.batting_style IS NOT NULL)
                 OR (p.bowling_style IS NULL AND s.bowling_style IS NOT NULL))
        """)
        print(f"  {cur.rowcount:,} players updated")

        print("4. check")
        cur.execute("""
            SELECT  COUNT(*),
                    COUNT(batting_style),
                    COUNT(bowling_style),
                    COUNT(*)             FILTER (WHERE primary_team = 'India'),
                    COUNT(batting_style) FILTER (WHERE primary_team = 'India'),
                    COUNT(bowling_style) FILTER (WHERE primary_team = 'India')
            FROM    dim_player
        """)
        total, bat, bowl, ind, ind_bat, ind_bowl = cur.fetchone()
    print(f"  all players : {bat:,} of {total:,} have a batting style, "
          f"{bowl:,} a bowling style")
    print(f"  India       : {ind_bat} of {ind} have a batting style, "
          f"{ind_bowl} a bowling style")
    print(f"done in {time.time() - started:.1f} s")


if __name__ == "__main__":
    main()