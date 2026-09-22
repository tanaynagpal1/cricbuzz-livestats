"""
The brain behind the Ask AI page: Google Gemini + the cricket database.

For every question the page makes (at most) two Gemini calls:

    1. plan     Gemini reads the question, the recent conversation and the
                database layout, and decides: can the DATABASE answer this?
                  yes -> it writes one read-only SQL query
                  no  -> it answers from general cricket knowledge
    2. explain  if a query ran, Gemini turns the rows into a short answer,
                using only numbers that are in the result

Safety, in three layers, so a question can never change the data:
    * the SQL must be a single SELECT / WITH statement with no write words;
    * it runs inside a READ ONLY transaction, so PostgreSQL itself refuses
      any write even if one slipped through;
    * a 15-second statement timeout and a 500-row cap.

Memory: the page keeps the conversation in st.session_state and passes the
last few turns (with the SQL used) back to Gemini, so follow-ups such as
"and in T20Is?" work. Nothing is stored after the browser tab closes.

Needs GEMINI_API_KEY in .env (locally) or in the Streamlit secrets (online).
GEMINI_MODEL is optional; if it is not set, the first model below that the
key can use is picked.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import text

from utils.db_connection import DatabaseError, get_engine, run_query

MODELS = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash",
          "gemini-2.5-flash", "gemini-2.5-flash-lite"]
MAX_ROWS = 500              # rows kept from any query
ROWS_FOR_ANSWER = 40        # rows shown to Gemini when it writes the answer
HISTORY_TURNS = 8           # messages of conversation passed back as memory
TIMEOUT_MS = 15_000

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|copy|"
    r"vacuum|analyze|call|do|execute|prepare|set|reset|lock|comment|refresh|"
    r"listen|notify|pg_sleep\w*|pg_read\w*|pg_write\w*|lo_\w+|dblink\w*)\b",
    re.IGNORECASE)


class ChatError(RuntimeError):
    """Something the page should show as a friendly message."""


# --------------------------------------------------------------------------
# the model
# --------------------------------------------------------------------------

def api_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or None


_client = None
_model: str | None = None


def _get_client():
    global _client
    if _client is None:
        if not api_key():
            raise ChatError("No GEMINI_API_KEY is set, so the assistant is switched off.")
        from google import genai                      # imported only when needed
        _client = genai.Client(api_key=api_key())
    return _client


def _generate(prompt: str, *, json_schema: dict | None = None,
              temperature: float = 0.2) -> str:
    """One Gemini call.

    Tries the configured model first, then the fallbacks. A model that is
    missing (404) or busy (5xx, e.g. "503 model overloaded" on the free tier)
    is retried once after a short pause, then the next model is tried.
    """
    global _model
    from google.genai import errors, types

    config = types.GenerateContentConfig(
        temperature=temperature,
        response_mime_type="application/json" if json_schema else "text/plain",
        response_json_schema=json_schema,
        # We never give Gemini tools, so switch the tool-calling helper off
        # (this also silences the "AFC" notice in the terminal).
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    preferred = _model or os.getenv("GEMINI_MODEL")
    candidates = list(dict.fromkeys([m for m in [preferred, *MODELS] if m]))
    problems = []
    for name in candidates:
        for attempt in (1, 2):
            try:
                reply = _get_client().models.generate_content(model=name, contents=prompt,
                                                              config=config)
                _model = name
                return (reply.text or "").strip()
            except errors.ClientError as exc:
                code = getattr(exc, "code", None)
                if code == 404:                       # model not available: next model
                    problems.append(f"{name}: not available")
                    break
                if code == 429:
                    raise ChatError("The free Gemini quota is used up for the moment. "
                                    "Wait a minute and ask again.") from None
                if code in (400, 401, 403) and "key" in str(exc).lower():
                    raise ChatError("Gemini rejected the API key. Check GEMINI_API_KEY.") from None
                raise ChatError(f"Gemini refused the request: {exc}") from None
            except errors.ServerError as exc:         # busy / overloaded
                problems.append(f"{name}: {getattr(exc, 'code', '')} {getattr(exc, 'status', '')}".strip())
                if attempt == 1:
                    time.sleep(2)
                    continue
                break
    raise ChatError("Gemini is busy or unavailable right now (" + "; ".join(problems[-3:])
                    + "). Try again in a minute.")


def model_name() -> str | None:
    return _model or os.getenv("GEMINI_MODEL")


# --------------------------------------------------------------------------
# what Gemini is told about the database
# --------------------------------------------------------------------------

NOTES = """
Facts about this database (PostgreSQL):
- It holds every men's and women's ODI and T20 INTERNATIONAL from 2002 to 2026,
  ball by ball (source: Cricsheet). No Tests, no IPL/leagues, no domestic cricket.
