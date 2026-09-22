"""
Manage Data — create, read, update and delete player records.

    Browse   search and filter the player table, and download it as CSV (Read)
    Add      a form that inserts a new player (Create)
    Edit     pick a player, change their details, save (Update)
    Delete   remove a player - but only if nothing else refers to them

Every write goes through utils/db_connection.execute(), which runs it
inside a transaction: it either commits completely or rolls back
completely. Values are always passed as parameters, never pasted into the
SQL text.

The database protects itself with constraints, and this page shows them
working instead of hiding them:
  * a player who appears in scorecards cannot be deleted (foreign keys);
  * the last match cannot be before the debut (checked here, and again by
    a CHECK constraint in the database);
  * gender must be male or female (a CHECK constraint).

Browsing is open to everyone. Adding, editing and deleting are locked
behind a password (MANAGE_PASSWORD, kept in .env locally and in the
Streamlit Cloud secrets online), because the app is public and the
database is real. If no password is set, editing stays locked.

Players added here get an id starting with "usr_", so they are easy to tell
apart from the players loaded from Cricsheet.

The columns worked out by the ETL from the scorecards (teams played for,
bowling share, average batting position, dismissal rate) are shown but not
editable: they are facts calculated from matches, not details to type in.
"""

from __future__ import annotations

import hmac
import os
import secrets
from datetime import date, datetime

import pandas as pd
import streamlit as st

from utils.db_connection import DatabaseError, execute, run_query, run_scalar
from utils.theme import page_header, rule, section, tiles

GENDERS = {"male": "Men's", "female": "Women's"}
ROLES = ["Batsman", "Bowler", "All-rounder", "Wicket-keeper", "Unknown"]
BATTING_STYLES = ["Right-hand bat", "Left-hand bat"]
NEW_ID_PREFIX = "usr_"
BROWSE_LIMIT = 500

# Every column in the database that points at a player, and what it means.
REFERENCES = [
    ("fact_batting", "player_id", "batting innings"),
    ("fact_batting", "dismissed_by_id", "dismissals as the bowler"),
    ("fact_batting", "fielder_id", "catches / run-outs"),
    ("fact_bowling", "player_id", "bowling innings"),
    ("fact_partnership", "batter1_id", "partnerships"),
    ("fact_partnership", "batter2_id", "partnerships"),
    ("fact_over", "bowler_id", "overs bowled"),
    ("fact_match", "player_of_match_id", "player-of-the-match awards"),
]


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------

@st.cache_data(ttl=600, show_spinner=False)
def counts() -> dict:
    return run_query("""
        SELECT COUNT(*)                                            AS players,
               COUNT(*) FILTER (WHERE gender = 'male')             AS men,
               COUNT(*) FILTER (WHERE gender = 'female')           AS women,
               COUNT(*) FILTER (WHERE player_id LIKE 'usr\\_%')    AS added
        FROM dim_player
    """).iloc[0].to_dict()


@st.cache_data(ttl=600, show_spinner=False)
def team_names(gender: str) -> list[str]:
    return run_query("SELECT team_name FROM dim_team WHERE gender = :g ORDER BY team_name",
                     {"g": gender})["team_name"].tolist()


@st.cache_data(ttl=600, show_spinner=False)
def player_options() -> pd.DataFrame:
    """Every player, for the Edit and Delete pickers. Newest additions first."""
    return run_query("""
        SELECT player_id,
               player_name || ' · ' || COALESCE(primary_team, 'no team') || ' · '
                 || CASE gender WHEN 'male' THEN 'Men' ELSE 'Women' END AS label
        FROM dim_player
        ORDER BY (player_id LIKE 'usr\\_%') DESC, player_name
    """)


@st.cache_data(ttl=600, show_spinner=False)
def matching_players(q: str | None, g: str | None, r: str | None,
                     added: bool) -> pd.DataFrame:
    """Every player matching the Browse filters. Cached, and cleared after
    any change, so the table and the download always show the latest data."""
    return run_query("""
        SELECT player_id, player_name, gender, primary_team, playing_role,
               batting_style, bowling_style, debut, last_match, teams_played_for
        FROM dim_player
        WHERE (CAST(:q AS text) IS NULL OR player_name ILIKE '%' || :q || '%')
          AND (CAST(:g AS text) IS NULL OR gender = :g)
          AND (CAST(:r AS text) IS NULL OR playing_role = :r)
          AND (NOT :added OR player_id LIKE 'usr\\_%')
        ORDER BY last_match DESC NULLS LAST, player_name
    """, {"q": q, "g": g, "r": r, "added": added})


