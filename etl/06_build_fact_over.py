"""
Build fact_over: one row per over, per innings, per match.

Why this table exists
---------------------
Every other fact table is too coarse for the over-by-over charts:
  fact_innings      one row per innings  -> no shape inside the innings
  fact_batting      one row per batter   -> no timing
  fact_bowling      one row per spell    -> no timing
The worm, the Manhattan, the chase-pressure chart and bowling-by-phase all
need to know WHEN runs and wickets happened. fact_over is that grain.

Rules (the same cricket rules as 02 and 02b, so the tables agree)
------------------------------------------------------------------
  runs            runs.total: batter runs + every extra (the scoreboard)
  legal_balls     every delivery except wides and no-balls
  dots            legal balls with no run of any kind
  fours / sixes   hit to the rope only (non_boundary = run, not hit)
  wickets         every dismissal except retired hurt / retired not out
  bowler_wickets  bowled, caught, lbw, stumped, caught and bowled, hit wicket
                  (NOT run out and the rest - the bowler gets no credit)
  bowler_runs     batter runs + wides + no-balls (NOT byes, leg-byes, penalty)
  phase           ODI: first 10 overs = powerplay, last 10 = death.
                  T20I: first 6 overs = powerplay, last 5 = death.
                  Rest = middle - exactly the boundaries 02b uses.
  bowler_id       the bowler of most deliveries in the over. An over is
                  occasionally finished by a second bowler (injury, or a
                  bowler removed from the attack); bowlers_used says so.
  super overs     excluded, as everywhere else

The proof it is right: every over total is summed back up per innings and
compared with fact_innings, and the bowler figures with fact_bowling. Two
independent parsers have to agree on every innings in the archive.

Reads   data/raw/odis_json.zip and data/raw/t20s_json.zip
        data/processed/fact_innings.parquet   (team ids, and the reconciliation)
        data/processed/fact_bowling.parquet   (the bowler reconciliation)
        data/processed/dim_player.parquet     (bowler ids must exist)
Writes  data/processed/fact_over.parquet

Run with:  python etl/06_build_fact_over.py
"""

from __future__ import annotations

import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

import pandas as pd


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
RAW = ROOT / "data" / "raw"
ARCHIVES = ["odis_json.zip", "t20s_json.zip"]

NOT_DISMISSALS = {"retired hurt", "retired not out"}
BOWLER_WICKETS = {"bowled", "caught", "lbw", "stumped",
                  "caught and bowled", "hit wicket"}

# Must match 02b_parse_innings.py, or the phase reconciliation below fails.
# (first N overs, last M overs) per format.
PHASES = {"ODI": (10, 10), "T20": (6, 5)}


# --------------------------------------------------------------------------
# one innings -> its overs
# --------------------------------------------------------------------------

def parse_overs(innings: dict, innings_no: int, match_id: int,
                registry: dict, match_type: str = "ODI") -> list[dict]:
    """One row per over of one innings, with running totals."""
    overs = innings.get("overs", [])
    if innings.get("super_over") or not overs:
        return []

    # Cricsheet numbers overs from 0. The phase boundary is computed on that
    # 0-based number exactly as 02b does; over_no is stored 1-based, the way
    # a scorecard shows it.
    powerplay_overs, death_overs = PHASES[match_type]
    max_over = max(o["over"] for o in overs)
    death_start = max(powerplay_overs, max_over - death_overs + 1)

    rows: list[dict] = []
    cum_runs = cum_wickets = cum_balls = 0

    for over in overs:
        n = over["over"]
        phase = ("powerplay" if n < powerplay_overs
                 else "death" if n >= death_start else "middle")

        runs = off_bat = extras = wides = noballs = 0
        legal = dots = fours = sixes = wickets = bowler_wkts = bowler_runs = 0
        bowlers: Counter[str] = Counter()

        for d in over["deliveries"]:
            r = d["runs"]
            ex = d.get("extras", {})
            bowlers[d["bowler"]] += 1

            runs += r["total"]
            off_bat += r["batter"]
            extras += r["extras"]
            wides += ex.get("wides", 0)
            noballs += ex.get("noballs", 0)
            bowler_runs += r["batter"] + ex.get("wides", 0) + ex.get("noballs", 0)

            if "wides" not in ex and "noballs" not in ex:
                legal += 1
                if r["total"] == 0:
                    dots += 1

            if not r.get("non_boundary"):
                if r["batter"] == 4:
                    fours += 1
                elif r["batter"] == 6:
                    sixes += 1

            for wk in d.get("wickets", []):
                kind = wk.get("kind")
                if kind not in NOT_DISMISSALS:
                    wickets += 1
                if kind in BOWLER_WICKETS:
                    bowler_wkts += 1

        cum_runs += runs
        cum_wickets += wickets
        cum_balls += legal

        main_bowler = bowlers.most_common(1)[0][0]
        rows.append({
            "match_id": match_id,
            "innings_no": innings_no,
            "over_no": n + 1,
            "phase": phase,
            "bowler": main_bowler,
            "bowler_id": registry.get(main_bowler),
            "bowlers_used": len(bowlers),
            "runs": runs,
            "runs_off_bat": off_bat,
            "extras": extras,
            "wides": wides,
            "noballs": noballs,
            "legal_balls": legal,
            "dots": dots,
            "fours": fours,
            "sixes": sixes,
            "wickets": wickets,
            "bowler_wickets": bowler_wkts,
            "bowler_runs": bowler_runs,
            "cum_runs": cum_runs,
            "cum_wickets": cum_wickets,
            "cum_legal_balls": cum_balls,
        })
    return rows


