"""
Global filters: the controls in the sidebar that apply to every page.

    Men's / Women's · ODI / T20I · Years · Team · Opponent · Host country · Ground

Two jobs live here:

1. draw_filters()   draws the controls (called from the sidebar)
2. match_where()    turns the current choices into a SQL condition on
                    fact_match, so any page can apply them with one line

Every filter starts OFF ("all"). A filter that is off adds nothing to the
SQL, so with no filters set, every query sees the whole archive.

Values always travel as SQL PARAMETERS (:f_team, :f_y0 ...), never pasted
into the SQL text. The only thing pasted in is the table alias, which comes
from our own code, never from the user.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.db_connection import run_query

GENDERS = {"Men's": "male", "Women's": "female"}
# Button label -> the value stored in fact_match.match_format.
FORMATS = {"ODI": "ODI", "T20I": "T20I"}
FIRST_YEAR, LAST_YEAR = 2002, 2026

ALL = "All"

# Every filter's session_state key and its "off" value. The widgets read
# their starting value from here, and "Clear all" puts these values back.
DEFAULTS = {
    "gender_choice": None,
    "format_choice": None,
    "f_years": (FIRST_YEAR, LAST_YEAR),
    "f_team": ALL,
    "f_opp": ALL,
    "f_country": ALL,
    "f_venue": ALL,
}


# --------------------------------------------------------------------------
# reading the current choices
# --------------------------------------------------------------------------

def current_gender() -> str | None:
    """'male', 'female', or None when nothing is selected (= both)."""
    choice = st.session_state.get("gender_choice")
    return GENDERS.get(choice) if choice else None


def gender_label() -> str:
    """For captions: "Men's", "Women's" or "Men's and women's"."""
    return st.session_state.get("gender_choice") or "Men's and women's"


def current_format() -> str | None:
    """'ODI', 'T20I', or None when nothing is selected (= both)."""
    choice = st.session_state.get("format_choice")
    return FORMATS.get(choice) if choice else None


def format_label() -> str:
    """For captions and headings: "ODI", "T20I" or "ODI and T20I"."""
    return current_format() or "ODI and T20I"


def current_years() -> tuple[int, int]:
    return tuple(st.session_state.get("f_years", (FIRST_YEAR, LAST_YEAR)))


def _picked(key: str):
    """The chosen value of a dropdown, or None when it says 'All'."""
    value = st.session_state.get(key)
    return None if value in (None, ALL) else value


# --------------------------------------------------------------------------
# lookup lists for the dropdowns (cached: they only change when the ETL runs)
# --------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def _teams() -> pd.DataFrame:
    return run_query("SELECT team_id, team_display, gender FROM dim_team ORDER BY team_display")


@st.cache_data(ttl=3600, show_spinner=False)
def _venues() -> pd.DataFrame:
    # Only grounds that actually hosted a match in the archive.
    return run_query("""
        SELECT v.venue_id, v.venue_display, v.country
        FROM dim_venue v
        WHERE EXISTS (SELECT 1 FROM fact_match m WHERE m.venue_id = v.venue_id)
        ORDER BY v.venue_display
    """)


def _team_options() -> dict[str, int]:
    """{'India': 12, 'India Women': 13, ...}, following the gender switch."""
    teams = _teams()
    gender = current_gender()
    if gender:
        teams = teams[teams["gender"] == gender]
    return dict(zip(teams["team_display"], teams["team_id"].astype(int)))


def _keep_valid(key: str, options: list[str]) -> None:
    """If a saved choice is no longer offered (e.g. 'India Women' after
    switching to Men's), reset it to 'All' BEFORE the widget is drawn."""
    if st.session_state.get(key) not in (None, *options):
        st.session_state[key] = ALL


# --------------------------------------------------------------------------
# drawing the controls
# --------------------------------------------------------------------------

def draw_filters() -> None:
    """Draw every global filter. Call inside `with st.sidebar:`."""

    # Give each filter its "off" value the first time the app runs. The
    # widgets below then take their value from session_state only (no
    # value= argument), so a reset in _clear_all() shows up on screen too.
    for key, value in DEFAULTS.items():
        st.session_state.setdefault(key, value)

    # ---- Men's / Women's (no default: the app opens showing both)
    st.segmented_control("Show cricket for", options=list(GENDERS),
                         key="gender_choice", label_visibility="collapsed")

    # ---- ODI / T20I (no default either: both formats)
    st.segmented_control("Format", options=list(FORMATS),
                         key="format_choice", label_visibility="collapsed")

    # ---- Years
    st.slider("Years", FIRST_YEAR, LAST_YEAR, key="f_years")

    # ---- Team, then Opponent (only once a team is chosen)
    team_map = _team_options()
    team_names = [ALL, *team_map]
    _keep_valid("f_team", team_names)
    st.selectbox("Team", team_names, key="f_team")

    team = _picked("f_team")
    opp_names = [ALL, *[t for t in team_map if t != team]]
    _keep_valid("f_opp", opp_names)
    st.selectbox("Opponent", opp_names, key="f_opp", disabled=team is None,
                 help="Choose a team first. Then pick an opponent to see "
                      "only their head-to-head matches.")

    # ---- Host country, then Ground (only grounds in that country)
    venues = _venues()
    countries = [ALL, *sorted(venues["country"].unique())]
    _keep_valid("f_country", countries)
    st.selectbox("Host country", countries, key="f_country")

    country = _picked("f_country")
    grounds = venues if country is None else venues[venues["country"] == country]
    ground_names = [ALL, *grounds["venue_display"]]
    _keep_valid("f_venue", ground_names)
    st.selectbox("Ground", ground_names, key="f_venue")


# --------------------------------------------------------------------------
# using the choices in SQL
# --------------------------------------------------------------------------

def match_where(alias: str = "m") -> tuple[str, dict]:
    """A SQL condition on fact_match for the current filters, plus params.

        where, params = match_where("m")
        run_query(f"SELECT ... FROM fact_match m WHERE {where}", params)

    With no filters set it returns ("TRUE", {}), which keeps every row.
    """
    a = alias
    conds: list[str] = []
    params: dict = {}

    if (gender := current_gender()):
        conds.append(f"{a}.gender = :f_gender")
        params["f_gender"] = gender

    if (fmt := current_format()):
        conds.append(f"{a}.match_format = :f_format")
        params["f_format"] = fmt

    y0, y1 = current_years()
    if (y0, y1) != (FIRST_YEAR, LAST_YEAR):
        conds.append(f"{a}.match_date BETWEEN make_date(:f_y0, 1, 1) "
                     f"AND make_date(:f_y1, 12, 31)")
        params.update(f_y0=int(y0), f_y1=int(y1))

    team_map = _team_options()
    if (team := _picked("f_team")) in team_map:
        conds.append(f":f_team IN ({a}.team1_id, {a}.team2_id)")
        params["f_team"] = team_map[team]
        # The opponent only means something alongside a team.
        if (opp := _picked("f_opp")) in team_map:
            conds.append(f":f_opp IN ({a}.team1_id, {a}.team2_id)")
            params["f_opp"] = team_map[opp]

    if (country := _picked("f_country")):
        conds.append(f"{a}.venue_id IN "
                     f"(SELECT venue_id FROM dim_venue WHERE country = :f_country)")
        params["f_country"] = country

    if (ground := _picked("f_venue")):
        venues = _venues()
        match = venues.loc[venues["venue_display"] == ground, "venue_id"]
        if not match.empty:
            conds.append(f"{a}.venue_id = :f_venue")
            params["f_venue"] = int(match.iloc[0])

    return (" AND ".join(conds) or "TRUE"), params


def team_id() -> int | None:
    """The chosen team's id, for pages that also filter players by team."""
    team_map = _team_options()
    team = _picked("f_team")
    return team_map.get(team) if team else None


# --------------------------------------------------------------------------
# the "active filters" line with a Clear all button
# --------------------------------------------------------------------------

def active_filters() -> list[str]:
    """Short labels for every filter that is ON."""
    labels = []
    if current_gender():
        labels.append(gender_label())
    if current_format():
        labels.append(format_label())
    y0, y1 = current_years()
    if (y0, y1) != (FIRST_YEAR, LAST_YEAR):
        labels.append(f"{y0}–{y1}")
    if (team := _picked("f_team")):
        opp = _picked("f_opp")
        labels.append(f"{team} v {opp}" if opp else team)
    if (country := _picked("f_country")):
        labels.append(f"in {country}")
    if (ground := _picked("f_venue")):
        labels.append(f"at {ground}")
    return labels


def _clear_all() -> None:
    # Runs as a button callback, i.e. BEFORE the widgets are drawn again,
    # which is the moment Streamlit allows widget values to be changed.
    # Values are SET back to "off", not deleted: deleting a key resets the
    # number the page uses but leaves the old choice showing in the sidebar.
    for key, value in DEFAULTS.items():
        st.session_state[key] = value


def filter_bar() -> None:
    """One line under the live strip, shown only when a filter is on."""
    labels = active_filters()
    if not labels:
        return
    chips = "".join(f'<span class="cb-chip on">{label}</span>' for label in labels)
    left, right = st.columns([6, 1], vertical_alignment="center")
    with left:
        st.markdown(f'<div class="cb-filterbar"><span class="cb-filterbar-label">'
                    f'Filters</span>{chips}</div>', unsafe_allow_html=True)
    with right:
        st.button("Clear all", on_click=_clear_all, width="stretch")