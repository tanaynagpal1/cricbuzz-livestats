"""
The Story — how international cricket has changed, told in four chapters.

    Chapter 1  How scoring changed   utils/story_ch1.py
    Chapter 2  The chase             utils/story_ch2.py
    Chapter 3  The grounds           utils/story_ch3.py
    Chapter 4  The batters           (next)

This file only draws the heading, the page switch and the tabs; each
chapter lives in its own file, so one can be changed without touching the
others. Shared settings and helpers are in utils/story.py.

Everything follows the sidebar filters. ODIs and T20Is are never averaged
together: each format is always its own line, bar or panel.

"Full members only": since January 2019 every ICC member plays official
T20Is, so the archive fills with matches between smaller associate sides.
The switch keeps only matches where BOTH sides are one of the 12 full
members.
"""

from __future__ import annotations

import streamlit as st

from utils import story_ch1, story_ch2, story_ch3, story_ch4
from utils.filters import current_gender, gender_label, match_where
from utils.story import Ctx
from utils.theme import page_header

page_header("The Story",
            "How international cricket has changed since 2002 — told from every ball in the archive.",
            eyebrow="Analytics")

scope_choice = st.segmented_control(
    "Which matches", ["All internationals", "Full members only"],
    default="All internationals", key="story_scope",
    help="Since 2019 every ICC member plays official T20Is, so the archive "
         "fills with matches between smaller sides. 'Full members only' keeps "
         "matches where both teams are one of the 12 full members.")
full_members = scope_choice == "Full members only"

where, params = match_where("m")
ctx = Ctx(
    where=where,
    params=params,
    full_members=full_members,
    scope_note="full members only" if full_members else "all internationals",
    # Men's and women's cricket score at different rates; say so when mixed.
    who=(gender_label() if current_gender()
         else "Men's and women's together (use the sidebar switch to split them)"),
)

tab1, tab2, tab3, tab4 = st.tabs(["1 · How scoring changed", "2 · The chase",
                                  "3 · The grounds", "4 · The batters"])
with tab1:
    story_ch1.render(ctx)
with tab2:
    story_ch2.render(ctx)
with tab3:
    story_ch3.render(ctx)
with tab4:
    story_ch4.render(ctx)