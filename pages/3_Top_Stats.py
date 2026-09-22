"""
Top Stats — all-time leaderboards straight from the Cricbuzz API's records endpoint.

    pick      a format (ODI, T20I, Test), batting or bowling, a statistic
              and optionally one calendar year
    see       the top three as tiles, a top-10 bar chart, and the full table
              (searchable and downloadable)

These are Cricbuzz's own international records, so they reach back before
our archive starts (2002) and include Tests, which our database does not
hold. The sidebar filters are for the archive and do not apply here.

The free API plan allows 200 calls a month, so:
  * the menu of statistics is written into this file (it never changes),
    so opening the page costs nothing;
  * each leaderboard is fetched only when you press the button, and is then
    saved on disk for a week - reopening it is free.
"""

from __future__ import annotations

import re
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils import api_client
from utils.charts import base_layout, show
from utils.story import EMPHASIS
from utils.theme import page_header, rule, section, tiles

FORMATS = {"ODI": 2, "T20I": 3, "Test": 1}          # the API's matchType codes

# The API's menu of statistics (from /stats/v1/topstats, saved in
# data/raw/samples/topstats.json). Written here so the page spends no call on it.
STAT_MENU = {
    "Batting": {
        "mostRuns": "Most runs", "highestScore": "Highest scores",
        "highestAvg": "Best batting average", "highestSr": "Best batting strike rate",
        "mostHundreds": "Most hundreds", "mostFifties": "Most fifties",
        "mostFours": "Most fours", "mostSixes": "Most sixes",
        "mostNineties": "Most nineties",
    },
    "Bowling": {
        "mostWickets": "Most wickets", "lowestAvg": "Best bowling average",
        "bestBowlingInnings": "Best bowling in an innings",
        "mostFiveWickets": "Most five-wicket hauls", "lowestEcon": "Best economy",
        "lowestSr": "Best bowling strike rate",
    },
}
# Leaderboards where smaller is better.
LOWER_IS_BETTER = {"lowestAvg", "lowestEcon", "lowestSr"}
# The column each leaderboard is ranked by, by its likely header names.
RANKED_BY = {
    "mostRuns": ["R", "Runs"], "highestScore": ["HS", "Score", "R", "Runs"],
    "highestAvg": ["Avg", "Ave"], "highestSr": ["SR"], "mostHundreds": ["100s", "100"],
    "mostFifties": ["50s", "50"], "mostFours": ["4s"], "mostSixes": ["6s"],
    "mostNineties": ["90s"], "mostWickets": ["W", "Wkts"], "lowestAvg": ["Avg", "Ave"],
    "mostFiveWickets": ["5W", "5-fers", "5wi"], "lowestEcon": ["Econ", "Eco", "ER"],
    "lowestSr": ["SR"],
}
# Best bowling is a figure like 8/19, not one number: table only.
TABLE_ONLY = {"bestBowlingInnings"}
FIRST_YEAR = 1971                                   # the first ODI
TOP_CHART = 10


def to_number(value) -> float | None:
    """'264*' -> 264, '53.78' -> 53.78, '8/19' or '-' -> None."""
    text = str(value).strip().rstrip("*").replace(",", "")
    return float(text) if re.fullmatch(r"-?\d+(\.\d+)?", text) else None


def parse_records(payload: dict) -> pd.DataFrame | None:
    """Turn the API's {headers, values} reply into a table.

    Each row arrives as {"values": [player_id, name, col1, col2, ...]}: one
    more item than there are headers, the first being Cricbuzz's player id.
    Returns None if the reply does not have that shape.
    """
    headers = payload.get("headers")
    rows = payload.get("values")
    if not headers or not isinstance(rows, list):
        return None
    headers = [str(h).strip() for h in headers]
    records = []
    for row in rows:
        items = row.get("values") if isinstance(row, dict) else row
        if not items:
            continue
        if len(items) == len(headers) + 1:           # drop the leading player id
            items = items[1:]
        if len(items) != len(headers):
            return None
        records.append(items)
    if not records:
        return pd.DataFrame(columns=headers)
    df = pd.DataFrame(records, columns=headers)
    for col in df.columns[1:]:                       # numbers where every cell is one
        numbers = df[col].map(to_number)
        if numbers.notna().all():
            df[col] = numbers.map(lambda v: int(v) if float(v).is_integer() else v)
    df.insert(0, "Rank", range(1, len(df) + 1))
    return df


def ranked_column(df: pd.DataFrame, stat: str) -> str | None:
    """The column the leaderboard is sorted by, or None for a table-only stat.

    First by name (RANKED_BY). If Cricbuzz uses a header we did not expect,
    fall back to the right-most numeric column whose values run in the
    leaderboard's direction ('264*' counts as 264).
    """
    if stat in TABLE_ONLY:
        return None
    by_name = {c.lower(): c for c in df.columns[2:]}
    for name in RANKED_BY.get(stat, []):
        if name.lower() in by_name:
            return by_name[name.lower()]
    lower_better = stat in LOWER_IS_BETTER
    for col in reversed(df.columns[2:]):
        values = df[col].map(to_number)
        if values.isna().any() or values.nunique() < 2:
            continue
        if values.is_monotonic_increasing if lower_better else values.is_monotonic_decreasing:
            return col
    return None


