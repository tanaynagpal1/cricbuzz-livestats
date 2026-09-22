"""
Live Matches — what is being played now, what just finished, and what is next.

    live      matches in progress (and ones that finished today), with scores
    recent    recently completed matches and their results
    upcoming  the schedule, with start times in Indian time
    scorecard pick any match above and load its full scorecard

Everything here comes from the Cricbuzz API through utils/api_client.py.
Nothing is stored in the database: live scores change every ball.

The free API plan allows only a few hundred calls a month, so:
  * the three lists are cached on disk (live 2 min, recent/upcoming 5 min);
  * a scorecard is loaded only when you press the button, and is then
    cached for an hour.
The sidebar filters are for the historical archive and do not apply here;
this page has its own "which cricket" filter.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from utils import api_client
from utils.theme import page_header, rule, section
from utils.transformers import economy, overs_to_balls, strike_rate, to_utc

IST = ZoneInfo("Asia/Kolkata")
# The API groups matches into these blocks. Internationals first.
MATCH_TYPES = ["International", "Women", "Domestic", "League"]
# What we show for each API block. "International" is the API's name for men's
# internationals; women's matches of every kind sit in their own "Women" block.
KIND_LABELS = {"International": "Men's international", "Women": "Women's",
               "Domestic": "Domestic", "League": "League"}
FORMAT_NAMES = {"T20": "T20", "ODI": "ODI", "TEST": "Test"}
MAX_CARDS = 24          # per list, so a busy day does not produce a wall of cards


# --------------------------------------------------------------------------
# reading the API's match lists
# --------------------------------------------------------------------------

def walk(payload: dict, types: set[str]) -> list[dict]:
    """Flatten a /matches/v1/* answer into one dict per match.

    The shape is typeMatches -> seriesMatches -> seriesAdWrapper -> matches,
    with adverts mixed into seriesMatches (they have no seriesAdWrapper).
    """
    rows = []
    for type_block in payload.get("typeMatches", []):
        kind = type_block.get("matchType")
        if kind not in types:
            continue
        for series_block in type_block.get("seriesMatches", []):
            wrapper = series_block.get("seriesAdWrapper")
            if not wrapper:
                continue
            for match in wrapper.get("matches", []):
                info = match.get("matchInfo")
                if info:
                    rows.append({"kind": kind, "info": info,
                                 "score": match.get("matchScore", {})})
    return rows


def overs_text(overs) -> str:
    """The API writes a completed 20th over as '19.6'. Through real balls it
    becomes '20'; '13.4' stays '13.4'."""
    balls = overs_to_balls(overs)
    if balls is None:
        return ""
    return f"{balls // 6}" if balls % 6 == 0 else f"{balls // 6}.{balls % 6}"


def innings_text(score_block: dict | None) -> str:
    """'245/3 (38.2)' for one team; both innings for a Test ('245 & 180/4')."""
    if not score_block:
        return ""
    parts = []
    for key in ("inngs1", "inngs2"):
        inn = score_block.get(key)
        if not inn or "runs" not in inn:
            continue
        wk = inn.get("wickets", 0)
        text = f"{inn['runs']}" if wk == 10 else f"{inn['runs']}/{wk}"
        if inn.get("isDeclared"):
            text += "d"
        parts.append(text)
    last = score_block.get("inngs2") or score_block.get("inngs1") or {}
    overs = f" ({overs_text(last['overs'])})" if last.get("overs") is not None else ""
    return " & ".join(parts) + overs


def start_text(info: dict) -> str:
    start = to_utc(info.get("startDate"))
    return start.astimezone(IST).strftime("%a %d %b · %H:%M IST") if start else ""


def label_of(row: dict) -> str:
    info = row["info"]
    t1 = info.get("team1", {}).get("teamSName", "?")
    t2 = info.get("team2", {}).get("teamSName", "?")
    return (f"{t1} v {t2} · {info.get('matchDesc', '')} · "
            f"{info.get('seriesName', '')}")


def match_card(row: dict, show_time: bool = False) -> None:
    """One match as a bordered card: series, teams and scores, status."""
    info, score = row["info"], row["score"]
    t1, t2 = info.get("team1", {}), info.get("team2", {})
    fmt = FORMAT_NAMES.get(info.get("matchFormat", ""), info.get("matchFormat", ""))
    state = info.get("state", "")
    live = state in ("In Progress", "Innings Break", "Stumps", "Lunch", "Tea", "Drink")
    venue = info.get("venueInfo", {})
    badge = ("● LIVE" if live else state.upper())
    colour = "#8D2B28" if live else "#728078"
    with st.container(border=True):
        st.markdown(
            f"<div style='font-size:.72rem;letter-spacing:.08em;color:{colour};"
            f"font-weight:700'>{escape(badge)} · {escape(fmt)} · {escape(KIND_LABELS.get(row['kind'], row['kind']))}</div>"
            f"<div style='font-size:.8rem;color:#728078;margin:.1rem 0 .5rem'>"
            f"{escape(info.get('seriesName', ''))} · {escape(info.get('matchDesc', ''))}</div>"
            f"<div style='display:flex;justify-content:space-between;font-weight:700'>"
            f"<span>{escape(t1.get('teamName', '?'))}</span>"
            f"<span style='white-space:nowrap;margin-left:.6rem'>"
            f"{escape(innings_text(score.get('team1Score')))}</span></div>"
            f"<div style='display:flex;justify-content:space-between;font-weight:700'>"
            f"<span>{escape(t2.get('teamName', '?'))}</span>"
            f"<span style='white-space:nowrap;margin-left:.6rem'>"
            f"{escape(innings_text(score.get('team2Score')))}</span></div>"
            f"<div style='font-size:.85rem;color:#1F7A4A;margin-top:.45rem'>"
            f"{escape(info.get('status', ''))}</div>"
            f"<div style='font-size:.75rem;color:#728078;margin-top:.3rem'>"
            f"{escape(venue.get('ground', ''))}, {escape(venue.get('city', ''))}"
            + (f" · {escape(start_text(info))}" if show_time else "") + "</div>",
            unsafe_allow_html=True,
        )


def card_grid(rows: list[dict], empty: str, show_time: bool = False) -> None:
    if not rows:
        st.info(empty)
        return
    shown = rows[:MAX_CARDS]
    for i in range(0, len(shown), 3):
        cols = st.columns(3)
        for col, row in zip(cols, shown[i:i + 3]):
            with col:
                match_card(row, show_time)
    if len(rows) > MAX_CARDS:
        st.caption(f"Showing the first {MAX_CARDS} of {len(rows)} matches.")


def ago(seconds: float | None) -> str:
    if seconds is None:
        return "never"
    if seconds < 90:
        return f"{int(seconds)} s ago"
    return f"{int(seconds // 60)} min ago"


# --------------------------------------------------------------------------
# the scorecard
# --------------------------------------------------------------------------

def batting_table(inn: dict) -> pd.DataFrame:
    rows = []
    for b in inn.get("batsman", []):
        balls = b.get("balls", 0)
        out = b.get("outdec") or ("not out" if balls else "did not bat")
        rows.append({"Batter": b.get("name", "") + (" (c)" if b.get("iscaptain") else "")
                               + (" †" if b.get("iskeeper") else ""),
                     "How out": out, "R": b.get("runs", 0), "B": balls,
                     "4s": b.get("fours", 0), "6s": b.get("sixes", 0),
                     # Computed here: the API's strike-rate arrives as text.
                     "SR": strike_rate(b.get("runs"), balls)})
    return pd.DataFrame(rows)


def bowling_table(inn: dict) -> pd.DataFrame:
    rows = []
    for w in inn.get("bowler", []):
        balls = overs_to_balls(w.get("overs"))
        rows.append({"Bowler": w.get("name", ""), "O": w.get("overs", ""),
                     "M": w.get("maidens", 0), "R": w.get("runs", 0),
                     "W": w.get("wickets", 0),
                     # Computed from real balls: the API's economy and its
                     # 'balls' field are both wrong (see utils/transformers.py).
                     "Econ": economy(w.get("runs"), balls)})
    return pd.DataFrame(rows)


def show_scorecard(match_id: int) -> None:
    try:
        card = api_client.get_scorecard(match_id)
    except api_client.CricbuzzError as exc:
        st.error(f"Could not load the scorecard: {exc}")
        return
    innings = card.get("scorecard", [])
    if not innings:
        st.info("No scorecard yet — the match may not have started.")
        return
    if card.get("status"):
        st.markdown(f"**{card['status']}**")
    for inn in innings:
        head = (f"{inn.get('batteamname', '')} — {inn.get('score', 0)}/{inn.get('wickets', 0)}"
                f" ({overs_text(inn.get('overs'))} overs)")
        with st.expander(head, expanded=True):
            st.dataframe(batting_table(inn), hide_index=True, width="stretch",
                         column_config={"SR": st.column_config.NumberColumn(format="%.1f")})
            ex = inn.get("extras", {})
            st.caption(f"Extras {ex.get('total', 0)} (wides {ex.get('wides', 0)}, no-balls "
                       f"{ex.get('noballs', 0)}, byes {ex.get('byes', 0)}, leg-byes "
                       f"{ex.get('legbyes', 0)}, penalty {ex.get('penalty', 0)})")
            fow = inn.get("fow", {}).get("fow", [])
            if fow:
                st.caption("Fall of wickets: " + ", ".join(
                    f"{f.get('runs')}-{i} ({f.get('batsmanname', '')}, {f.get('overnbr')} ov)"
                    for i, f in enumerate(fow, start=1)))
            st.dataframe(bowling_table(inn), hide_index=True, width="stretch",
                         column_config={"Econ": st.column_config.NumberColumn(format="%.2f")})


# --------------------------------------------------------------------------
# page
# --------------------------------------------------------------------------

page_header("Live Matches",
            "What is being played now, what just finished and what is next — straight from "
            "the Cricbuzz API.", eyebrow="Live")

kinds = st.pills("Which cricket", MATCH_TYPES, selection_mode="multi",
                 format_func=KIND_LABELS.get,
                 default=["International", "Women"], key="lm_kinds",
                 help="The Cricbuzz API sorts matches into four blocks: men's internationals, "
                      "women's cricket (internationals and domestic), men's domestic, and "
                      "franchise leagues. The sidebar filters are for the historical archive "
                      "and do not apply on this page.")

kinds = set(kinds or [])
if not kinds:
    st.info("Pick at least one kind of cricket above.")
    st.stop()

quota = api_client.get_quota()
st.caption(
    f"Live scores refreshed {ago(api_client.cache_age('matches_live'))} · kept for "
    f"{api_client.TTL_LIVE // 60} min to save API calls"
    + (f" · {quota['remaining']} of {quota['limit']} API calls left this month" if quota else "")
)

errors = []


def fetch(getter, name: str) -> dict:
    try:
        return getter()
    except api_client.CricbuzzError as exc:
        errors.append(f"{name}: {exc}")
        return {}


live = walk(fetch(api_client.get_live_matches, "Live"), kinds)
recent = walk(fetch(api_client.get_recent_matches, "Recent"), kinds)
upcoming = walk(fetch(api_client.get_upcoming_matches, "Upcoming"), kinds)
if errors:
    st.warning("Some of the live feed is unavailable right now — " + "; ".join(errors))

now = datetime.now(timezone.utc)
upcoming = sorted([r for r in upcoming if (to_utc(r["info"].get("startDate")) or now) >= now]
                  or upcoming, key=lambda r: to_utc(r["info"].get("startDate")) or now)
in_play = [r for r in live if r["info"].get("state") not in ("Complete",)]

tab_live, tab_recent, tab_next = st.tabs([f"Live · {len(in_play)}",
                                          f"Recent · {len(recent)}",
                                          f"Upcoming · {len(upcoming)}"])
with tab_live:
    finished_today = [r for r in live if r["info"].get("state") == "Complete"]
    card_grid(in_play, "No match of this kind is in progress right now. Recent results "
                       "and the next fixtures are in the other two tabs.")
    if finished_today:
        section("Just finished")
        card_grid(finished_today, "")
with tab_recent:
    card_grid(recent, "No recent matches of this kind.")
with tab_next:
    card_grid(upcoming, "No upcoming matches of this kind.", show_time=True)

# --------------------------------------------------------------------------
# scorecard
# --------------------------------------------------------------------------

rule()
section("Full scorecard")
choices = {}
for row in live + recent:
    mid = row["info"].get("matchId")
    if mid and mid not in choices and row["info"].get("state") != "Preview":
        choices[mid] = label_of(row)
if not choices:
    st.info("No started or finished match to show a scorecard for.")
    st.stop()

st.caption("Loading a scorecard uses one API call (then it is kept for an hour), so it "
           "loads only when you press the button.")
pick = st.selectbox("Match", options=list(choices), format_func=choices.get, key="lm_match")
cached = api_client.cache_age(f"scorecard_{pick}")
fresh = cached is not None and cached < api_client.TTL_SCORECARD
if fresh or st.button("Load scorecard", key="lm_load", type="primary"):
    show_scorecard(int(pick))