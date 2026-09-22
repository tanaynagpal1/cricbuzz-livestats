"""
One database engine for the whole application.

Every page imports `get_engine()` and gets the SAME engine back. That is the
"centralized connection handling" the brief asks for, and it matters more
than it looks: an engine owns a pool of connections, so a page that builds
its own engine builds its own pool. Five pages doing that is five pools, and
Neon's free tier will refuse connections long before you notice why.

Also handles the one Neon behaviour that will otherwise look like a bug:
the free plan suspends compute after five minutes of inactivity, so the
first query after a pause takes a few seconds while the database wakes.
`pool_pre_ping` makes SQLAlchemy quietly discard connections that died
during the suspend rather than handing you a dead one.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

def find_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__).resolve()).parent
    for candidate in [here, *here.parents]:
        if (candidate / "sql").exists():
            return candidate
    return Path(__file__).resolve().parent.parent


ROOT = find_root()
load_dotenv(ROOT / ".env")


class DatabaseError(RuntimeError):
    """Something went wrong talking to PostgreSQL.

    A separate type so pages can catch database trouble specifically and
    show one clear message, instead of catching everything and hiding real
    bugs behind 'something went wrong'.
    """


# Streamlit's cache_resource keeps one engine alive across reruns. Outside
# Streamlit — in a notebook, or a script — lru_cache does the same job. The
# module must work in both, because the ETL and the app share these utils.
try:                                                    # pragma: no cover
    import streamlit as st
    _cache_resource = st.cache_resource
except Exception:                                       # pragma: no cover
    def _cache_resource(func):
        return lru_cache(maxsize=1)(func)


# --------------------------------------------------------------------------
# engine
# --------------------------------------------------------------------------

@_cache_resource
def get_engine() -> Engine:
    """Return the one shared engine, creating it on first use."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise DatabaseError(
            "DATABASE_URL is not set. Copy .env.example to .env and put your "
            "Neon connection string in it."
        )

    return create_engine(
        url,
        # Check a connection is alive before handing it out. Neon suspends
        # compute when idle, which silently kills pooled connections.
        pool_pre_ping=True,
        # Small pool: Streamlit is single-user here and Neon's free tier is
        # not generous with connections.
        pool_size=3,
        max_overflow=2,
        # Recycle before any proxy decides the connection is stale.
        pool_recycle=280,
        connect_args={"connect_timeout": 15},
        future=True,
    )


def warm_up() -> bool:
    """Wake the database and report whether it answered.

    Call this once on page load, inside a spinner. Neon's first query after
    a suspend takes several seconds; without a spinner a reviewer assumes
    the app has hung.
    """
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------

def run_query(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Run a SELECT and return a DataFrame.

    Values are passed as PARAMETERS, never glued into the SQL string. Two
    reasons, and the second is the one people forget:

      1. It is the only safe way to accept anything a user typed.
      2. PostgreSQL can reuse the query plan, because the statement text is
         identical every time regardless of the values.

    Write placeholders as :name in the SQL and pass {"name": value}.
    """
    try:
        with get_engine().connect() as conn:
            return pd.read_sql(text(sql), conn, params=params or {})
    except SQLAlchemyError as exc:
        raise DatabaseError(_readable(exc)) from exc


def run_scalar(sql: str, params: dict | None = None):
    """Run a query that returns a single value."""
    try:
        with get_engine().connect() as conn:
            return conn.execute(text(sql), params or {}).scalar()
    except SQLAlchemyError as exc:
        raise DatabaseError(_readable(exc)) from exc


# --------------------------------------------------------------------------
# writing — used only by the CRUD page
# --------------------------------------------------------------------------

def execute(sql: str, params: dict | None = None) -> int:
    """Run an INSERT, UPDATE or DELETE inside a transaction.

    `engine.begin()` commits on success and rolls back on any exception, so
    a statement that violates a foreign key leaves the database exactly as
    it was. That is what makes 'delete a player who has records' fail
    safely instead of half-deleting them.

    Returns the number of rows affected.
    """
    try:
        with get_engine().begin() as conn:
            result = conn.execute(text(sql), params or {})
            return result.rowcount
    except SQLAlchemyError as exc:
        raise DatabaseError(_readable(exc)) from exc


def execute_many(statements: list[tuple[str, dict]]) -> None:
    """Run several statements as ONE transaction — all or nothing.

    Use this when two changes only make sense together. Either every
    statement commits or none of them do.
    """
    try:
        with get_engine().begin() as conn:
            for sql, params in statements:
                conn.execute(text(sql), params or {})
    except SQLAlchemyError as exc:
        raise DatabaseError(_readable(exc)) from exc


# --------------------------------------------------------------------------
# error messages
# --------------------------------------------------------------------------

def _readable(exc: SQLAlchemyError) -> str:
    """Turn a database exception into something a user can act on.

    PostgreSQL's messages are precise but assume you know the schema. These
    translations say what the person actually did wrong.
    """
    raw = str(getattr(exc, "orig", exc))
    low = raw.lower()

    if "violates foreign key constraint" in low:
        if "still referenced" in low:
            return ("That record can't be deleted because other records "
                    "still refer to it. Remove those first.")
        return ("That record points at something that doesn't exist — check "
                "the player, team or venue you selected.")
    if "violates unique constraint" in low or "duplicate key" in low:
        return "A record with those details already exists."
    if "violates check constraint" in low:
        return "One of the values is outside the range the database allows."
    if "violates not-null constraint" in low:
        return "A required field was left empty."
    if "could not connect" in low or "connection refused" in low:
        return ("Could not reach the database. If it has been idle it may be "
                "waking up — try again in a few seconds.")
    if "timeout" in low:
        return "The database took too long to respond. It may be waking up."

    return f"Database error: {raw.splitlines()[0]}"


# --------------------------------------------------------------------------
# quick check
# --------------------------------------------------------------------------

if __name__ == "__main__":
    print("connecting…")
    if not warm_up():
        print("could not reach the database")
        raise SystemExit(1)

    print("connected\n")
    print(run_query("""
        SELECT table_name,
               pg_size_pretty(pg_total_relation_size(quote_ident(table_name)))
                   AS size
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY pg_total_relation_size(quote_ident(table_name)) DESC
    """).to_string(index=False))