def get_player(player_id: str) -> dict | None:
    df = run_query("SELECT * FROM dim_player WHERE player_id = :p", {"p": player_id})
    return None if df.empty else df.iloc[0].to_dict()


def reference_counts(player_id: str) -> dict[str, int]:
    """How many rows in each fact table point at this player."""
    found: dict[str, int] = {}
    for table, column, meaning in REFERENCES:
        n = run_scalar(f"SELECT COUNT(*) FROM {table} WHERE {column} = :p", {"p": player_id})
        if n:
            found[meaning] = found.get(meaning, 0) + int(n)
    return found


def refresh() -> None:
    """After a write, forget cached reads so every page shows the change."""
    st.cache_data.clear()


def log(action: str, detail: str) -> None:
    st.session_state.setdefault("crud_log", []).insert(
        0, {"Time": datetime.now().strftime("%H:%M:%S"), "Action": action, "Detail": detail})


def player_picker(key: str, label: str) -> str | None:
    options = player_options()
    labels = dict(zip(options["player_id"], options["label"]))
    return st.selectbox(label, options=list(labels), format_func=labels.get, index=None,
                        placeholder="Type a player's name", key=key)


def clean(text: str | None) -> str | None:
    text = (text or "").strip()
    return text or None


def password_ok(typed: str) -> bool:
    """Compare in constant time, so the check leaks nothing about the answer."""
    expected = os.getenv("MANAGE_PASSWORD") or ""
    return bool(expected) and hmac.compare_digest(typed.encode(), expected.encode())


def _unlock() -> None:
    if password_ok(st.session_state.get("crud_pw", "")):
        st.session_state["crud_unlocked"] = True
        st.session_state["crud_pw_bad"] = False
    else:
        st.session_state["crud_pw_bad"] = True
    st.session_state["crud_pw"] = ""                 # never keep the typed password


def _lock() -> None:
    st.session_state["crud_unlocked"] = False


def edit_lock() -> bool:
    """The lock bar. Returns True when this visitor may add, edit and delete."""
    if not os.getenv("MANAGE_PASSWORD"):
        st.info("Editing is switched off: no MANAGE_PASSWORD is set for this app. "
                "Browsing and downloading still work.", icon=":material/lock:")
        return False
    if st.session_state.get("crud_unlocked"):
        left, right = st.columns([4, 1])
        left.success("Editing unlocked for this session.", icon=":material/lock_open:")
        right.button("Lock again", key="crud_lock", on_click=_lock, width="stretch")
        return True
    with st.container(border=True):
        st.markdown(":material/lock: **Editing is locked.** Anyone can browse and download; "
                    "adding, editing and deleting need the project password.")
        left, right = st.columns([3, 1], vertical_alignment="bottom")
        left.text_input("Password", type="password", key="crud_pw",
                        placeholder="Project password")
        right.button("Unlock", key="crud_unlock", on_click=_unlock, type="primary",
                     width="stretch")
        if st.session_state.get("crud_pw_bad"):
            st.error("That password is not right.")
    return False


# --------------------------------------------------------------------------
# page
# --------------------------------------------------------------------------

page_header("Manage Data",
            "Create, read, update and delete player records — every change runs as a "
            "transaction, and the database's own rules are shown, not hidden.",
            eyebrow="Manage")

try:
    c = counts()
except DatabaseError as exc:
    st.error(f"Could not reach the database: {exc}")
    st.stop()

tiles([
    ("Players", f"{c['players']:,}", "rows in dim_player"),
    ("Men's", f"{c['men']:,}", ""),
    ("Women's", f"{c['women']:,}", ""),
    ("Added here", f"{c['added']:,}", f"ids starting {NEW_ID_PREFIX}"),
])
st.caption("The sidebar filters do not apply on this page. Changes here are real: they are "
           "saved to the database and show up on every other page.")

# A message from the last action survives the rerun that follows it.
if "crud_flash" in st.session_state:
    kind, message = st.session_state.pop("crud_flash")
    getattr(st, kind)(message)

can_edit = edit_lock()
LOCKED_NOTE = "Unlock editing above to use this tab. Browsing and downloading need no password."

browse_tab, add_tab, edit_tab, delete_tab = st.tabs(
    ["Browse", "Add a player", "Edit a player", "Delete a player"])

