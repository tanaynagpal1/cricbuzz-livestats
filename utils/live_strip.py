"""
The thin live-score strip shown under the navigation on every page.

It reads the Cricbuzz API through utils/api_client.py, which keeps each
answer on disk for 2 minutes, so clicking between pages costs nothing. When
no international is being played, it shows the next scheduled one instead.

If the API is down or the monthly quota is spent, the strip says so in one
quiet line and the rest of the page carries on. A broken ticker must never
break the page under it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape

import streamlit as st

from utils import api_client
from utils.transformers import to_utc

# Which blocks of the API's match lists to show: men's and women's
# internationals. League and domestic cricket would crowd the strip out.
SHOW_TYPES = {"International", "Women"}
MAX_ITEMS = 3


def _walk(payload: dict):
    """Yield (matchInfo, matchScore) pairs.

    api_client.iter_matches() yields matchInfo only; the strip also needs the
    score, which sits next to it in the same entry.
    """
    for type_block in payload.get("typeMatches", []):
        if type_block.get("matchType") not in SHOW_TYPES:
            continue
        for series_block in type_block.get("seriesMatches", []):
            wrapper = series_block.get("seriesAdWrapper")
            if not wrapper:
                continue                          # an advert, not a series
            for match in wrapper.get("matches", []):
                if match.get("matchInfo"):
                    yield match["matchInfo"], match.get("matchScore", {})


def _innings(score_block: dict | None) -> str:
    """'245/3 (38.2)' from one team's score block. Latest innings wins."""
    if not score_block:
        return ""
    last = score_block.get("inngs2") or score_block.get("inngs1") or {}
    if "runs" not in last:
        return ""
    wickets = last.get("wickets", 0)
    runs = f"{last['runs']}" if wickets == 10 else f"{last['runs']}/{wickets}"
    overs = f" ({last['overs']})" if last.get("overs") is not None else ""
    return runs + overs


def _live_items() -> list[str]:
    items = []
    for info, score in _walk(api_client.get_live_matches()):
        t1 = info.get("team1", {}).get("teamSName", "?")
        t2 = info.get("team2", {}).get("teamSName", "?")
        s1 = _innings(score.get("team1Score"))
        s2 = _innings(score.get("team2Score"))
        fmt = info.get("matchFormat", "")
        items.append(
            f'<span class="cb-strip-item"><b>{escape(t1)}</b> {escape(s1)}'
            f' <i>v</i> <b>{escape(t2)}</b> {escape(s2)}'
            f' <em>{escape(fmt)}</em></span>'
        )
        if len(items) == MAX_ITEMS:
            break
    return items


def _next_fixture() -> str | None:
    """The soonest upcoming international, as one short line."""
    now = datetime.now(timezone.utc)
    upcoming = []
    for info, _ in _walk(api_client.get_upcoming_matches()):
        start = to_utc(info.get("startDate"))
        if start and start > now:
            upcoming.append((start, info))
    if not upcoming:
        return None
    start, info = min(upcoming, key=lambda pair: pair[0])
    t1 = info.get("team1", {}).get("teamSName", "?")
    t2 = info.get("team2", {}).get("teamSName", "?")
    when = start.strftime("%a %d %b, %H:%M UTC")
    return (f'<b>{escape(t1)}</b> <i>v</i> <b>{escape(t2)}</b> '
            f'{escape(info.get("matchDesc", ""))} · {when}')


def live_strip() -> None:
    """Draw the strip. Safe to call on every page: it never raises."""
    try:
        items = _live_items()
        if items:
            body = ('<span class="cb-strip-badge live">● LIVE</span>'
                    + '<span class="cb-strip-sep">·</span>'.join(items))
        else:
            nxt = _next_fixture()
            body = ('<span class="cb-strip-badge">NO LIVE INTERNATIONALS</span>'
                    + (f'<span class="cb-strip-item">Next: {nxt}</span>' if nxt else ""))
    except api_client.CricbuzzError as exc:
        body = ('<span class="cb-strip-badge off">LIVE FEED UNAVAILABLE</span>'
                f'<span class="cb-strip-item muted">{escape(str(exc))}</span>')

    st.markdown(f'<div class="cb-strip">{body}</div>', unsafe_allow_html=True)