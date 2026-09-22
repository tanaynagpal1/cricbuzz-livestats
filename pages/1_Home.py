"""
Home — what this is, what's in it, and where the numbers come from.

Every figure on this page is read from the database at load time rather than
typed into the file. A hardcoded "3,182 matches" is correct exactly once;
after the next load it is a claim nobody checks.

The ODI / T20I switch changes the words as well as the numbers: with no
format chosen the page talks about "total matches"; with one chosen it
talks about ODIs or T20Is only.
"""

from __future__ import annotations

import streamlit as st

from utils import coverage
from utils.db_connection import DatabaseError, run_query, warm_up
from utils.filters import active_filters, current_format, format_label, match_where, team_id
from utils.theme import card, rule, section, stadium_banner, tiles


# --------------------------------------------------------------------------
# wording that follows the ODI / T20I switch
# --------------------------------------------------------------------------

# format -> (banner / tile label, tile sub-line, phrase for the banner text)
FORMAT_WORDS = {
    None:   ("Total matches", "ODIs + T20Is", "every ODI and T20 international"),
    "ODI":  ("ODIs", "one-day internationals", "every one-day international"),
    "T20I": ("T20Is", "T20 internationals", "every T20 international"),
}


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

# One round trip instead of ten. Cached for an hour: these counts only change
# when the ETL runs, and the ETL does not run while the app is up.
@st.cache_data(ttl=3600, show_spinner=False)
def warehouse_stats(fmt: str | None) -> dict:
    """Banner numbers. Follows ONLY the format switch: the banner already
    splits men's and women's, so the gender switch must not change it.
    `fmt` is None (both formats), 'ODI' or 'T20I'."""
    df = run_query("""
        SELECT
            (SELECT count(*) FROM fact_match WHERE {f})          AS matches,
            (SELECT count(*) FROM fact_innings)                  AS innings,
            (SELECT count(*) FROM fact_batting)                  AS batting_rows,
            (SELECT count(*) FROM fact_bowling)                  AS bowling_rows,
            (SELECT count(*) FROM fact_partnership)              AS partnerships,
            (SELECT count(*) FROM dim_player)                    AS players,
            (SELECT count(*) FROM dim_venue)                     AS venues,
            (SELECT count(*) FROM dim_team)                      AS teams,
            (SELECT count(*) FROM dim_series)                    AS series,
            (SELECT count(*) FROM dim_date)                      AS dates,
            (SELECT min(match_date) FROM fact_match WHERE {f})   AS first_match,
            (SELECT max(match_date) FROM fact_match WHERE {f})   AS last_match,
            (SELECT count(*) FROM fact_match WHERE {f} AND gender='male')   AS mens,
            (SELECT count(*) FROM fact_match WHERE {f} AND gender='female') AS womens
    """.format(f="(CAST(:fmt AS text) IS NULL OR match_format = :fmt)"), {"fmt": fmt})
    return df.iloc[0].to_dict()


@st.cache_data(ttl=3600, show_spinner=False)
def filtered_stats(where: str, params: dict) -> dict:
    """The tile numbers for the matches the sidebar filters select.

    `where` comes from utils.filters.match_where(): a condition on
    fact_match (alias m). With no filters it is simply TRUE, so every
    match counts. The filtered matches become a small list, `picked`, and
    every other count is taken over the matches in that list.
    """
    df = run_query(f"""
        WITH picked AS (SELECT m.match_id, m.venue_id FROM fact_match m WHERE {where}),
        players AS (
            SELECT player_id FROM fact_batting WHERE match_id IN (SELECT match_id FROM picked)
            UNION
            SELECT player_id FROM fact_bowling WHERE match_id IN (SELECT match_id FROM picked)
        )
        SELECT
            (SELECT count(*) FROM picked)                                       AS matches,
            (SELECT count(*) FROM fact_batting
               WHERE match_id IN (SELECT match_id FROM picked))                 AS batting_rows,
            (SELECT count(*) FROM fact_bowling
               WHERE match_id IN (SELECT match_id FROM picked))                 AS bowling_rows,
            (SELECT count(*) FROM fact_partnership
               WHERE match_id IN (SELECT match_id FROM picked))                 AS partnerships,
            (SELECT count(*) FROM players)                                      AS players,
            (SELECT count(DISTINCT venue_id) FROM picked)                       AS venues,
            (SELECT count(DISTINCT v.country) FROM dim_venue v
               WHERE v.venue_id IN (SELECT venue_id FROM picked))               AS countries
    """, params)
    return df.iloc[0].to_dict()


@st.cache_data(ttl=3600, show_spinner=False)
def leaders(where: str, params: dict, bat_team: int | None) -> "object":
    """Top run scorers in the filtered matches.

    If a team is chosen, only that team's batters are counted — otherwise
    'India' would list Australian batters who happened to play India.
    The filters are arguments, not read inside, so the cache keeps one
    answer per combination of filters.
    """
    team_rule = "AND b.team_id = :bat_team" if bat_team is not None else ""
    return run_query(f"""
        SELECT p.player_name                       AS player,
               p.primary_team                      AS team,
               sum(b.runs_scored)                  AS runs,
               count(*)                            AS innings
        FROM fact_batting b
        JOIN dim_player   p ON p.player_id = b.player_id
        JOIN fact_match   m ON m.match_id  = b.match_id
        WHERE {where} {team_rule}
        GROUP BY p.player_id, p.player_name, p.primary_team
        ORDER BY runs DESC
        LIMIT 8
    """, {**params, "bat_team": bat_team})