# ---- READ ------------------------------------------------------------------
with browse_tab:
    left, middle, right = st.columns([2, 1, 1])
    with left:
        name = st.text_input("Name contains", key="crud_q", placeholder="e.g. Kohli")
    with middle:
        gender_pick = st.selectbox("Cricket", ["All", *GENDERS], key="crud_g",
                                   format_func=lambda g: GENDERS.get(g, g))
    with right:
        role_pick = st.selectbox("Role", ["All", *ROLES], key="crud_r")
    only_added = st.toggle("Only players added on this page", key="crud_added")

    filters = {"q": clean(name), "g": None if gender_pick == "All" else gender_pick,
               "r": None if role_pick == "All" else role_pick, "added": only_added}
    everything = matching_players(**filters)          # every match, for the download
    df = everything.head(BROWSE_LIMIT)                # the first 500, for the screen
    st.caption(f"{len(everything):,} players match, most recently active first"
               + (f" — showing the first {BROWSE_LIMIT}; the download has all of them."
                  if len(everything) > BROWSE_LIMIT else "."))
    st.dataframe(df, hide_index=True, width="stretch", height=min(520, 40 + 35 * len(df)),
                 column_config={"player_id": "Id", "player_name": "Name", "gender": "Gender",
                                "primary_team": "Team", "playing_role": "Role",
                                "batting_style": "Batting", "bowling_style": "Bowling",
                                "debut": "Debut", "last_match": "Last match",
                                "teams_played_for": "Teams"})
    st.download_button(f"Download {len(everything):,} players as CSV",
                       data=everything.to_csv(index=False).encode("utf-8"),
                       file_name=f"players_{date.today():%Y%m%d}.csv", mime="text/csv",
                       key="crud_download", disabled=everything.empty)

# ---- CREATE ----------------------------------------------------------------
with add_tab:
    if not can_edit:
        st.info(LOCKED_NOTE)
    else:
        st.caption("Fields marked * are required. The new player gets an id starting "
                   f"“{NEW_ID_PREFIX}”.")
        gender = st.segmented_control("Cricket *", list(GENDERS), format_func=GENDERS.get,
                                      default="male", key="crud_add_gender") or "male"
        with st.form("crud_add", clear_on_submit=True):
            left, right = st.columns(2)
            with left:
                new_name = st.text_input("Name *", placeholder="e.g. A Sharma")
                new_team = st.selectbox("Team", team_names(gender), index=None,
                                        placeholder="Choose a team")
                new_role = st.selectbox("Role *", ROLES, index=0)
                new_debut = st.date_input("Debut", value=None, max_value=date.today(),
                                          min_value=date(1970, 1, 1))
            with right:
                new_bat = st.selectbox("Batting style", BATTING_STYLES, index=None,
                                       placeholder="Not known")
                new_bowl = st.text_input("Bowling style", placeholder="e.g. Right-arm offbreak")
                st.write("")
                new_last = st.date_input("Last match", value=None, max_value=date.today(),
                                         min_value=date(1970, 1, 1))
            submitted = st.form_submit_button("Add player", type="primary")

        if submitted:
            if not clean(new_name):
                st.error("Please enter a name.")
            elif new_debut and new_last and new_last < new_debut:
                st.error("The last match cannot be before the debut.")
            else:
                new_id = NEW_ID_PREFIX + secrets.token_hex(3)
                try:
                    execute("""
                        INSERT INTO dim_player (player_id, player_name, gender, primary_team,
                                                teams_played_for, playing_role, batting_style,
                                                bowling_style, debut, last_match)
                        VALUES (:id, :name, :gender, :team, :teams, :role, :bat, :bowl,
                                :debut, :last)
                    """, {"id": new_id, "name": clean(new_name), "gender": gender,
                          "team": new_team, "teams": 1 if new_team else 0, "role": new_role,
                          "bat": new_bat, "bowl": clean(new_bowl), "debut": new_debut,
                          "last": new_last})
                except DatabaseError as exc:
                    st.error(f"Not added — the database refused it and nothing was changed. {exc}")
                else:
                    refresh()
                    log("Added", f"{clean(new_name)} ({new_id})")
                    st.session_state["crud_flash"] = (
                        "success", f"Added {clean(new_name)} with id {new_id}.")
                    st.rerun()

