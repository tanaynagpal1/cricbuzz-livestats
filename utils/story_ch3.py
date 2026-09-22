"""
The Story, chapter 3 — the grounds.

    3a  records              grounds and countries used, the highest-scoring
                             ground, the best ground to chase at
    3b  ground personality   every regular ground placed by its average
                             first-innings score and how often batting first wins
    3c  home advantage       how often the home side wins, by host country
    3d  the busiest grounds  most matches hosted, by format
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from utils.charts import INK, MUTED, SURFACE, base_layout, show
from utils.db_connection import DatabaseError, run_query
from utils.story import (EMPHASIS, FORMAT_COLOURS, MIN_MATCHES, Ctx,
                         panel_titles_left, scope, scope_params)
from utils.theme import rule, section, tiles

MIN_GROUND = 15        # full-length decided matches before a ground is placed
HOME_ABOVE = EMPHASIS  # home side wins more than half the time
HOME_BELOW = "#8D2B28" # home side wins less than half the time
TOP_GROUNDS = 12


def short(name: str, n: int = 24) -> str:
    """A ground name short enough to print on a chart."""
    name = name.split(",")[0]
    return name if len(name) <= n else name[:n - 1].rstrip() + "…"


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def ground_rows(where: str, params: dict, full_members: bool) -> pd.DataFrame:
    """Per ground and format: matches, average first-innings score, and how
    often the side batting first won. Full-length decided matches only, so
    every first-innings score is a real, unaltered target."""
    return run_query(f"""
        SELECT m.match_format                                           AS format,
               v.venue_id,
               v.venue_display                                          AS ground,
               v.city,
               v.country,
               count(*)                                                 AS matches,
               avg(i1.runs_total)                                       AS avg_first,
               100.0 * avg((m.winner_id = i1.batting_team_id)::int)     AS bat_first_won
        FROM fact_match   m
        JOIN dim_venue    v  ON v.venue_id  = m.venue_id
        JOIN fact_innings i1 ON i1.match_id = m.match_id AND i1.innings_no = 1
        JOIN fact_innings i2 ON i2.match_id = m.match_id AND i2.innings_no = 2
        WHERE m.victory_method IS NULL
          AND m.victory_type IN ('runs', 'wickets')
          AND i2.target_overs = m.scheduled_overs
          AND {scope(where, full_members)}
        GROUP BY 1, 2, 3, 4, 5
    """, scope_params(params))


@st.cache_data(ttl=3600, show_spinner=False)
def home_rows(where: str, params: dict, full_members: bool) -> pd.DataFrame:
    """Per host country and format: decided matches in which that country
    was one of the two sides, and how many the home side won.

    dim_venue.home_nation is the team that plays at home there ("West
    Indies" for grounds in the Caribbean); it is compared with
    dim_team.team_name, which has no "Women", so it covers both sexes.
    """
    return run_query(f"""
        SELECT v.home_nation                                            AS host,
               m.match_format                                           AS format,
               count(*)                                                 AS matches,
               sum((w.team_name = v.home_nation)::int)                  AS home_won
        FROM fact_match m
        JOIN dim_venue  v  ON v.venue_id  = m.venue_id
        JOIN dim_team   t1 ON t1.team_id  = m.team1_id
        JOIN dim_team   t2 ON t2.team_id  = m.team2_id
        JOIN dim_team   w  ON w.team_id   = m.winner_id
        WHERE m.victory_type IN ('runs', 'wickets')
          AND v.home_nation IN (t1.team_name, t2.team_name)
          AND {scope(where, full_members)}
        GROUP BY 1, 2
    """, scope_params(params))


@st.cache_data(ttl=3600, show_spinner=False)
def busy_rows(where: str, params: dict, full_members: bool) -> pd.DataFrame:
    """Matches hosted per ground and format (every match, any result)."""
    return run_query(f"""
        SELECT v.venue_display AS ground, v.city, v.country,
               m.match_format  AS format,
               count(*)        AS matches
        FROM fact_match m
        JOIN dim_venue  v ON v.venue_id = m.venue_id
        WHERE {scope(where, full_members)}
        GROUP BY 1, 2, 3, 4
    """, scope_params(params))


# --------------------------------------------------------------------------
# chapter
# --------------------------------------------------------------------------

def render(ctx: Ctx) -> None:
    try:
        grounds = ground_rows(ctx.where, ctx.params, ctx.full_members)
        homes = home_rows(ctx.where, ctx.params, ctx.full_members)
        busy = busy_rows(ctx.where, ctx.params, ctx.full_members)
    except DatabaseError as exc:
        st.error(str(exc))
        return
    if busy.empty:
        st.info("No matches fit the filters in the sidebar. Widen them.")
        return

    regular = grounds[grounds["matches"] >= MIN_GROUND].copy()
    formats = [f for f in ("ODI", "T20I") if f in set(busy["format"])]

    _records(ctx, busy, regular, formats)
    rule()
    _personality(ctx, regular, formats)
    rule()
    _home(ctx, homes, formats)
    rule()
    _busiest(ctx, busy, formats)


# --------------------------------------------------------------------------
# 3a. records
# --------------------------------------------------------------------------

def _records(ctx: Ctx, busy: pd.DataFrame, regular: pd.DataFrame, formats: list[str]) -> None:
    section("The grounds in this view")
    st.caption(f"Record grounds need at least {MIN_GROUND} full-length decided matches in "
               f"that format. {ctx.footer}")
    per_ground = busy.groupby(["ground", "country"])["matches"].sum().reset_index()
    cells = [("Grounds used", f"{len(per_ground):,}",
              f"in {per_ground['country'].nunique()} countries")]
    for fmt in formats:
        g = regular[regular["format"] == fmt]
        if g.empty:
            continue
        hi = g.loc[g["avg_first"].idxmax()]
        cells.append((f"Highest-scoring ground · {fmt}", f"{hi['avg_first']:.0f}",
                      f"average first innings · {hi['ground']}"))
        ch = g.loc[g["bat_first_won"].idxmin()]
        cells.append((f"Best ground to chase · {fmt}", f"{100 - ch['bat_first_won']:.0f}%",
                      f"of chases won · {ch['ground']}"))
    tiles(cells)


# --------------------------------------------------------------------------
# 3b. ground personality
# --------------------------------------------------------------------------

def _personality(ctx: Ctx, regular: pd.DataFrame, formats: list[str]) -> None:
    section("Ground personality — big-scoring or tight, bat first or chase")
    st.caption(f"One dot per ground with {MIN_GROUND}+ full-length decided matches. "
               "Across: the average first-innings score there. Up: how often the side "
               "batting first won. Bigger dot = more matches. Dotted lines: the middle "
               f"ground in this view and 50%. Hover a dot for the ground. {ctx.footer}")

    p_formats = [f for f in formats if f in set(regular["format"])]
    if not p_formats:
        st.info(f"No ground in this view has {MIN_GROUND} full-length decided matches. "
                "Widen the filters.")
        return

    fig = make_subplots(rows=1, cols=len(p_formats), shared_yaxes=True,
                        horizontal_spacing=0.07, subplot_titles=p_formats)
    for c, fmt in enumerate(p_formats, start=1):
        g = regular[regular["format"] == fmt]
        colour = FORMAT_COLOURS[fmt]
        fig.add_trace(go.Scatter(
            x=g["avg_first"], y=g["bat_first_won"], mode="markers", name=fmt,
            showlegend=False,
            marker=dict(size=8 + 14 * np.sqrt(g["matches"] / regular["matches"].max()),
                        color=colour, opacity=0.75, line=dict(color=SURFACE, width=1.5)),
            customdata=g[["ground", "country", "matches"]],
            hovertemplate=("<b>%{customdata[0]}</b>, %{customdata[1]}<br>"
                           "average first innings %{x:.0f} · batting first won %{y:.0f}%"
                           "<br>%{customdata[2]} matches<extra></extra>"),
        ), row=1, col=c)
        fig.add_vline(x=float(g["avg_first"].median()),
                      line=dict(color=MUTED, width=1, dash="dot"), row=1, col=c)
        fig.add_hline(y=50, line=dict(color=MUTED, width=1, dash="dot"), row=1, col=c)
        # Name only the two grounds the tiles above talk about; every other
        # ground is one hover away.
        middle = float(g["avg_first"].median())
        for idx in {g["avg_first"].idxmax(), g["bat_first_won"].idxmin()}:
            r = g.loc[idx]
            # Labels right of the middle hang to the left, so none runs off the edge.
            fig.add_annotation(x=r["avg_first"], y=r["bat_first_won"],
                               text=short(r["ground"]), showarrow=False, yshift=14,
                               xanchor="right" if r["avg_first"] > middle else "left",
                               font=dict(size=10, color=INK), row=1, col=c)
        pad = 0.08 * (g["avg_first"].max() - g["avg_first"].min() or 20)
        fig.update_xaxes(title_text="Average first-innings score",
                         range=[g["avg_first"].min() - pad, g["avg_first"].max() + pad],
                         row=1, col=c)
    base_layout(fig, height=460, legend=False)
    fig.update_layout(hovermode="closest")
    fig.update_yaxes(range=[0, 100], ticksuffix="%", dtick=25)
    fig.update_yaxes(title_text="Side batting first won", row=1, col=1)
    panel_titles_left(fig, p_formats)

    parts = []
    for fmt in p_formats:
        g = regular[regular["format"] == fmt]
        hi, lo = g.loc[g["avg_first"].idxmax()], g.loc[g["avg_first"].idxmin()]
        parts.append(f"{fmt}s — first innings average <strong>{hi['avg_first']:.0f}</strong> "
                     f"at {hi['ground']} but only <strong>{lo['avg_first']:.0f}</strong> at "
                     f"{lo['ground']} ({len(g)} grounds placed)")
    show(fig, takeaway="; ".join(parts) + ".", key="story_grounds",
         table=regular.sort_values(["format", "matches"], ascending=[True, False])
         [["format", "ground", "country", "matches", "avg_first", "bat_first_won"]]
         .round(1).rename(columns={"format": "Format", "ground": "Ground",
                                   "country": "Country", "matches": "Matches",
                                   "avg_first": "Avg 1st innings",
                                   "bat_first_won": "Batting first won %"}))


# --------------------------------------------------------------------------
# 3c. home advantage
# --------------------------------------------------------------------------

def _home(ctx: Ctx, homes: pd.DataFrame, formats: list[str]) -> None:
    section("Home advantage — how often the home side wins")
    st.caption("Decided matches where the host country was one of the two sides. Each "
               "bar starts at 50% (no advantage): green bars mean the home side wins more "
               "often than it loses, red bars mean it loses more often at home. Hosts with "
               f"fewer than {MIN_MATCHES} such matches are left out. {ctx.footer}")

    h = homes[homes["matches"] >= MIN_MATCHES].copy()
    if h.empty:
        st.info(f"No host in this view has {MIN_MATCHES} decided home matches. "
                "Widen the filters.")
        return
    h["pct"] = 100 * h["home_won"] / h["matches"]
    h_formats = [f for f in formats if f in set(h["format"])]

    # One panel per format, stacked, each as tall as its number of hosts.
    counts = [len(h[h["format"] == f]) for f in h_formats]
    fig = make_subplots(rows=len(h_formats), cols=1, vertical_spacing=0.06,
                        row_heights=counts, subplot_titles=h_formats)
    for c, fmt in enumerate(h_formats, start=1):
        g = h[h["format"] == fmt].sort_values("pct")
        fig.add_trace(go.Bar(
            y=g["host"], x=g["pct"] - 50, base=50, orientation="h", showlegend=False,
            marker=dict(color=[HOME_ABOVE if p >= 50 else HOME_BELOW for p in g["pct"]],
                        line=dict(color=SURFACE, width=1)),
            text=[f"{p:.0f}%" for p in g["pct"]], textposition="outside",
            textfont=dict(color=INK, size=11), cliponaxis=False,
            customdata=g[["matches", "home_won"]],
            hovertemplate=(f"{fmt} in %{{y}}: <b>home side won %{{text}}</b>"
                           "<br>%{customdata[1]} of %{customdata[0]} matches<extra></extra>"),
        ), row=c, col=1)
        fig.add_vline(x=50, line=dict(color=MUTED, width=1), row=c, col=1)
        fig.update_xaxes(range=[0, 100], ticksuffix="%", dtick=25, row=c, col=1)
        fig.update_yaxes(tickfont=dict(size=11, color=INK), showgrid=False, row=c, col=1)
    base_layout(fig, height=90 + 24 * sum(counts) + 40 * len(counts), legend=False)
    fig.update_layout(bargap=0.3)
    fig.update_annotations(font=dict(size=13, color=INK), xanchor="left", x=0)

    parts = []
    for fmt in h_formats:
        g = h[h["format"] == fmt]
        best, worst = g.loc[g["pct"].idxmax()], g.loc[g["pct"].idxmin()]
        overall = 100 * g["home_won"].sum() / g["matches"].sum()
        parts.append(f"{fmt}s — home sides win <strong>{overall:.0f}%</strong> overall; "
                     f"strongest at home: {best['host']} ({best['pct']:.0f}%), weakest: "
                     f"{worst['host']} ({worst['pct']:.0f}%)")
    show(fig, takeaway="; ".join(parts) + ".", key="story_home",
         table=h.sort_values(["format", "pct"], ascending=[True, False]).round(1)
         .rename(columns={"host": "Host", "format": "Format", "matches": "Matches",
                          "home_won": "Home side won", "pct": "Won %"}))


# --------------------------------------------------------------------------
# 3d. busiest grounds
# --------------------------------------------------------------------------

def _busiest(ctx: Ctx, busy: pd.DataFrame, formats: list[str]) -> None:
    section(f"The busiest grounds — top {TOP_GROUNDS} by matches hosted")
    st.caption(f"Every match in the view, any result, split by format. {ctx.footer}")

    totals = busy.groupby(["ground", "city", "country"])["matches"].sum().nlargest(TOP_GROUNDS)
    top = busy.merge(totals.reset_index()[["ground", "city", "country"]],
                     on=["ground", "city", "country"])
    order = list(totals.reset_index()["ground"])[::-1]   # biggest at the top

    fig = go.Figure()
    for fmt in formats:
        g = top[top["format"] == fmt].set_index("ground").reindex(order).fillna(0)
        fig.add_trace(go.Bar(
            y=order, x=g["matches"], name=fmt, orientation="h",
            marker=dict(color=FORMAT_COLOURS[fmt], line=dict(color=SURFACE, width=1)),
            hovertemplate="%{y}: <b>%{x:.0f} " + fmt + "s</b><extra></extra>",
        ))
    total_by = totals.reset_index().set_index("ground")["matches"]
    for ground in order:
        fig.add_annotation(x=float(total_by[ground]), y=ground, text=f"{int(total_by[ground])}",
                           showarrow=False, xanchor="left", xshift=6,
                           font=dict(color=INK, size=11))
    base_layout(fig, height=90 + 30 * len(order))
    fig.update_layout(barmode="stack", bargap=0.3, legend_traceorder="normal")
    fig.update_yaxes(showgrid=False, tickfont=dict(size=11, color=INK))
    fig.update_xaxes(title_text="Matches hosted")

    first = totals.reset_index().iloc[0]
    show(fig, key="story_busy",
         takeaway=(f"<strong>{first['ground']}</strong> ({first['country']}) has hosted "
                   f"the most matches in this view: <strong>{int(first['matches'])}</strong>."),
         table=totals.reset_index().rename(columns={"ground": "Ground", "city": "City",
                                                    "country": "Country",
                                                    "matches": "Matches"}))