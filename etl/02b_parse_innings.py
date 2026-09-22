"""
Parse the Cricsheet archive a second time, at INNINGS grain.

02_parse_matches.py turns deliveries into one row per player. This script
reads the same deliveries and turns them into one row per innings, plus one
row per partnership. Different grain, different file — so neither script can
break the other, and 02's verified output is never touched.

Why this exists
---------------
Neither of the player-level tables can produce a team's score.
  fact_batting.runs_scored   = runs off the bat only
  fact_bowling.runs_conceded = includes wides and no-balls, excludes byes
                               and leg-byes (not the bowler's fault)
So England's world-record 498 against the Netherlands shows as 476 in one
table and 492 in the other, and neither is the score. Summing runs.total
over every delivery gives the real figure.

Reads
-----
data/raw/odis_json.zip    one-day internationals
data/raw/t20s_json.zip    T20 internationals

Writes
------
data/processed/innings.parquet       one row per innings (super overs excluded)
data/processed/partnerships.parquet  one row per partnership
data/processed/match_extra.parquet   one row per match: event stage, group

Run with:  python etl/02b_parse_innings.py
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
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
ARCHIVES = ["odis_json.zip", "t20s_json.zip"]

# A batter who retires is not out. Counting a retirement as a wicket would
# overstate wickets lost and understate every batting average involved.
NOT_DISMISSALS = {"retired hurt", "retired not out"}

# Phase boundaries, per format: (first N overs, last M overs).
#   ODI : overs 1-10 and the last 10  - the ODI powerplay and death overs
#   T20I: overs 1-6  and the last 5   - the T20 powerplay and death overs
# Fixed counts rather than the JSON's own `powerplays` blocks, which shift
# between eras and get rewritten in rain-affected matches.
PHASES = {"ODI": (10, 10), "T20": (6, 5)}

# One stage, two spellings - the same label-versus-identity problem as the
# venues. "ODI" is not a stage at all; it is a format that leaked into the
# field, so it becomes NULL rather than a category of one.
STAGE_ALIASES = {
    "Semi-Final": "Semi Final",
    "Quarter-Final": "Quarter Final",
    "ODI": None,
}


# --------------------------------------------------------------------------
# innings
# --------------------------------------------------------------------------

def summarise_innings(innings: dict, innings_no: int, match_id: int,
                      match_type: str = "ODI") -> dict | None:
    """One row describing a whole innings, or None for a super over.

    A super over is a tie-break, not an innings — the same exclusion
    02_parse_matches.py applies, for the same reason.
    """
    if innings.get("super_over"):
        return None

    overs = innings.get("overs", [])
    if not overs:
        return None

    powerplay_overs, death_overs = PHASES[match_type]
    max_over = max(o["over"] for o in overs)
    death_start = max(powerplay_overs, max_over - death_overs + 1)

    def phase_of(over_no: int) -> str:
        if over_no < powerplay_overs:
            return "pp"
        return "death" if over_no >= death_start else "middle"

    runs_total = runs_off_bat = legal_balls = wickets = 0
    fours = sixes = dots = 0
    extras: Counter[str] = Counter()
    phase = {p: {"runs": 0, "balls": 0, "wickets": 0}
             for p in ("pp", "middle", "death")}

    for over in overs:
        p = phase[phase_of(over["over"])]
        for d in over["deliveries"]:
            r = d["runs"]
            ex = d.get("extras", {})

            # runs.total is batter runs plus every kind of extra. Summing it
            # over the innings IS the scoreboard total.
            runs_total += r["total"]
            runs_off_bat += r["batter"]
            p["runs"] += r["total"]

            for kind, value in ex.items():
                extras[kind] += value

            is_wide = "wides" in ex
            is_noball = "noballs" in ex
            if not is_wide and not is_noball:
                legal_balls += 1
                p["balls"] += 1
                if r["total"] == 0:
                    dots += 1

            # non_boundary marks a 4 or 6 that was RUN, not hit to the rope.
            if not r.get("non_boundary"):
                if r["batter"] == 4:
                    fours += 1
                elif r["batter"] == 6:
                    sixes += 1

            for wk in d.get("wickets", []):
                if wk.get("kind") not in NOT_DISMISSALS:
                    wickets += 1
                    p["wickets"] += 1

    target = innings.get("target") or {}

    row = {
        "match_id": match_id,
        "innings_no": innings_no,
        "batting_team": innings.get("team"),
        "runs_total": runs_total,
        "wickets_lost": wickets,
        "legal_balls": legal_balls,
        "runs_off_bat": runs_off_bat,
        "extras_total": sum(extras.values()),
        "extras_wides": extras.get("wides", 0),
        "extras_noballs": extras.get("noballs", 0),
        "extras_byes": extras.get("byes", 0),
        "extras_legbyes": extras.get("legbyes", 0),
        "extras_penalty": extras.get("penalty", 0),
        "fours": fours,
        "sixes": sixes,
        "dots": dots,
        "target_runs": target.get("runs"),
        "target_overs": target.get("overs"),
        "penalty_runs": _penalty_runs(innings),
        "absent_hurt": len(innings.get("absent_hurt", []) or []),
        "overs_recorded": max_over + 1,
    }
    for name in ("pp", "middle", "death"):
        row[f"{name}_runs"] = phase[name]["runs"]
        row[f"{name}_balls"] = phase[name]["balls"]
        row[f"{name}_wickets"] = phase[name]["wickets"]
    return row


def _penalty_runs(innings: dict) -> int:
    """Innings-level penalty runs, which are not attached to a delivery."""
    pen = innings.get("penalty_runs") or {}
    if isinstance(pen, dict):
        return int(pen.get("pre", 0)) + int(pen.get("post", 0))
    return 0


# --------------------------------------------------------------------------
# partnerships
# --------------------------------------------------------------------------

def parse_partnerships(innings: dict, innings_no: int, match_id: int) -> list[dict]:
    """One row per partnership.

    The pair at the crease is tracked as a SET, so the batters crossing does
    not look like a new partnership — only a genuine change of personnel
    does. When the set changes, the previous partnership has ended.

    Runs include extras, which is how partnerships are scored in cricket.
    Balls exclude wides, which are not faced.
    """
    if innings.get("super_over"):
        return []

    rows: list[dict] = []
    current: frozenset[str] | None = None
    order: tuple[str, str] | None = None
    runs = balls = 0
    wicket_no = 0

    for over in innings.get("overs", []):
        for d in over["deliveries"]:
            pair = frozenset((d["batter"], d["non_striker"]))

            if current is None:
                current, order = pair, (d["batter"], d["non_striker"])
            elif pair != current:
                wicket_no += 1
                rows.append({
                    "match_id": match_id,
                    "innings_no": innings_no,
                    "wicket_no": wicket_no,
                    "batter1": order[0],
                    "batter2": order[1],
                    "runs": runs,
                    "balls": balls,
                    "unbroken": False,
                })
                current, order = pair, (d["batter"], d["non_striker"])
                runs = balls = 0

            # The delivery on which a wicket falls still belongs to the
            # partnership that was ending, because the pair only changes
            # on the NEXT delivery.
            runs += d["runs"]["total"]
            if "wides" not in d.get("extras", {}):
                balls += 1

    if current is not None:
        wicket_no += 1
        rows.append({
            "match_id": match_id,
            "innings_no": innings_no,
            "wicket_no": wicket_no,
            "batter1": order[0],
            "batter2": order[1],
            "runs": runs,
            "balls": balls,
            "unbroken": True,
        })
    return rows


# --------------------------------------------------------------------------
# match-level extras
# --------------------------------------------------------------------------

def parse_match_extra(info: dict, match_id: int) -> dict:
    """Event stage and group — final, semi-final, Group A, and so on.

    `event` is usually a dict but is a bare string in some older files, so
    both shapes are handled rather than assumed.
    """
    event = info.get("event")
    if isinstance(event, str):
        event = {"name": event}
    event = event or {}

    stage = event.get("stage")
    stage = STAGE_ALIASES.get(stage, stage)

    return {
        "match_id": match_id,
        "event_name": event.get("name"),
        "event_stage": stage,
        # A group is a label ("A", "Group 1") but some T20I files store it
        # as a bare number. Parquet refuses a column holding both, so it is
        # always stored as text - the same fix as `season` in 02.
        "event_group": None if event.get("group") is None else str(event.get("group")),
        "event_match_number": event.get("match_number"),
    }


# --------------------------------------------------------------------------
# runner
# --------------------------------------------------------------------------

def main() -> int:
    missing = [a for a in ARCHIVES if not (RAW / a).exists()]
    if missing:
        print(f"missing {missing} - run etl/01_download_cricsheet.py first")
        return 1

    innings_rows: list[dict] = []
    partnership_rows: list[dict] = []
    extra_rows: list[dict] = []
    failures: list[tuple[str, str]] = []
    super_overs = 0
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
                    match_type = info.get("match_type", "ODI")

                    # Names resolve to ids using THIS match's own registry,
                    # the same rule as 02: inside one file a name is
                    # unambiguous, and it is only on merge that SR Taylor
                    # becomes two people.
                    registry = (info.get("registry") or {}).get("people") or {}

                    extra_rows.append(parse_match_extra(info, match_id))

                    for n, innings in enumerate(data.get("innings", []), start=1):
                        if innings.get("super_over"):
                            super_overs += 1
                            continue

                        summary = summarise_innings(innings, n, match_id, match_type)
                        if summary:
                            innings_rows.append(summary)

                        for p in parse_partnerships(innings, n, match_id):
                            p["batter1_id"] = registry.get(p["batter1"])
                            p["batter2_id"] = registry.get(p["batter2"])
                            partnership_rows.append(p)

                except Exception as exc:                       # noqa: BLE001
                    failures.append((name, f"{type(exc).__name__}: {exc}"))

    innings_df = pd.DataFrame(innings_rows)
    partners_df = pd.DataFrame(partnership_rows)
    extra_df = pd.DataFrame(extra_rows)

    print(f"\nfiles read          : {len(names):,}")
    print(f"failures            : {len(failures)}")
    for name, err in failures[:5]:
        print(f"    {name}: {err}")
    print(f"super overs skipped : {super_overs}")

    # --- verification -----------------------------------------------------
    ok = True

    def check(label: str, actual, expected):
        nonlocal ok
        good = actual == expected
        ok = ok and good
        print(f"  [{'PASS' if good else 'FAIL'}] {label}: {actual}")

    print("\nverification")
    check("parse failures", len(failures), 0)

    # The reconciliation that justifies this whole script.
    mismatch = int((innings_df["runs_total"]
                    != innings_df["runs_off_bat"]
                    + innings_df["extras_total"]).sum())
    check("runs_total = off the bat + extras", mismatch, 0)

    phase_gap = int((innings_df["runs_total"]
                     != innings_df[["pp_runs", "middle_runs",
                                    "death_runs"]].sum(axis=1)).sum())
    check("phase runs sum to the total", phase_gap, 0)

    phase_balls = int((innings_df["legal_balls"]
                       != innings_df[["pp_balls", "middle_balls",
                                      "death_balls"]].sum(axis=1)).sum())
    check("phase balls sum to legal balls", phase_balls, 0)

    check("duplicate (match_id, innings_no)",
          int(innings_df.duplicated(["match_id", "innings_no"]).sum()), 0)
    check("duplicate (match_id, innings_no, wicket_no)",
          int(partners_df.duplicated(
              ["match_id", "innings_no", "wicket_no"]).sum()), 0)
    check("partnerships with no batter id",
          int(partners_df[["batter1_id", "batter2_id"]]
              .isna().any(axis=1).sum()), 0)
    check("innings with no batting team",
          int(innings_df["batting_team"].isna().sum()), 0)

    if not ok:
        print("\nverification FAILED - nothing written")
        return 1

    for name, df in [("innings", innings_df),
                     ("partnerships", partners_df),
                     ("match_extra", extra_df)]:
        path = PROCESSED / f"{name}.parquet"
        df.to_parquet(path, index=False)
        print(f"\n  wrote {name}.parquet  {len(df):>7,} rows  "
              f"{path.stat().st_size / 1_048_576:5.1f} MB")

    print("\n--- highest totals, now correct ---")
    top = innings_df.nlargest(5, "runs_total")[
        ["match_id", "innings_no", "batting_team", "runs_total",
         "wickets_lost", "legal_balls", "extras_total"]]
    print(top.to_string(index=False))

    print("\n--- biggest partnerships ---")
    big = partners_df.nlargest(5, "runs")[
        ["match_id", "innings_no", "wicket_no", "batter1", "batter2",
         "runs", "balls", "unbroken"]]
    print(big.to_string(index=False))

    print("\n--- match stages found ---")
    print(extra_df["event_stage"].value_counts(dropna=False)
          .head(12).to_string())

    print("\ndone")
    return 0


if __name__ == "__main__":
    sys.exit(main())