# ---- UPDATE ----------------------------------------------------------------
with edit_tab:
    if not can_edit:
        st.info(LOCKED_NOTE)
    else:
        pid = player_picker("crud_edit_pick", "Player to edit")
        player = get_player(pid) if pid else None
        if not player:
            st.info("Choose a player above. Players added on this page are listed first.")
        else:
            g = player["gender"]
            teams = team_names(g)
            if player["primary_team"] and player["primary_team"] not in teams:
                teams = [player["primary_team"], *teams]
            role = player["playing_role"] if player["playing_role"] in ROLES else "Unknown"
            # Keys include the player id, so switching player refills the form.
            with st.form(f"crud_edit_{pid}"):
                left, right = st.columns(2)
                with left:
                    e_name = st.text_input("Name *", value=player["player_name"])
                    e_team = st.selectbox("Team", teams,
                                          index=teams.index(player["primary_team"])
                                          if player["primary_team"] in teams else None,
                                          placeholder="No team")
                    e_role = st.selectbox("Role *", ROLES, index=ROLES.index(role))
                    e_debut = st.date_input("Debut", value=player["debut"], min_value=date(1970, 1, 1),
                                            max_value=date.today())
                with right:
                    e_bat = st.selectbox("Batting style", BATTING_STYLES,
                                         index=BATTING_STYLES.index(player["batting_style"])
                                         if player["batting_style"] in BATTING_STYLES else None,
                                         placeholder="Not known")
                    e_bowl = st.text_input("Bowling style", value=player["bowling_style"] or "")
                    st.text_input("Cricket", value=GENDERS[g], disabled=True,
                                  help="Men's and women's players are separate records, so "
                                       "this cannot be changed.")
                    e_last = st.date_input("Last match", value=player["last_match"],
                                           min_value=date(1970, 1, 1), max_value=date.today())
                saved = st.form_submit_button("Save changes", type="primary")

            st.caption(f"Id {pid} · calculated from scorecards (not editable): teams played for "
                       f"{player['teams_played_for'] if player['teams_played_for'] is not None else '—'}"
                       f" · average batting position "
                       f"{player['avg_position'] if player['avg_position'] is not None else '—'}"
                       f" · share of innings bowling "
                       f"{player['bowl_share'] if player['bowl_share'] is not None else '—'}")

            if saved:
                if not clean(e_name):
                    st.error("The name cannot be empty.")
                elif e_debut and e_last and e_last < e_debut:
                    st.error("The last match cannot be before the debut.")
                else:
                    try:
                        changed = execute("""
                            UPDATE dim_player
                            SET player_name = :name, primary_team = :team, playing_role = :role,
                                batting_style = :bat, bowling_style = :bowl,
                                debut = :debut, last_match = :last
                            WHERE player_id = :id
                        """, {"id": pid, "name": clean(e_name), "team": e_team, "role": e_role,
                              "bat": e_bat, "bowl": clean(e_bowl), "debut": e_debut,
                              "last": e_last})
                    except DatabaseError as exc:
                        st.error(f"Not saved — the database refused it and nothing was changed. {exc}")
                    else:
                        refresh()
                        log("Edited", f"{clean(e_name)} ({pid})")
                        st.session_state["crud_flash"] = (
                            "success", f"Saved {clean(e_name)} ({changed} row updated).")
                        st.rerun()

# ---- DELETE ----------------------------------------------------------------
with delete_tab:
    if not can_edit:
        st.info(LOCKED_NOTE)
    else:
        pid = player_picker("crud_del_pick", "Player to delete")
        player = get_player(pid) if pid else None
        if not player:
            st.info("Choose a player above. Players added on this page are listed first; "
                    "try one of them, then try a well-known player to see the database refuse.")
        else:
            refs = reference_counts(pid)
            if refs:
                st.warning(
                    f"**{player['player_name']}** appears in the scorecards — "
                    + ", ".join(f"{n:,} {what}" for what, n in refs.items())
                    + ". Deleting them would leave those rows pointing at nobody, so the "
                      "database's foreign keys will refuse. You can try it: the transaction "
                      "is rolled back and nothing changes.")
            else:
                st.success(f"Nothing refers to **{player['player_name']}**, so they can be deleted.")

            sure = st.checkbox(f"Yes, delete {player['player_name']} ({pid})", key=f"crud_sure_{pid}")
            if st.button("Delete player", type="primary", disabled=not sure, key="crud_delete"):
                try:
                    execute("DELETE FROM dim_player WHERE player_id = :id", {"id": pid})
                except DatabaseError as exc:
                    log("Refused", f"delete {player['player_name']} ({pid})")
                    st.error(f"Not deleted — nothing was changed. {exc}")
                else:
                    refresh()
                    log("Deleted", f"{player['player_name']} ({pid})")
                    st.session_state.pop("crud_del_pick", None)
                    st.session_state["crud_flash"] = (
                        "success", f"Deleted {player['player_name']}.")
                    st.rerun()

# ---- this session's changes ------------------------------------------------
if st.session_state.get("crud_log"):
    rule()
    section("Changes in this session")
    st.dataframe(pd.DataFrame(st.session_state["crud_log"]), hide_index=True, width="stretch")