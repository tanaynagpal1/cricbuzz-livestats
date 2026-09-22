"""
The Story, chapter 4 — the batters.

    4a  records                  most runs and highest score, per format
    4b  anchors and aggressors   every regular batter placed by average and
                                 strike rate
    4c  the batting order        runs per innings and strike rate, positions 1-11
    4d  partnerships by wicket   how big the average stand is, wicket by wicket
    4e  how batters get out      caught, bowled, lbw ... as a share of dismissals

Everything follows the sidebar filters. When a team is chosen, only that
team's batters are counted (otherwise "India" would list the Australians
who happened to bat against them).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from utils.charts import INK, MUTED, SURFACE, base_layout, show
from utils.db_connection import DatabaseError, run_query
from utils.filters import team_id
from utils.story import FORMAT_COLOURS, Ctx, panel_titles_left, scope, scope_params
from utils.theme import rule, section, tiles

MIN_INNINGS = {"ODI": 40, "T20I": 30}   # innings before a batter is placed
TOP_BATTERS = 120                       # most-runs batters shown per format
MIN_POSITION_INNINGS = 50               # innings before a batting position is plotted

# Grouping of Cricsheet's dismissal kinds into the ones people talk about.
DISMISSAL_GROUPS = {
    "caught": "Caught", "caught and bowled": "Caught", "bowled": "Bowled",
    "lbw": "LBW", "run out": "Run out", "stumped": "Stumped",
}


def _team_rule(alias: str) -> tuple[str, dict]:
    """Only the chosen team's batters, when a team is chosen."""
    tid = team_id()
    return (f"AND {alias}.team_id = :bat_team", {"bat_team": tid}) if tid else ("", {})


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def batter_rows(where: str, params: dict, full_members: bool, team_sql: str) -> pd.DataFrame:
    """Per batter and format: innings, runs, balls, dismissals, best score."""
    return run_query(f"""
        SELECT m.match_format                          AS format,
               b.player_id,
               p.player_name                           AS player,
               p.primary_team                          AS team,
               count(*)                                AS innings,
               sum(b.runs_scored)                      AS runs,
               sum(b.balls_faced)                      AS balls,
               sum((NOT b.is_not_out)::int)            AS outs,
               max(b.runs_scored)                      AS best,
               sum((b.runs_scored >= 100)::int)        AS hundreds
        FROM fact_batting b
        JOIN fact_match   m ON m.match_id  = b.match_id
        JOIN dim_player   p ON p.player_id = b.player_id
        WHERE {scope(where, full_members)} {team_sql}
        GROUP BY 1, 2, 3, 4
    """, scope_params(params))


@st.cache_data(ttl=3600, show_spinner=False)
def best_innings(where: str, params: dict, full_members: bool, team_sql: str) -> pd.DataFrame:
    """The highest individual score per format, with who, against whom, when."""
    return run_query(f"""
        SELECT DISTINCT ON (m.match_format)
               m.match_format AS format, p.player_name AS player, b.runs_scored AS runs,
               b.balls_faced AS balls, b.is_not_out,
               opp.team_display AS opponent, EXTRACT(YEAR FROM m.match_date)::int AS year
        FROM fact_batting b
        JOIN fact_match   m   ON m.match_id  = b.match_id
        JOIN dim_player   p   ON p.player_id = b.player_id
        JOIN dim_team     opp ON opp.team_id = CASE WHEN b.team_id = m.team1_id
                                                    THEN m.team2_id ELSE m.team1_id END
        WHERE {scope(where, full_members)} {team_sql}
        ORDER BY m.match_format, b.runs_scored DESC, b.balls_faced
    """, scope_params(params))


@st.cache_data(ttl=3600, show_spinner=False)
def position_rows(where: str, params: dict, full_members: bool, team_sql: str) -> pd.DataFrame:
    return run_query(f"""
        SELECT m.match_format AS format, b.batting_position AS position,
               count(*) AS innings, sum(b.runs_scored) AS runs,
               sum(b.balls_faced) AS balls
        FROM fact_batting b
        JOIN fact_match   m ON m.match_id = b.match_id
        WHERE b.batting_position BETWEEN 1 AND 11
          AND {scope(where, full_members)} {team_sql}
        GROUP BY 1, 2
    """, scope_params(params))


