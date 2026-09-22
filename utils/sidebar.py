"""
The sidebar: the global filters, then a small status panel.

The filters themselves live in utils/filters.py. Page-specific filters
(e.g. stat type on Top Stats) are added by each page underneath these,
with `with st.sidebar:`, so this file stays the same as pages are added.
"""

from __future__ import annotations

import streamlit as st

from utils import api_client
from utils.db_connection import warm_up
from utils.filters import draw_filters


@st.cache_data(ttl=60, show_spinner=False)
def _db_online() -> bool:
    # Cached for a minute so the check doesn't run on every click.
    return warm_up()


def _ago(seconds: float | None) -> str:
    if seconds is None:
        return "not yet"
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    return f"{int(seconds // 3600)} h ago"


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown('<div class="cb-side-label">Filters</div>', unsafe_allow_html=True)
        draw_filters()

        st.markdown('<div class="cb-side-label">Status</div>', unsafe_allow_html=True)

        db_ok = _db_online()
        quota = api_client.get_quota()
        if quota:
            used = quota["limit"] - quota["remaining"]
            api_text = f'{used} of {quota["limit"]} calls used'
            api_state = "ok" if quota["remaining"] > 50 else "warn"
        else:
            api_text, api_state = "no calls made yet", "ok"

        st.markdown(
            '<div class="cb-status">'
            f'<div><span class="dot {"ok" if db_ok else "bad"}"></span>'
            f'Database <b>{"connected" if db_ok else "offline"}</b></div>'
            f'<div><span class="dot {api_state}"></span>Cricbuzz API <b>{api_text}</b></div>'
            f'<div><span class="dot none"></span>Live scores refreshed '
            f'<b>{_ago(api_client.cache_age("matches_live"))}</b></div>'
            '</div>',
            unsafe_allow_html=True,
        )