- fact_match.match_format is 'ODI' or 'T20I'. gender is 'male' or 'female'
  (on fact_match, dim_team, dim_player, dim_series).
- Men's and women's sides are separate teams: dim_team.team_name = 'India' for
  both, so filter by gender too; team_display is 'India' / 'India Women'.
- Player names are Cricsheet style: initials + surname ('V Kohli', 'RG Sharma',
  'S Mandhana'). Always match players with ILIKE '%surname%' and, if the name
  is ambiguous, also on primary_team or gender.
- fact_match.winner_id is NULL for no result / tie. victory_type is 'runs',
  'wickets', 'tie', 'no result' or 'super over'; victory_margin is the number.
- toss_decision is 'bat' or 'field'. match_date is a date; dim_date has year,
  quarter, month.
- fact_batting: one row per batter per innings (runs_scored, balls_faced, fours,
  sixes, is_not_out, dismissal_kind, batting_position). Batting average =
  SUM(runs_scored) / NULLIF(COUNT(*) FILTER (WHERE NOT is_not_out), 0).
  Strike rate = 100.0 * SUM(runs_scored) / NULLIF(SUM(balls_faced), 0).
  A hundred = runs_scored >= 100; a fifty = 50-99.
- fact_bowling: balls_bowled, runs_conceded, wickets, maidens, dots.
  Economy = 6.0 * SUM(runs_conceded) / NULLIF(SUM(balls_bowled), 0).
- fact_over.phase is 'powerplay', 'middle' or 'death'.
- fact_innings.innings_no 1 = batting first, 2 = chasing; runs_total, wickets_lost.
- dim_venue.home_nation is the team that plays at home there.
- "Recent" / "last N days" should count back from (SELECT MAX(match_date) FROM fact_match).
""".strip()

_schema_text: str | None = None


def schema_text() -> str:
    global _schema_text
    if _schema_text is None:
        cols = run_query("""
            SELECT table_name, string_agg(column_name, ', ' ORDER BY ordinal_position) AS cols
            FROM   information_schema.columns
            WHERE  table_schema = 'public'
            GROUP BY table_name ORDER BY table_name
        """)
        _schema_text = "\n".join(f"{r.table_name}({r.cols})" for r in cols.itertuples())
    return _schema_text


def _history_text(history: list[dict]) -> str:
    lines = []
    for m in history[-HISTORY_TURNS:]:
        who = "User" if m["role"] == "user" else "Assistant"
        lines.append(f"{who}: {m['content']}")
        if m.get("sql"):
            lines.append(f"(SQL used: {m['sql']})")
    return "\n".join(lines) or "(no earlier messages)"


# --------------------------------------------------------------------------
# step 1: plan
# --------------------------------------------------------------------------

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "mode": {"type": "string", "enum": ["sql", "general"]},
        "sql": {"type": "string"},
        "answer": {"type": "string"},
    },
    "required": ["mode"],
}


def plan(question: str, history: list[dict]) -> dict:
    prompt = f"""You are the analyst inside a cricket statistics dashboard.

Tables and columns:
{schema_text()}

{NOTES}

Conversation so far (use it to understand follow-up questions like
"and in T20Is?" or "only since 2020"):
{_history_text(history)}

New question: {question}

Decide:
- If the database above can answer it, reply with mode "sql" and ONE PostgreSQL
  SELECT (a WITH ... SELECT is fine). Read-only, no semicolon, name output
  columns clearly, round decimals to 2, sort sensibly, and add LIMIT 50 or
  less unless the user wants everything.
- Otherwise (Tests, IPL, cricket before 2002, rules, opinions, news, anything
  not in these tables), reply with mode "general" and a short, accurate answer
  in "answer" from your own cricket knowledge. Say plainly if you are not sure.