@st.cache_data(ttl=3600, show_spinner=False)
def partnership_rows(where: str, params: dict, full_members: bool, team_sql: str) -> pd.DataFrame:
    """Average and best stand for wickets 1-10. (A handful of '11th wicket'
    rows exist where a retired batter came back; they are left out.)"""
    return run_query(f"""
        SELECT m.match_format AS format, pt.wicket_no AS wicket,
               count(*) AS stands, avg(pt.runs) AS avg_runs, max(pt.runs) AS best,
               sum((pt.runs >= 100)::int) AS hundred_stands
        FROM fact_partnership pt
        JOIN fact_match       m ON m.match_id = pt.match_id
        WHERE pt.wicket_no BETWEEN 1 AND 10
          AND {scope(where, full_members)} {team_sql.replace('b.team_id', 'pt.batting_team_id')}
        GROUP BY 1, 2
    """, scope_params(params))


@st.cache_data(ttl=3600, show_spinner=False)
def dismissal_rows(where: str, params: dict, full_members: bool, team_sql: str) -> pd.DataFrame:
    return run_query(f"""
        SELECT m.match_format AS format, b.dismissal_kind AS kind, count(*) AS outs
        FROM fact_batting b
        JOIN fact_match   m ON m.match_id = b.match_id
        WHERE NOT b.is_not_out AND b.dismissal_kind IS NOT NULL
          AND {scope(where, full_members)} {team_sql}
        GROUP BY 1, 2
    """, scope_params(params))


# --------------------------------------------------------------------------
# chapter
# --------------------------------------------------------------------------

def render(ctx: Ctx) -> None:
    team_sql, team_params = _team_rule("b")
    params = {**ctx.params, **team_params}
    args = (ctx.where, params, ctx.full_members, team_sql)
    try:
        batters = batter_rows(*args)
        best = best_innings(*args)
        positions = position_rows(*args)
        stands = partnership_rows(*args)
        outs = dismissal_rows(*args)
    except DatabaseError as exc:
        st.error(str(exc))
        return
    if batters.empty:
        st.info("No batting in the matches the sidebar filters select. Widen them.")
        return

    formats = [f for f in ("ODI", "T20I") if f in set(batters["format"])]
    team_note = " Only the chosen team's batters are counted." if team_sql else ""
    footer = ctx.footer + team_note

    _records(footer, batters, best, formats)
    rule()
    _anchors(footer, batters, formats)
    rule()
    _positions(footer, positions, formats)
    rule()
    _partnerships(footer, stands, formats)
    rule()
    _dismissals(footer, outs, formats)


# --------------------------------------------------------------------------
# 4a. records
# --------------------------------------------------------------------------

def _records(footer: str, batters: pd.DataFrame, best: pd.DataFrame, formats: list[str]) -> None:
    section("The records in this view")
    st.caption(footer)
    cells = []
    for fmt in formats:
        g = batters[batters["format"] == fmt]
        top = g.loc[g["runs"].idxmax()]
        cells.append((f"Most runs · {fmt}", f"{int(top['runs']):,}",
                      f"{top['player']} · {int(top['innings'])} innings"))
        b = best[best["format"] == fmt]
        if not b.empty:
            r = b.iloc[0]
            cells.append((f"Highest score · {fmt}",
                          f"{int(r['runs'])}{'*' if r['is_not_out'] else ''}",
                          f"{r['player']} v {r['opponent']}, {r['year']}"))
    tiles(cells)


# --------------------------------------------------------------------------
# 4b. anchors and aggressors
# --------------------------------------------------------------------------

