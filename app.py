"""
Cricbuzz LiveStats — application entry point.

Run with:  streamlit run app.py

This file does five things, in this order, on every page load:
  1. page settings and the theme
  2. the logo, top-left in the navigation bar
  3. the navigation bar itself (pages across the top)
  4. the sidebar (filters + status panel)
  5. the live-score strip, the active-filters line, then the chosen page

Because steps 3-5 happen here and not inside each page, every page gets the
same navigation, sidebar and live strip without repeating any code.
"""

from __future__ import annotations

import streamlit as st

from utils.filters import filter_bar
from utils.live_strip import live_strip
from utils.sidebar import render_sidebar
from utils.theme import apply_theme

# set_page_config must be the first Streamlit call.
st.set_page_config(
    page_title="Cricbuzz LiveStats",
    page_icon="🏏",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "about": "Cricbuzz LiveStats — real-time cricket insights and "
                 "SQL-based analytics. Historical data from Cricsheet, "
                 "live data from the Cricbuzz API."
    },
)

apply_theme()

# The full logo shows in the sidebar; the small icon shows when it is closed.
st.logo("assets/logo.svg", size="large", icon_image="assets/icon.svg")

# Streamlit caps the logo at 32px tall, which is too small for a two-line
# logo. This raises the cap to 64px for the sidebar logo only.
st.markdown(
    """<style>
    [data-testid="stSidebarHeader"] { height: auto; padding-top: 1.2rem; }
    [data-testid="stSidebarHeader"] > div { height: auto; }
    img[data-testid="stSidebarLogo"] { height: 64px; max-width: 220px; }
    </style>""",
    unsafe_allow_html=True,
)

# Pages grouped into menus. In the top bar, each named group becomes a
# dropdown ("Live ▾", "Analytics ▾"); the group with an empty name shows its
# pages as plain links.
PAGES = {
    "": [
        st.Page("pages/1_Home.py", title="Home", icon=":material/home:", default=True),
    ],
    "Live": [
        st.Page("pages/2_Live_Matches.py", title="Live Matches", icon=":material/sensors:"),
        st.Page("pages/3_Top_Stats.py", title="Top Stats", icon=":material/leaderboard:"),
    ],
    "Analytics": [
        st.Page("pages/7_The_Story.py", title="The Story", icon=":material/auto_stories:"),
        st.Page("pages/6_Match_Centre.py", title="Match Centre", icon=":material/stadium:"),
        st.Page("pages/8_Player_Lab.py", title="Player Lab", icon=":material/person_search:"),
        st.Page("pages/9_Rivalries.py", title="Rivalries", icon=":material/swords:"),
        st.Page("pages/4_SQL_Analytics.py", title="SQL Analytics", icon=":material/query_stats:"),
    ],
    "Manage": [
        st.Page("pages/5_CRUD_Operations.py", title="Manage Data", icon=":material/edit_note:"),
    ],
    "Ask AI": [
        st.Page("pages/10_Ask_AI.py", title="Cricket Chat", icon=":material/smart_toy:"),
    ],
}

# position="top" puts the menus in a bar across the top of the screen,
# leaving the sidebar free for filters.
page = st.navigation(PAGES, position="top")

render_sidebar()
live_strip()
filter_bar()

page.run()