# --------------------------------------------------------------------------
# page
# --------------------------------------------------------------------------

# Neon's free tier suspends compute after five minutes idle, so the first
# query after a pause takes several seconds. Without a spinner saying so, a
# reviewer assumes the app has hung.
with st.spinner("Waking the database…"):
    online = warm_up()

if not online:
    st.error(
        "Can't reach the database right now. If it has been idle it may still "
        "be waking up — refresh in a few seconds. Live match data on the other "
        "pages does not depend on it."
    )
    st.stop()

fmt = current_format()                        # None, 'ODI' or 'T20I'
count_label, count_sub, archive_phrase = FORMAT_WORDS[fmt]

try:
    stats = warehouse_stats(fmt)
except DatabaseError as exc:
    st.error(str(exc))
    st.stop()

# The animated stadium banner. Every number in it comes from the query above.
stadium_banner(
    title_html="REAL-TIME<br>CRICKET, <span>REAL</span><br>NUMBERS",
    subtitle=(
        f"Live scores from the Cricbuzz API, and {archive_phrase} "
        f"from {stats['first_match']:%Y} to {stats['last_match']:%Y}, "
        f"ball by ball, in a SQL database you can query."
    ),
    stats=[
        (count_label, f"{int(stats['matches']):,}"),
        ("Men's", f"{int(stats['mens']):,}"),
        ("Women's", f"{int(stats['womens']):,}"),
    ],
)

# The tiles and the table below follow the filters in the sidebar.
where, params = match_where("m")
scope = " · ".join(active_filters()) or "The whole archive"

try:
    g = filtered_stats(where, params)
except DatabaseError as exc:
    st.error(str(exc))
    st.stop()

st.caption(f"{scope} · change the filters in the sidebar")
tiles([
    (count_label, f"{int(g['matches']):,}", count_sub),
    ("Player innings", f"{int(g['batting_rows']):,}", "batting records"),
    ("Bowling spells", f"{int(g['bowling_rows']):,}", ""),
    ("Partnerships", f"{int(g['partnerships']):,}", ""),
    ("Players", f"{int(g['players']):,}", "batted or bowled"),
    ("Venues", f"{int(g['venues']):,}", f"in {int(g['countries'])} " + ("country" if int(g['countries']) == 1 else "countries")),
])

rule()

# --------------------------------------------------------------------------
left, right = st.columns([1.15, 1], gap="large")

with left:
    card("What this is", """
      <p>A cricket analytics dashboard built on two data paths that never
      touch each other.</p>
      <p>The <strong>cold path</strong> holds two decades of international
      cricket in PostgreSQL — every ball bowled, parsed into innings,
      partnerships and player records, and queried with SQL.</p>
      <p>The <strong>hot path</strong> reads live and upcoming matches
      straight from the Cricbuzz API and never stores them. Live scores
      change every ball; there is nothing to persist.</p>
      <p>The consequence is worth knowing: <strong>three of the five pages
      keep working when the API is down</strong> or its quota is spent.</p>
    """)

with right:
    card("The five pages", dark=True, body_html="""
      <div class="cb-nav-item"><span class="cb-nav-name">Home</span>
        <span class="cb-nav-desc">This page — what's here and where it came from</span></div>
      <div class="cb-nav-item"><span class="cb-nav-name">Live Matches</span>
        <span class="cb-nav-desc">In-play and upcoming fixtures, read live</span></div>
      <div class="cb-nav-item"><span class="cb-nav-name">Top Stats</span>
        <span class="cb-nav-desc">Leaderboards from the Cricbuzz API</span></div>
      <div class="cb-nav-item"><span class="cb-nav-name">SQL Analytics</span>
        <span class="cb-nav-desc">25 queries, each shown with its SQL</span></div>
      <div class="cb-nav-item"><span class="cb-nav-name">Manage Data</span>
        <span class="cb-nav-desc">Create, update and delete player records</span></div>
    """)

rule()

# --------------------------------------------------------------------------
section(f"Most {format_label()} runs")
st.caption(
    f"{scope}. Computed live from the warehouse — not a stored figure."
    + (" Only the chosen team's batters are counted." if team_id() else "")
)

try:
    st.dataframe(
        leaders(where, params, team_id()),
        width="stretch",
        hide_index=True,
        column_config={
            "player": st.column_config.TextColumn("Player"),
            "team": st.column_config.TextColumn("Team"),
            "runs": st.column_config.NumberColumn("Runs", format="%d"),
            "innings": st.column_config.NumberColumn("Innings", format="%d"),
        },
    )
except DatabaseError as exc:
    st.warning(str(exc))

rule()

# --------------------------------------------------------------------------
section("Where the data comes from")

src_cols = st.columns(3, gap="medium")
for col, key in zip(src_cols, ("historical", "live", "venue_capacity")):
    source = coverage.SOURCES[key]
    with col:
        card(key.replace("_", " ").title(), f"""
          <p><strong>{source['name']}</strong></p>
          <p>{source['what']}</p>
          <p style="font-size:0.84rem;color:var(--cb-muted)">
            {source['licence']}<br>retrieved {source['retrieved']}
          </p>
          <p><a href="{source['url']}" target="_blank">Source</a></p>
        """)

st.write("")

with st.expander("Coverage and known limitations", expanded=False):
    st.markdown(coverage.coverage_markdown())

st.caption(
    "Historical data from Cricsheet, used under its open-data terms. "
    "Live data from the Cricbuzz API via RapidAPI. "
    "This is a portfolio project and is not affiliated with either."
)