def _anchors(footer: str, batters: pd.DataFrame, formats: list[str]) -> None:
    section("Anchors and aggressors — average against strike rate")
    st.caption(f"One dot per batter: the {TOP_BATTERS} highest run-scorers in each format "
               f"with at least {MIN_INNINGS['ODI']} ODI or {MIN_INNINGS['T20I']} T20I "
               "innings. Across: strike rate (runs per 100 balls). Up: average (runs per "
               "dismissal). Top right is the rare batter who scores both fast and "
               "reliably. Bigger dot = more runs. Named: the top run-scorer, the fastest "
               "and the steadiest; hover any dot for the rest. Dotted lines: the middle "
               f"batter in this view. {footer}")

    g_all = batters.copy()
    g_all["average"] = g_all["runs"] / g_all["outs"].replace(0, np.nan)
    g_all["strike_rate"] = 100 * g_all["runs"] / g_all["balls"].replace(0, np.nan)
    placed = []
    for fmt in formats:
        g = g_all[(g_all["format"] == fmt) & (g_all["innings"] >= MIN_INNINGS[fmt])]
        placed.append(g.dropna(subset=["average", "strike_rate"]).nlargest(TOP_BATTERS, "runs"))
    placed = pd.concat(placed) if placed else pd.DataFrame()
    a_formats = [f for f in formats if not placed.empty and f in set(placed["format"])]
    if not a_formats:
        st.info("No batter in this view has enough innings to be placed. Widen the filters.")
        return

    fig = make_subplots(rows=1, cols=len(a_formats), horizontal_spacing=0.08,
                        subplot_titles=a_formats)
    for c, fmt in enumerate(a_formats, start=1):
        g = placed[placed["format"] == fmt]
        fig.add_trace(go.Scatter(
            x=g["strike_rate"], y=g["average"], mode="markers", showlegend=False,
            marker=dict(size=7 + 14 * np.sqrt(g["runs"] / g["runs"].max()),
                        color=FORMAT_COLOURS[fmt], opacity=0.7,
                        line=dict(color=SURFACE, width=1.5)),
            customdata=g[["player", "team", "runs", "innings"]],
            hovertemplate=("<b>%{customdata[0]}</b> (%{customdata[1]})<br>average %{y:.1f}"
                           " · strike rate %{x:.1f}<br>%{customdata[2]:,} runs in "
                           "%{customdata[3]} innings<extra></extra>"),
        ), row=1, col=c)
        mid_x, mid_y = float(g["strike_rate"].median()), float(g["average"].median())
        fig.add_vline(x=mid_x, line=dict(color=MUTED, width=1, dash="dot"), row=1, col=c)
        fig.add_hline(y=mid_y, line=dict(color=MUTED, width=1, dash="dot"), row=1, col=c)
        # Name three batters only - the top run-scorer, the fastest and the
        # steadiest - so labels never pile up; every other dot is a hover away.
        named = {g["runs"].idxmax(), g["strike_rate"].idxmax(), g["average"].idxmax()}
        for idx in named:
            r = g.loc[idx]
            fig.add_annotation(x=r["strike_rate"], y=r["average"], text=r["player"],
                               showarrow=False, yshift=12,
                               xanchor="right" if r["strike_rate"] > mid_x else "left",
                               font=dict(size=10, color=INK), row=1, col=c)
        fig.update_xaxes(title_text="Strike rate", row=1, col=c)
        fig.update_yaxes(title_text="Average" if c == 1 else None, rangemode="tozero",
                         row=1, col=c)
    base_layout(fig, height=480, legend=False)
    fig.update_layout(hovermode="closest")
    panel_titles_left(fig, a_formats)

    parts = []
    for fmt in a_formats:
        g = placed[placed["format"] == fmt]
        # "Both": above the middle on average AND strike rate; the best of
        # them by average x strike rate (runs per 100 balls times reliability).
        both = g[(g["average"] > g["average"].median())
                 & (g["strike_rate"] > g["strike_rate"].median())]
        if both.empty:
            continue
        star = both.loc[(both["average"] * both["strike_rate"]).idxmax()]
        parts.append(f"{fmt}s — {len(both)} of {len(g)} batters are above the middle on "
                     f"both; the standout is <strong>{star['player']}</strong> (average "
                     f"{star['average']:.1f}, strike rate {star['strike_rate']:.1f})")
    show(fig, takeaway=("; ".join(parts) + ".") if parts else None, key="story_anchors",
         table=placed.sort_values(["format", "runs"], ascending=[True, False])
         [["format", "player", "team", "innings", "runs", "average", "strike_rate",
           "hundreds", "best"]].round(1)
         .rename(columns={"format": "Format", "player": "Player", "team": "Team",
                          "innings": "Innings", "runs": "Runs", "average": "Average",
                          "strike_rate": "Strike rate", "hundreds": "100s",
                          "best": "Best"}))