Reply as JSON only."""
    raw = _generate(prompt, json_schema=PLAN_SCHEMA)
    try:
        data = json.loads(raw)
    except ValueError:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise ChatError("The assistant replied in an unexpected format. Try rephrasing.")
        data = json.loads(match.group(0))
    if data.get("mode") == "sql" and not (data.get("sql") or "").strip():
        data["mode"] = "general"
    return data


def fix_sql(question: str, sql: str, error: str) -> str:
    prompt = f"""This PostgreSQL query failed.

Tables and columns:
{schema_text()}

{NOTES}

Question: {question}
Query:
{sql}
Error: {error}

Reply as JSON with the corrected read-only query in "sql" (mode "sql")."""
    data = json.loads(_generate(prompt, json_schema=PLAN_SCHEMA))
    return (data.get("sql") or "").strip()


# --------------------------------------------------------------------------
# running the SQL safely
# --------------------------------------------------------------------------

def clean_sql(sql: str) -> str:
    """Strip fences and a trailing semicolon; refuse anything but one read."""
    sql = re.sub(r"^```(?:sql)?|```$", "", sql.strip(), flags=re.I | re.M).strip()
    sql = sql.rstrip().rstrip(";").strip()
    body = re.sub(r"'(?:[^']|'')*'", "''", sql)          # ignore text inside quotes
    body = re.sub(r"--[^\n]*", "", body)
    if ";" in body:
        raise ChatError("Only one query at a time is allowed.")
    if not re.match(r"^\s*(select|with)\b", body, re.I):
        raise ChatError("Only SELECT queries are allowed.")
    bad = FORBIDDEN.search(body)
    if bad:
        raise ChatError(f"The query was blocked because it contains “{bad.group(0)}”. "
                        "The assistant can only read data.")
    return sql


def run_readonly(sql: str) -> pd.DataFrame:
    """Run a query in a READ ONLY transaction with a timeout and a row cap."""
    try:
        with get_engine().connect() as conn:
            with conn.begin():
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(text(f"SET LOCAL statement_timeout = {TIMEOUT_MS}"))
                return pd.read_sql(text(f"SELECT * FROM ({sql}) AS answer LIMIT {MAX_ROWS}"),
                                   conn)
    except Exception as exc:                              # noqa: BLE001
        message = str(getattr(exc, "orig", exc)).splitlines()[0]
        raise DatabaseError(message) from exc


# --------------------------------------------------------------------------
# step 2: explain
# --------------------------------------------------------------------------

def explain(question: str, sql: str, df: pd.DataFrame) -> str:
    sample = df.head(ROWS_FOR_ANSWER).to_csv(index=False)
    more = (f"\n(Only the first {ROWS_FOR_ANSWER} of {len(df)} rows are shown here.)"
            if len(df) > ROWS_FOR_ANSWER else "")
    prompt = f"""Question: {question}

The database query returned {len(df)} rows:
{sample}{more}

Write the answer for a cricket fan in 1-4 short sentences. Use ONLY numbers
that appear in these rows; never invent or estimate. Use **bold** for the key
figure. If the result is empty, say the archive (ODIs and T20Is, 2002-2026)
has no matching data and suggest how to rephrase. Do not mention SQL."""
    return _generate(prompt, temperature=0.3)


# --------------------------------------------------------------------------
# the whole turn
# --------------------------------------------------------------------------

@dataclass
class Reply:
    content: str
    source: str                         # "database" | "general" | "error"
    sql: str | None = None
    data: pd.DataFrame | None = field(default=None, repr=False)


def ask(question: str, history: list[dict]) -> Reply:
    decision = plan(question, history)
    if decision.get("mode") != "sql":
        return Reply(decision.get("answer") or "I'm not sure about that one.", "general")

    sql = clean_sql(decision["sql"])
    try:
        df = run_readonly(sql)
    except DatabaseError as first:
        sql = clean_sql(fix_sql(question, sql, str(first)))          # one retry
        try:
            df = run_readonly(sql)
        except DatabaseError as second:
            return Reply("I couldn't build a working query for that. Try rephrasing "
                         f"it. (Database said: {second})", "error", sql=sql)
    return Reply(explain(question, sql, df), "database", sql=sql, data=df)