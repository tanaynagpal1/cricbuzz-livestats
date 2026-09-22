"""
The Story, chapter 1 — how scoring changed.

    1a  the boom                 matches per year, by format
    1b  the run-rate river       median run rate per year, with the middle half
    1c  the six explosion        sixes per match per year
    1d  where the runs come from share of runs by phase, per year
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from utils.charts import SURFACE, base_layout, show
from utils.db_connection import DatabaseError, run_query
from utils.story import (FORMAT_COLOURS, MIN_MATCHES, Ctx, end_labels, first_last,
                         legend_below, panel_titles_left, scope, scope_params, year_axis)
from utils.theme import rule, section

# Phases are ordered (start -> middle -> end), so they get one hue, light to
# dark, rather than three unrelated colours.
PHASE_COLOURS = {"Powerplay": "#A9D3B5", "Middle overs": "#5FA37A", "Death overs": "#1F5C3A"}


@st.cache_data(ttl=3600, show_spinner=False)
def matches_per_year(where: str, params: dict, full_members: bool) -> pd.DataFrame:
    return run_query(f"""
        SELECT m.match_format AS format,
               EXTRACT(YEAR FROM m.match_date)::int AS year,
               count(*) AS matches
        FROM fact_match m
        WHERE {scope(where, full_members)}
        GROUP BY 1, 2
        ORDER BY 1, 2
    """, scope_params(params))


@st.cache_data(ttl=3600, show_spinner=False)
def scoring_by_year(where: str, params: dict, full_members: bool) -> pd.DataFrame:
    """One row per format per year: run-rate spread, sixes, phase shares.

    Only innings of at least 5 overs (30 legal balls) count, so a
    rain-ruined innings of 2 overs cannot drag a year around.
    """
    return run_query(f"""
        SELECT m.match_format                                     AS format,
               EXTRACT(YEAR FROM m.match_date)::int               AS year,
               count(DISTINCT m.match_id)                         AS matches,
               count(*)                                           AS innings,
               percentile_cont(0.25) WITHIN GROUP
                   (ORDER BY 6.0 * i.runs_total / i.legal_balls)  AS rr_q1,
               percentile_cont(0.50) WITHIN GROUP
                   (ORDER BY 6.0 * i.runs_total / i.legal_balls)  AS rr_median,
               percentile_cont(0.75) WITHIN GROUP
                   (ORDER BY 6.0 * i.runs_total / i.legal_balls)  AS rr_q3,
               sum(i.sixes)                                       AS sixes,
               sum(i.pp_runs)                                     AS pp_runs,
               sum(i.middle_runs)                                 AS middle_runs,
               sum(i.death_runs)                                  AS death_runs
        FROM fact_innings i
        JOIN fact_match   m ON m.match_id = i.match_id
        WHERE i.legal_balls >= 30 AND {scope(where, full_members)}
        GROUP BY 1, 2
        ORDER BY 1, 2
    """, scope_params(params))


def render(ctx: Ctx) -> None:
    try:
        per_year = matches_per_year(ctx.where, ctx.params, ctx.full_members)
        scoring = scoring_by_year(ctx.where, ctx.params, ctx.full_members)
    except DatabaseError as exc:
        st.error(str(exc))
        return

    # Keep only years with enough matches to mean something.
    plotted = scoring[scoring["matches"] >= MIN_MATCHES].copy()
    if plotted.empty:
        st.info(f"No year in this view has {MIN_MATCHES} or more matches. "
                "Widen the filters in the sidebar.")
        return
    plotted["six_per_match"] = plotted["sixes"] / plotted["matches"]
    phase_total = plotted["pp_runs"] + plotted["middle_runs"] + plotted["death_runs"]
    for part in ("pp", "middle", "death"):
        plotted[f"{part}_share"] = 100 * plotted[f"{part}_runs"] / phase_total
    formats = [f for f in ("ODI", "T20I") if f in set(plotted["format"])]

    dropped = int((scoring["matches"] < MIN_MATCHES).sum())
    dropped_note = (f" Years with fewer than {MIN_MATCHES} matches are left out "
                    f"({dropped} in this view)." if dropped else "")

    # ----------------------------------------------------------------------
    # 1a. the boom — matches per year
    # ----------------------------------------------------------------------
    section("The boom — international matches per year")
    st.caption(f"Every match in the archive, by year and format. The last year is the "
               f"year so far. {ctx.footer}")

    fig = go.Figure()
    for fmt in formats:
        g = per_year[per_year["format"] == fmt]
        fig.add_trace(go.Bar(
            x=g["year"], y=g["matches"], name=fmt,
            marker=dict(color=FORMAT_COLOURS[fmt], line=dict(color=SURFACE, width=1)),
            hovertemplate="%{x}: <b>%{y} " + fmt + "s</b><extra></extra>",
        ))
    base_layout(fig, height=340, y_title="Matches")
    fig.update_layout(barmode="group", bargap=0.2, bargroupgap=0.05, hovermode="x unified")
    fig.update_xaxes(dtick=2)

    t20 = per_year[per_year["format"] == "T20I"].set_index("year")["matches"]
    if 2018 in t20.index and 2019 in t20.index and not ctx.full_members:
        takeaway = (f"T20Is jumped from <strong>{t20[2018]}</strong> in 2018 to "
                    f"<strong>{t20[2019]}</strong> in 2019, the year every ICC member "
                    f"was given official T20I status"
                    + (f", and reached <strong>{t20.max()}</strong> in {t20.idxmax()}."
                       if t20.max() > t20[2019] else "."))
    else:
        top = per_year.loc[per_year["matches"].idxmax()]
        takeaway = (f"Busiest year in this view: <strong>{int(top['year'])}</strong>, "
                    f"with {int(top['matches'])} {top['format']}s.")
    show(fig, takeaway=takeaway, key="story_boom",
         table=per_year.pivot_table(index="year", columns="format", values="matches",
                                    fill_value=0).reset_index().rename(columns={"year": "Year"}))

    # ----------------------------------------------------------------------
    # 1b. the run-rate river
    # ----------------------------------------------------------------------
    rule()
    section("The run-rate river — how fast teams score")
    st.caption("Line: the median innings run rate that year. Band: the middle half of all "
               "innings (25th to 75th percentile) — a wide band means very different "
               f"scoring from match to match. Innings of 5+ overs only. {ctx.footer}"
               + dropped_note)

    fig = go.Figure()
    ends = []
    for fmt in formats:
        g = plotted[plotted["format"] == fmt].sort_values("year")
        colour = FORMAT_COLOURS[fmt]
        r, gg, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
        # The band: upper edge, then lower edge filled up to it.
        fig.add_trace(go.Scatter(x=g["year"], y=g["rr_q3"], mode="lines",
                                 line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=g["year"], y=g["rr_q1"], mode="lines",
                                 line=dict(width=0), fill="tonexty",
                                 fillcolor=f"rgba({r},{gg},{b},0.16)",
                                 showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(
            x=g["year"], y=g["rr_median"], mode="lines+markers", name=fmt,
            line=dict(color=colour, width=2.5),
            marker=dict(size=8, color=colour, line=dict(color=SURFACE, width=2)),
            customdata=g[["rr_q1", "rr_q3", "innings"]],
            hovertemplate=(fmt + " %{x}: median <b>%{y:.2f}</b> an over<br>"
                           "middle half %{customdata[0]:.2f}–%{customdata[1]:.2f} · "
                           "%{customdata[2]} innings<extra></extra>"),
        ))
        last = g.iloc[-1]
        ends.append((last["year"], last["rr_median"], f"{fmt} {last['rr_median']:.2f}"))
    end_labels(fig, ends)
    base_layout(fig, height=400, y_title="Runs per over")
    # Filled bands make Plotly reverse the legend; keep it ODI first.
    fig.update_layout(hovermode="closest", legend_traceorder="normal")
    year_axis(fig, plotted["year"])

    parts = []
    for fmt in formats:
        a, b, sa, sb = first_last(plotted[plotted["format"] == fmt], "rr_median")
        parts.append(f"{fmt}s went from <strong>{a:.2f}</strong> an over ({sa}) to "
                     f"<strong>{b:.2f}</strong> ({sb}), "
                     f"{'+' if b >= a else ''}{100 * (b - a) / a:.0f}%")
    takeaway = "Median run rate: " + "; ".join(parts) + "."
    if "T20I" in formats and not ctx.full_members:
        takeaway += (" If the T20I line looks flat, switch to <em>Full members only</em>: "
                     "the post-2019 matches between smaller sides pull the average down.")
    show(fig, takeaway=takeaway, key="story_river",
         table=plotted[["format", "year", "matches", "innings", "rr_q1", "rr_median", "rr_q3"]]
         .round(2).rename(columns={"format": "Format", "year": "Year", "matches": "Matches",
                                   "innings": "Innings", "rr_q1": "25th pct",
                                   "rr_median": "Median", "rr_q3": "75th pct"}))

    # ----------------------------------------------------------------------
    # 1c. the six explosion
    # ----------------------------------------------------------------------
    rule()
    section("The six explosion — sixes per match")
    st.caption("All sixes hit in the year, both teams together, divided by the number of "
               f"matches. {ctx.footer}" + dropped_note)

    fig = go.Figure()
    ends = []
    for fmt in formats:
        g = plotted[plotted["format"] == fmt].sort_values("year")
        colour = FORMAT_COLOURS[fmt]
        fig.add_trace(go.Scatter(
            x=g["year"], y=g["six_per_match"], mode="lines+markers", name=fmt,
            line=dict(color=colour, width=2.5),
            marker=dict(size=8, color=colour, line=dict(color=SURFACE, width=2)),
            customdata=g[["sixes", "matches"]],
            hovertemplate=(fmt + " %{x}: <b>%{y:.1f}</b> sixes a match<br>"
                           "%{customdata[0]:,} sixes in %{customdata[1]} matches<extra></extra>"),
        ))
        last = g.iloc[-1]
        ends.append((last["year"], last["six_per_match"], f"{fmt} {last['six_per_match']:.1f}"))
    end_labels(fig, ends)
    base_layout(fig, height=380, y_title="Sixes per match")
    fig.update_layout(hovermode="closest")
    fig.update_yaxes(rangemode="tozero")
    year_axis(fig, plotted["year"])

    parts = []
    for fmt in formats:
        a, b, sa, sb = first_last(plotted[plotted["format"] == fmt], "six_per_match")
        parts.append(f"{fmt}s: <strong>{a:.1f}</strong> a match ({sa}) → "
                     f"<strong>{b:.1f}</strong> ({sb})"
                     + (f", {b / a:.1f}× as many" if a and b / a >= 1.2 else ""))
    show(fig, takeaway="Sixes per match — " + "; ".join(parts) + ".", key="story_sixes",
         table=plotted[["format", "year", "matches", "sixes", "six_per_match"]]
         .round(2).rename(columns={"format": "Format", "year": "Year", "matches": "Matches",
                                   "sixes": "Sixes", "six_per_match": "Sixes per match"}))

    # ----------------------------------------------------------------------
    # 1d. where the runs come from — phase share
    # ----------------------------------------------------------------------
    rule()
    section("Where the runs come from — share of runs by phase")
    st.caption("Each column is one year and adds up to 100%. ODI: powerplay = first 10 "
               "overs, death = last 10. T20I: powerplay = first 6 overs, death = last 5. "
               "One panel per format, because the phases are different lengths. "
               f"{ctx.footer}" + dropped_note)

    fig = make_subplots(rows=1, cols=len(formats), shared_yaxes=True,
                        horizontal_spacing=0.06, subplot_titles=formats)
    for c, fmt in enumerate(formats, start=1):
        g = plotted[plotted["format"] == fmt].sort_values("year")
        for label, col in (("Powerplay", "pp_share"), ("Middle overs", "middle_share"),
                           ("Death overs", "death_share")):
            fig.add_trace(go.Bar(
                x=g["year"], y=g[col], name=label, legendgroup=label, showlegend=(c == 1),
                marker=dict(color=PHASE_COLOURS[label], line=dict(color=SURFACE, width=1)),
                hovertemplate=(fmt + " %{x} · " + label + ": <b>%{y:.1f}%</b><extra></extra>"),
            ), row=1, col=c)
    base_layout(fig, height=420)
    legend_below(fig)
    fig.update_layout(barmode="stack", bargap=0.15)
    fig.update_yaxes(range=[0, 100], ticksuffix="%")
    fig.update_yaxes(title_text="Share of runs", row=1, col=1)
    fig.update_xaxes(dtick=4)
    panel_titles_left(fig, formats)

    parts = []
    for fmt in formats:
        g = plotted[plotted["format"] == fmt]
        a, b, sa, sb = first_last(g, "pp_share")
        d_a, d_b, _, _ = first_last(g, "death_share")
        parts.append(f"{fmt}s — powerplay <strong>{a:.0f}% → {b:.0f}%</strong>, "
                     f"death overs {d_a:.0f}% → {d_b:.0f}% ({sa} vs {sb})")
    show(fig, takeaway="Share of runs: " + "; ".join(parts) + ".", key="story_phase",
         table=plotted[["format", "year", "pp_share", "middle_share", "death_share"]]
         .round(1).rename(columns={"format": "Format", "year": "Year",
                                   "pp_share": "Powerplay %", "middle_share": "Middle %",
                                   "death_share": "Death %"}))