# --------------------------------------------------------------------------
# 4c. the batting order
# --------------------------------------------------------------------------

def _positions(footer: str, positions: pd.DataFrame, formats: list[str]) -> None:
    section("The batting order — what each position is worth")
    st.caption("Average runs per innings at each batting position (1 = opener). Hover "
               f"for the strike rate. Positions with fewer than {MIN_POSITION_INNINGS} "
               f"innings are left out. {footer}")

    p = positions[positions["innings"] >= MIN_POSITION_INNINGS].copy()
    if p.empty:
        st.info("Not enough innings in this view. Widen the filters.")
        return
    p["per_innings"] = p["runs"] / p["innings"]
    p["strike_rate"] = 100 * p["runs"] / p["balls"].replace(0, np.nan)

    fig = go.Figure()
    for fmt in formats:
        g = p[p["format"] == fmt].sort_values("position")
        if g.empty:
            continue
        fig.add_trace(go.Bar(
            x=g["position"], y=g["per_innings"], name=fmt,
            marker=dict(color=FORMAT_COLOURS[fmt], line=dict(color=SURFACE, width=1)),
            customdata=g[["strike_rate", "innings"]],
            hovertemplate=(fmt + " · number %{x}: <b>%{y:.1f} runs an innings</b><br>"
                           "strike rate %{customdata[0]:.1f} · %{customdata[1]:,} innings"
                           "<extra></extra>"),
        ))
    base_layout(fig, height=360, x_title="Batting position", y_title="Runs per innings")
    fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.06, hovermode="x unified")
    fig.update_xaxes(dtick=1)

    parts = []
    for fmt in formats:
        g = p[p["format"] == fmt]
        if g.empty:
            continue
        top = g.loc[g["per_innings"].idxmax()]
        fast = g.loc[g["strike_rate"].idxmax()]
        parts.append(f"{fmt}s — number <strong>{int(top['position'])}</strong> scores most "
                     f"({top['per_innings']:.1f} an innings); number {int(fast['position'])} "
                     f"scores fastest (strike rate {fast['strike_rate']:.0f})")
    show(fig, takeaway="; ".join(parts) + ".", key="story_positions",
         table=p.sort_values(["format", "position"])
         [["format", "position", "innings", "runs", "per_innings", "strike_rate"]].round(1)
         .rename(columns={"format": "Format", "position": "Position", "innings": "Innings",
                          "runs": "Runs", "per_innings": "Runs per innings",
                          "strike_rate": "Strike rate"}))


# --------------------------------------------------------------------------
# 4d. partnerships by wicket
# --------------------------------------------------------------------------