# --------------------------------------------------------------------------
# runner
# --------------------------------------------------------------------------

def main() -> int:
    missing = [a for a in ARCHIVES if not (RAW / a).exists()]
    if missing:
        print(f"missing {missing}")
        return 1

    rows: list[dict] = []
    failures: list[tuple[str, str]] = []
    names: list[str] = []

    for archive in ARCHIVES:
        print(f"reading {archive}")
        with zipfile.ZipFile(RAW / archive) as z:
            files = [n for n in z.namelist() if n.endswith(".json")]
            names.extend(files)
            for i, name in enumerate(files, 1):
                if i % 1000 == 0:
                    print(f"  {i:,} / {len(files):,}")
                try:
                    with z.open(name) as f:
                        data = json.load(f)
                    match_id = int(Path(name).stem)
                    info = data["info"]
                    # Resolve names with THIS match's registry (the SR Taylor rule).
                    registry = (info.get("registry") or {}).get("people") or {}
                    match_type = info.get("match_type", "ODI")
                    for n, innings in enumerate(data.get("innings", []), start=1):
                        rows.extend(parse_overs(innings, n, match_id, registry, match_type))
                except Exception as exc:                        # noqa: BLE001
                    failures.append((name, f"{type(exc).__name__}: {exc}"))

    df = pd.DataFrame(rows)

    # Team ids come from fact_innings, which already resolved them - the
    # same team in the same innings, so there is nothing to re-derive.
    fi = pd.read_parquet(PROCESSED / "fact_innings.parquet")
    df = df.merge(fi[["match_id", "innings_no", "batting_team_id", "bowling_team_id"]],
                  on=["match_id", "innings_no"], how="left")

    print(f"\nfiles read : {len(names):,}")
    print(f"failures   : {len(failures)}")
    for name, err in failures[:5]:
        print(f"    {name}: {err}")
    print(f"overs      : {len(df):,}")

    # --- verification -----------------------------------------------------
    ok = True

    def check(label: str, actual: int, expected: int = 0):
        nonlocal ok
        good = actual == expected
        ok = ok and good
        print(f"  [{'PASS' if good else 'FAIL'}] {label}: {actual}")

    print("\nverification")
    check("parse failures", len(failures))
    check("duplicate (match_id, innings_no, over_no)",
          int(df.duplicated(["match_id", "innings_no", "over_no"]).sum()))
    check("overs with no team ids",
          int(df[["batting_team_id", "bowling_team_id"]].isna().any(axis=1).sum()))
    check("overs with no bowler id", int(df["bowler_id"].isna().sum()))

    players = set(pd.read_parquet(PROCESSED / "dim_player.parquet")["player_id"])
    check("bowler ids missing from dim_player",
          int((~df["bowler_id"].isin(players)).sum()))

    check("runs = off the bat + extras",
          int((df["runs"] != df["runs_off_bat"] + df["extras"]).sum()))

    # Reconciliation 1: overs add back up to every innings in fact_innings.
    per_inn = (df.groupby(["match_id", "innings_no"])
                 .agg(o_runs=("runs", "sum"), o_wickets=("wickets", "sum"),
                      o_balls=("legal_balls", "sum"), o_fours=("fours", "sum"),
                      o_sixes=("sixes", "sum"), o_dots=("dots", "sum"),
                      o_overs=("over_no", "count"))
                 .reset_index())
    rec = fi.merge(per_inn, on=["match_id", "innings_no"], how="left")
    # (The o_ prefix keeps our sums apart from fact_innings' own columns,
    # several of which have the same names.)
    check("innings with no overs", int(rec["o_runs"].isna().sum()))
    for ours, theirs in [("runs", "runs_total"), ("wickets", "wickets_lost"),
                         ("balls", "legal_balls"), ("fours", "fours"),
                         ("sixes", "sixes"), ("dots", "dots"),
                         ("overs", "overs_recorded")]:
        check(f"sum of over {ours} = fact_innings.{theirs}",
              int((rec[f"o_{ours}"] != rec[theirs]).sum()))

    # Reconciliation 2: the phases agree with fact_innings' phase columns.
    ph = (df.pivot_table(index=["match_id", "innings_no"], columns="phase",
                         values=["runs", "legal_balls", "wickets"],
                         aggfunc="sum", fill_value=0))
    ph.columns = [f"o_{p}_{m}" for m, p in ph.columns]
    ph = ph.reset_index().merge(fi, on=["match_id", "innings_no"])
    for p_ours, p_theirs in [("powerplay", "pp"), ("middle", "middle"), ("death", "death")]:
        for m_ours, m_theirs in [("runs", "runs"), ("legal_balls", "balls"),
                                 ("wickets", "wickets")]:
            col = f"o_{p_ours}_{m_ours}"
            ours = ph[col] if col in ph else 0
            check(f"{p_ours} {m_ours} = fact_innings.{p_theirs}_{m_theirs}",
                  int((ours != ph[f"{p_theirs}_{m_theirs}"]).sum()))

    # Reconciliation 3: bowler figures, innings by innings, against
    # fact_bowling. Team-level, so it holds even when an over was shared.
    fw = pd.read_parquet(PROCESSED / "fact_bowling.parquet")
    bw = (fw.groupby(["match_id", "innings_no"])
            .agg(w=("wickets", "sum"), r=("runs_conceded", "sum")).reset_index())
    ob = (df.groupby(["match_id", "innings_no"])
            .agg(w=("bowler_wickets", "sum"), r=("bowler_runs", "sum")).reset_index())
    rb = bw.merge(ob, on=["match_id", "innings_no"], suffixes=("_bowl", "_over"))
    check("bowler wickets = fact_bowling wickets (per innings)",
          int((rb["w_bowl"] != rb["w_over"]).sum()))
    check("bowler runs = fact_bowling runs conceded (per innings)",
          int((rb["r_bowl"] != rb["r_over"]).sum()))

    # Running totals end where the innings ends.
    last = df.sort_values("over_no").groupby(["match_id", "innings_no"]).tail(1)
    last = last.merge(fi[["match_id", "innings_no", "runs_total"]],
                      on=["match_id", "innings_no"])
    check("final cum_runs = innings total",
          int((last["cum_runs"] != last["runs_total"]).sum()))

    if not ok:
        print("\nverification FAILED - nothing written")
        return 1

    cols = ["match_id", "innings_no", "over_no", "batting_team_id",
            "bowling_team_id", "bowler_id", "bowlers_used", "phase",
            "runs", "runs_off_bat", "extras", "wides", "noballs",
            "legal_balls", "dots", "fours", "sixes", "wickets",
            "bowler_wickets", "bowler_runs",
            "cum_runs", "cum_wickets", "cum_legal_balls"]
    out = df[cols].sort_values(["match_id", "innings_no", "over_no"])
    path = PROCESSED / "fact_over.parquet"
    out.to_parquet(path, index=False)
    print(f"\n  wrote fact_over.parquet  {len(out):,} rows  "
          f"{path.stat().st_size / 1_048_576:.1f} MB")

    print("\n--- most expensive overs ---")
    print(out.nlargest(5, "runs")[["match_id", "innings_no", "over_no",
                                   "runs", "sixes", "fours", "wides", "noballs"]]
          .to_string(index=False))
    print(f"\novers finished by a second bowler: {int((out['bowlers_used'] > 1).sum()):,}")
    print("\ndone")
    return 0


if __name__ == "__main__":
    sys.exit(main())