def ago(seconds: float | None) -> str:
    if seconds is None:
        return "never"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} days ago"


def calls_left() -> str:
    quota = api_client.get_quota()
    return f" · {quota['remaining']} of {quota['limit']} API calls left this month" if quota else ""


# --------------------------------------------------------------------------
# page
# --------------------------------------------------------------------------

page_header("Top Stats",
            "All-time international leaderboards, straight from Cricbuzz's own records.",
            eyebrow="Live")

left, right = st.columns(2)
with left:
    fmt = st.segmented_control("Format", list(FORMATS), default="ODI", key="ts_format") or "ODI"
with right:
    category = st.segmented_control("Discipline", list(STAT_MENU), default="Batting",
                                    key="ts_category") or "Batting"

left, right = st.columns([2, 1])
with left:
    menu = STAT_MENU[category]
    stat = st.selectbox("Statistic", list(menu), format_func=menu.get,
                        key=f"ts_stat_{category}")
with right:
    years = ["All time"] + list(range(date.today().year, FIRST_YEAR - 1, -1))
    year_pick = st.selectbox("Year", years, key="ts_year",
                             help="All time, or one calendar year. Each year is a separate "
                                  "leaderboard, so each one costs an API call the first time.")
year = None if year_pick == "All time" else int(year_pick)

st.caption("Cricbuzz's records for men's internationals, including matches before our archive "
           "begins in 2002. The sidebar filters do not apply on this page." + calls_left())

match_type = FORMATS[fmt]
cache_name = api_client.records_cache_name(stat, match_type, year)
age = api_client.cache_age(cache_name)
fresh = age is not None and age < api_client.TTL_RECORDS

rule()
section(f"{menu[stat]} · {fmt} · {year or 'all time'}")

if not fresh:
    st.info("This leaderboard is not saved yet. Loading it uses **one** API call; after that "
            "it is kept for a week and reopening it is free.")
    if not st.button("Load from Cricbuzz", key="ts_load", type="primary"):
        st.stop()

try:
    with st.spinner("Fetching from Cricbuzz…"):
        payload = api_client.get_records(stat, match_type=match_type, year=year)
except api_client.CricbuzzError as exc:
    st.warning(f"Cricbuzz did not answer: {exc}")
    st.stop()

df = parse_records(payload or {})
if df is None:
    st.warning("Cricbuzz replied, but not in the shape this page expects.")
    with st.expander("What came back (for debugging)"):
        st.json(payload)
    st.stop()
if df.empty:
    st.info(f"Cricbuzz has no records for this choice{f' in {year}' if year else ''}.")
    st.stop()

player_col = df.columns[1]
value_col = ranked_column(df, stat)

# ---- top three
tiles([(f"No. {r['Rank']}", str(r[player_col]),
        f"{value_col}: {r[value_col]}" if value_col else "")
       for _, r in df.head(3).iterrows()])

# ---- top-10 chart
if value_col:
    top = df.head(TOP_CHART).copy()
    top["value"] = top[value_col].map(to_number)
    top = top.iloc[::-1]                             # best at the top of the chart
    fig = go.Figure(go.Bar(
        x=top["value"], y=top[player_col], orientation="h",
        marker_color=EMPHASIS, text=top[value_col].astype(str),
        textposition="outside", cliponaxis=False,
        hovertemplate="%{y}: %{text}<extra></extra>"))
    base_layout(fig, height=40 * len(top) + 90)
    fig.update_layout(margin=dict(l=10, r=60, t=20, b=40), showlegend=False)
    fig.update_xaxes(title_text=value_col, rangemode="tozero")
    fig.update_yaxes(title_text=None)
    first = df.iloc[0]
    takeaway = f"<b>{first[player_col]}</b> leads with {first[value_col]}"
    if len(df) > 1:
        second = df.iloc[1]
        takeaway += f", ahead of {second[player_col]} on {second[value_col]}"
    show(fig, takeaway=takeaway + ".", key="ts_chart")
else:
    st.caption("Best bowling is a figure such as 8/19 rather than one number, so it is shown "
               "as a table only.")

# ---- full table
section("Full list")
search = st.text_input("Search the list", key="ts_search", placeholder="Type a player's name")
shown = df
if search:
    shown = df[df[player_col].astype(str).str.contains(search, case=False, regex=False)]
    st.caption(f"{len(shown)} of {len(df)} players match “{search}”.")
st.dataframe(shown, hide_index=True, width="stretch", height=min(560, 40 + 35 * len(shown)))
st.download_button("Download as CSV", data=df.to_csv(index=False).encode("utf-8"),
                   file_name=f"{stat}_{fmt}{'_' + str(year) if year else ''}.csv",
                   mime="text/csv", key="ts_download")

st.caption(f"Saved {ago(api_client.cache_age(cache_name))} · kept for a week, then the button "
           "fetches a fresh copy." + calls_left())