def _partnerships(footer: str, stands: pd.DataFrame, formats: list[str]) -> None:
    section("Partnerships — which wicket builds the biggest stands")
    st.caption("The average partnership for each wicket (1st wicket = the openers). "
               f"Hover for the record stand. {footer}")
    if stands.empty:
        st.info("No partnerships in this view. Widen the filters.")
        return

    fig = go.Figure()
    for fmt in formats:
        g = stands[stands["format"] == fmt].sort_values("wicket")
        if g.empty:
            continue
        fig.add_trace(go.Bar(
            x=g["wicket"], y=g["avg_runs"], name=fmt,
            marker=dict(color=FORMAT_COLOURS[fmt], line=dict(color=SURFACE, width=1)),
            customdata=g[["best", "stands", "hundred_stands"]],
            hovertemplate=(fmt + " · wicket %{x}: <b>average %{y:.1f}</b><br>record "
                           "%{customdata[0]} · %{customdata[2]} hundred stands in "
                           "%{customdata[1]:,}<extra></extra>"),
        ))
    base_layout(fig, height=360, x_title="Wicket", y_title="Average partnership (runs)")
    fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.06, hovermode="x unified")
    fig.update_xaxes(dtick=1)

    parts = []
    for fmt in formats:
        g = stands[stands["format"] == fmt]
        if g.empty:
            continue
        top = g.loc[g["avg_runs"].idxmax()]
        parts.append(f"{fmt}s — the <strong>{int(top['wicket'])}"
                     f"{ {1: 'st', 2: 'nd', 3: 'rd'}.get(int(top['wicket']), 'th') } wicket"
                     f"</strong> averages most ({top['avg_runs']:.1f})")
    show(fig, takeaway="; ".join(parts) + ".", key="story_stands",
         table=stands.sort_values(["format", "wicket"]).round(1)
         .rename(columns={"format": "Format", "wicket": "Wicket", "stands": "Stands",
                          "avg_runs": "Average", "best": "Record",
                          "hundred_stands": "100+ stands"}))


# --------------------------------------------------------------------------
# 4e. how batters get out
# --------------------------------------------------------------------------

def _dismissals(footer: str, outs: pd.DataFrame, formats: list[str]) -> None:
    section("How batters get out")
    st.caption("Share of all dismissals. 'Caught' includes caught-and-bowled; 'Other' is "
               f"hit wicket, retired out, obstructing the field and the like. {footer}")
    if outs.empty:
        st.info("No dismissals in this view. Widen the filters.")
        return

    d = outs.copy()
    d["how"] = d["kind"].map(DISMISSAL_GROUPS).fillna("Other")
    d = d.groupby(["format", "how"])["outs"].sum().reset_index()
    d["share"] = 100 * d["outs"] / d.groupby("format")["outs"].transform("sum")
    order = ["Caught", "Bowled", "LBW", "Run out", "Stumped", "Other"][::-1]

    fig = go.Figure()
    for fmt in formats:
        g = d[d["format"] == fmt].set_index("how").reindex(order).fillna(0)
        fig.add_trace(go.Bar(
            y=order, x=g["share"], name=fmt, orientation="h",
            marker=dict(color=FORMAT_COLOURS[fmt], line=dict(color=SURFACE, width=1)),
            text=[f"{v:.1f}%" if 0 < v < 1 else f"{v:.0f}%" for v in g["share"]],
            textposition="outside", textfont=dict(color=INK, size=11), cliponaxis=False,
            customdata=g[["outs"]],
            hovertemplate=(fmt + " · %{y}: <b>%{x:.1f}%</b> of dismissals<br>"
                           "%{customdata[0]:,} batters<extra></extra>"),
        ))
    base_layout(fig, height=380, x_title="Share of dismissals")
    fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.06,
                      legend_traceorder="normal")
    fig.update_xaxes(ticksuffix="%", range=[0, float(d["share"].max()) * 1.15])
    fig.update_yaxes(showgrid=False, tickfont=dict(size=12, color=INK))

    parts = []
    for fmt in formats:
        g = d[d["format"] == fmt].set_index("how")["share"]
        if g.empty:
            continue
        parts.append(f"{fmt}s — caught <strong>{g.get('Caught', 0):.0f}%</strong>, bowled "
                     f"{g.get('Bowled', 0):.0f}%, lbw {g.get('LBW', 0):.0f}%, run out "
                     f"{g.get('Run out', 0):.0f}%")
    show(fig, takeaway="; ".join(parts) + ".", key="story_outs",
         table=d.sort_values(["format", "share"], ascending=[True, False]).round(1)
         .rename(columns={"format": "Format", "how": "How out", "outs": "Dismissals",
                          "share": "Share %"}))