"""
Load and run the 25 analytics queries.

Every query lives in its own file under sql/queries/. No page in this
application contains a SQL string. Three reasons that matters:

  * A .sql file is version-controlled, diffable, and syntax-highlighted.
  * A reviewer can read all 25 deliverables in one folder.
  * The app can SHOW the SQL next to the result without the SQL and the
    displayed text ever drifting apart — they are the same file.

Each query file starts with a metadata header, which this module parses so
the app's dropdown is built from the files themselves. Add q26.sql and it
appears in the UI with no code change.

    -- id: 1
    -- title: Players who represent India
    -- question: Find all players who represent India...
    -- params: none
    SELECT ...

Only `title` is required; everything else has a sensible default. There is
no tier line: the level comes from the question number, exactly as the brief
groups them (1-8 beginner, 9-16 intermediate, 17-25 advanced). A `-- tier:`
line, if present, still overrides that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

from utils.db_connection import DatabaseError, run_query


def find_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__).resolve()).parent
    for candidate in [here, *here.parents]:
        if (candidate / "sql" / "queries").exists():
            return candidate
    return Path(__file__).resolve().parent.parent


ROOT = find_root()
QUERY_DIR = ROOT / "sql" / "queries"

TIERS = ("beginner", "intermediate", "advanced")

# A header line looks like:  -- key: value
_HEADER = re.compile(r"^\s*--\s*([a-z_]+)\s*:\s*(.*?)\s*$")


def tier_for(number: int) -> str:
    """The brief's grouping: Q1-8 beginner, Q9-16 intermediate, Q17+ advanced."""
    if number <= 8:
        return "beginner"
    if number <= 16:
        return "intermediate"
    return "advanced"


@dataclass(frozen=True)
class Query:
    """One analytics query, with everything the UI needs to present it."""
    name: str                       # "q01"
    path: Path
    sql: str
    title: str
    question: str = ""
    tier: str = "beginner"
    number: int = 0
    params: tuple[str, ...] = field(default_factory=tuple)

    @property
    def label(self) -> str:
        return f"Q{self.number:02d} — {self.title}"


def _parse(path: Path) -> Query:
    """Read one .sql file and pull its header out.

    Header lines are ordinary SQL comments, so the file still runs unchanged
    if you paste it into the Neon SQL editor. Metadata that breaks the thing
    it describes is worse than no metadata.
    """
    raw = path.read_text(encoding="utf-8")

    meta: dict[str, str] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("--"):
            break                       # header ends at the first real SQL
        match = _HEADER.match(line)
        if match:
            meta[match.group(1)] = match.group(2)

    number = int(meta.get("id") or re.sub(r"\D", "", path.stem) or 0)
    tier = meta.get("tier", "").strip().lower()
    if tier not in TIERS:
        tier = tier_for(number)

    params = tuple(p.strip() for p in meta.get("params", "").split(",")
                   if p.strip() and p.strip().lower() != "none")

    return Query(
        name=path.stem,
        path=path,
        sql=raw,
        title=meta.get("title", path.stem),
        question=meta.get("question", ""),
        tier=tier,
        number=number,
        params=params,
    )


@lru_cache(maxsize=1)
def all_queries() -> tuple[Query, ...]:
    """Every query on disk, in question order.

    Cached, because the files do not change while the app is running. Delete
    the cache (all_queries.cache_clear()) if you are editing them live.
    """
    if not QUERY_DIR.exists():
        return ()
    files = sorted(QUERY_DIR.glob("q*.sql"))
    return tuple(sorted((_parse(f) for f in files), key=lambda q: q.number))


def by_tier(tier: str) -> list[Query]:
    return [q for q in all_queries() if q.tier == tier]


def get(name_or_number: str | int) -> Query:
    """Fetch one query by name ('q01') or by number (1)."""
    queries = all_queries()
    if isinstance(name_or_number, int):
        found = [q for q in queries if q.number == name_or_number]
    else:
        stem = str(name_or_number).lower().removesuffix(".sql")
        found = [q for q in queries if q.name.lower() == stem]

    if not found:
        available = ", ".join(q.name for q in queries) or "none"
        raise KeyError(f"no query called {name_or_number!r}. Have: {available}")
    return found[0]


def run(name_or_number: str | int, **params) -> pd.DataFrame:
    """Run a query by name, passing any :placeholders as parameters.

        run("q01", gender="male")

    Missing parameters are reported by name rather than as a database error
    thirty lines deep.
    """
    query = get(name_or_number)

    missing = [p for p in query.params if p not in params]
    if missing:
        raise DatabaseError(
            f"{query.name} needs parameter(s) {', '.join(missing)}. "
            f"Call run({query.name!r}, {missing[0]}=…)"
        )
    return run_query(query.sql, params)


def sql_of(name_or_number: str | int) -> str:
    """The SQL text, for showing beside the result with st.code()."""
    return get(name_or_number).sql


# --------------------------------------------------------------------------
# quick check
# --------------------------------------------------------------------------

if __name__ == "__main__":
    queries = all_queries()
    print(f"{len(queries)} queries in {QUERY_DIR}\n")
    for tier in TIERS:
        group = by_tier(tier)
        if not group:
            continue
        print(f"{tier} ({len(group)})")
        for q in group:
            args = f"  params: {', '.join(q.params)}" if q.params else ""
            print(f"   {q.label}{args}")
        print()
