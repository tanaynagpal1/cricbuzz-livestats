"""
The Story, chapter 2 — the chase.

    2a  records              highest chase, lowest total defended
    2b  the safe score       how often each first-innings total is enough
    2c  halfway pressure     chance of winning a chase from the halfway mark,
                             by the rate needed and wickets already lost
    2d  chase or defend      what wins each year, and what captains choose
    2e  does the toss matter how often the toss winner wins, by their choice

Only "full-length" matches are used where a target matters: no rain rule,
and the chase was over the full distance, so the target really was the
first-innings score + 1.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from utils.charts import INK, MUTED, SURFACE, base_layout, show
from utils.db_connection import DatabaseError, run_query
from utils.story import (CONTEXT_GREY, EMPHASIS, MIN_MATCHES, Ctx, legend_below,
                         panel_titles_left, scope, scope_params)
from utils.theme import rule, section, tiles

# The safe-score chart compares two eras, split here. 2015 sits after the
# 2012 ODI rule changes (two new balls, fewer fielders out) had bedded in.
ERA_SPLIT = 2015
ERA_COLOURS = {f"Before {ERA_SPLIT}": CONTEXT_GREY, f"{ERA_SPLIT} onward": EMPHASIS}
BAND = {"ODI": 20, "T20I": 10}     # first-innings scores grouped into bands this wide
MIN_BAND = 10                      # matches needed before a band / point is plotted

# Halfway in each format, in overs (the chase is judged at the end of it).
HALFWAY = {"ODI": 25, "T20I": 10}
# Wickets already lost at halfway: ordered, so one hue from light to dark.
WICKET_GROUPS = {"0–2 down": "#1F7A4A", "3–4 down": "#5FA37A", "5+ down": "#A9C9B3"}


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def chase_rows(where: str, params: dict, full_members: bool) -> pd.DataFrame:
    """One row per match that has a second innings."""
    return run_query(f"""
        SELECT m.match_id,
               m.match_format                             AS format,
               EXTRACT(YEAR FROM m.match_date)::int       AS year,
               t1.team_display                            AS bat_first,
               t2.team_display                            AS bat_second,
               i1.runs_total                              AS first_score,
               i2.runs_total                              AS second_score,
               i2.wickets_lost                            AS second_wickets,
               m.toss_decision,
               m.victory_type IN ('runs', 'wickets')      AS decided,
               m.winner_id = i2.batting_team_id           AS chase_won,
               m.winner_id = i1.batting_team_id           AS defend_won,
               m.winner_id = m.toss_winner_id             AS toss_winner_won,
               (m.victory_method IS NULL
                AND i2.target_overs = m.scheduled_overs)  AS full_length
        FROM fact_match   m
        JOIN fact_innings i1 ON i1.match_id = m.match_id AND i1.innings_no = 1
        JOIN fact_innings i2 ON i2.match_id = m.match_id AND i2.innings_no = 2
        JOIN dim_team     t1 ON t1.team_id  = i1.batting_team_id
        JOIN dim_team     t2 ON t2.team_id  = i2.batting_team_id
        WHERE {scope(where, full_members)}
    """, scope_params(params))


@st.cache_data(ttl=3600, show_spinner=False)
def halfway_rows(where: str, params: dict, full_members: bool) -> pd.DataFrame:
    """Every full-length chase still going at halfway: the runs still needed,
    the wickets already down, and whether it was won.

    fact_over holds the running score at the end of every over, so the
    halfway state is simply the row for over 25 (ODI) or over 10 (T20I).
    Chases already finished before halfway have no such row and drop out.
    """
    return run_query(f"""
        SELECT m.match_format                              AS format,
               i1.runs_total + 1 - o.cum_runs              AS runs_needed,
               o.cum_wickets                               AS wickets_down,
               m.winner_id = i2.batting_team_id            AS chase_won
        FROM fact_match   m
        JOIN fact_innings i1 ON i1.match_id = m.match_id AND i1.innings_no = 1
        JOIN fact_innings i2 ON i2.match_id = m.match_id AND i2.innings_no = 2
        JOIN fact_over    o  ON o.match_id  = m.match_id AND o.innings_no = 2
                            AND o.over_no = CASE m.match_format WHEN 'ODI' THEN 25 ELSE 10 END
        WHERE m.victory_method IS NULL
          AND m.victory_type IN ('runs', 'wickets')
          AND i2.target_overs = m.scheduled_overs
          AND {scope(where, full_members)}
    """, scope_params(params))


# --------------------------------------------------------------------------
# chapter
# --------------------------------------------------------------------------

def render(ctx: Ctx) -> None:
    try:
        chases = chase_rows(ctx.where, ctx.params, ctx.full_members)
        halfway = halfway_rows(ctx.where, ctx.params, ctx.full_members)
    except DatabaseError as exc:
        st.error(str(exc))
        return

    decided = chases[chases["decided"].astype(bool)].copy()
    if decided.empty:
        st.info("No decided matches fit the filters in the sidebar. Widen them.")
        return
    formats = [f for f in ("ODI", "T20I") if f in set(decided["format"])]
    clean = decided[decided["full_length"].astype(bool)].copy()

    _records(ctx, clean, formats)
    rule()
    _safe_score(ctx, clean, formats)
    rule()
    _halfway(ctx, halfway, formats)
    rule()
    _chase_or_defend(ctx, decided, formats)
    rule()
    _toss(ctx, decided, formats)


# --------------------------------------------------------------------------
# 2a. records
# --------------------------------------------------------------------------

def _records(ctx: Ctx, clean: pd.DataFrame, formats: list[str]) -> None:
    section("The records in this view")
    st.caption("Rain-affected matches are left out of these, because their targets "
               f"were changed. {ctx.footer}")
    cells = []
    for fmt in formats:
        g = clean[clean["format"] == fmt]
        won = g[g["chase_won"].astype(bool)]
        held = g[g["defend_won"].astype(bool)]
        if not won.empty:
            r = won.loc[won["second_score"].idxmax()]
            cells.append((f"Highest chase · {fmt}",
                          f"{int(r['second_score'])}/{int(r['second_wickets'])}",
                          f"{r['bat_second']} v {r['bat_first']}, {r['year']}"))
        if not held.empty:
            r = held.loc[held["first_score"].idxmin()]
            cells.append((f"Lowest total defended · {fmt}", f"{int(r['first_score'])}",
                          f"{r['bat_first']} v {r['bat_second']}, {r['year']}"))
    if cells:
        tiles(cells)


# --------------------------------------------------------------------------
# 2b. the safe score
# --------------------------------------------------------------------------

def _thresholds(g: pd.DataFrame) -> tuple[int | None, int | None]:
    """Par: the lowest band won at least half the time. Safe: the lowest
    band from which EVERY higher band is won at least 3 times in 4."""
    g = g.sort_values("band")
    par = g.loc[g["win_pct"] >= 50, "band"]
    safe_from = None
    for band in g["band"]:
        if (g.loc[g["band"] >= band, "win_pct"] >= 75).all():
            safe_from = int(band)
            break
    return (int(par.iloc[0]) if not par.empty else None), safe_from


def _safe_score(ctx: Ctx, clean: pd.DataFrame, formats: list[str]) -> None:
    section("The safe score — how often a first-innings total is enough")
    st.caption(f"Each point: every full-length match where the side batting first made a "
               f"score in that band ({BAND['ODI']}-run bands for ODIs, {BAND['T20I']} for "
               f"T20Is), and the share of them the side batting first went on to win. "
               f"Grey: before {ERA_SPLIT}. Green: {ERA_SPLIT} onward. Dotted lines: 50% and "
               f"75%. Bands with fewer than {MIN_BAND} matches are left out. {ctx.footer}")

    safe = clean.copy()
    safe["era"] = [f"{ERA_SPLIT} onward" if y >= ERA_SPLIT else f"Before {ERA_SPLIT}"
                   for y in safe["year"]]
    safe["band"] = [int(sc // BAND[f] * BAND[f]) for sc, f in zip(safe["first_score"], safe["format"])]
    curve = (safe.groupby(["format", "era", "band"])
             .agg(matches=("match_id", "size"), won=("defend_won", "sum"))
             .reset_index())
    curve = curve[curve["matches"] >= MIN_BAND].copy()
    if curve.empty:
        st.info(f"Not enough matches in this view for any score band to have "
                f"{MIN_BAND} matches. Widen the filters.")
        return
    curve["win_pct"] = 100 * curve["won"] / curve["matches"]
    curve["band_to"] = curve["band"] + curve["format"].map(BAND) - 1

    s_formats = [f for f in formats if f in set(curve["format"])]
    fig = make_subplots(rows=1, cols=len(s_formats), shared_yaxes=True,
                        horizontal_spacing=0.07, subplot_titles=s_formats)
    for c, fmt in enumerate(s_formats, start=1):
        for era, colour in ERA_COLOURS.items():
            g = curve[(curve["format"] == fmt) & (curve["era"] == era)].sort_values("band")
            if g.empty:
                continue
            fig.add_trace(go.Scatter(
                x=g["band"] + BAND[fmt] / 2, y=g["win_pct"], mode="lines+markers",
                name=era, legendgroup=era, showlegend=(c == 1),
                line=dict(color=colour, width=2.5),
                marker=dict(size=8, color=colour, line=dict(color=SURFACE, width=2)),
                customdata=g[["band", "band_to", "matches", "won"]],
                hovertemplate=(f"{fmt}, {era}<br>batting first, "
                               "%{customdata[0]}–%{customdata[1]}: <b>won %{y:.0f}%</b>"
                               "<br>%{customdata[3]} of %{customdata[2]} matches<extra></extra>"),
            ), row=1, col=c)
        for ref in (50, 75):
            fig.add_hline(y=ref, line=dict(color=MUTED, width=1, dash="dot"), row=1, col=c)
        fig.update_xaxes(title_text="First-innings score", row=1, col=c)
    base_layout(fig, height=420)
    legend_below(fig, y=-0.16)
    fig.update_layout(hovermode="closest")
    fig.update_yaxes(range=[0, 102], ticksuffix="%", dtick=25)
    fig.update_yaxes(title_text="Side batting first won", row=1, col=1)
    panel_titles_left(fig, s_formats)

    parts = []
    for fmt in s_formats:
        recent = curve[(curve["format"] == fmt) & (curve["era"] == f"{ERA_SPLIT} onward")]
        early = curve[(curve["format"] == fmt) & (curve["era"] == f"Before {ERA_SPLIT}")]
        p_new, s_new = _thresholds(recent) if not recent.empty else (None, None)
        p_old, s_old = _thresholds(early) if not early.empty else (None, None)
        bits = []
        if p_new is not None:
            bits.append(f"a total of <strong>{p_new}+</strong> wins more often than not"
                        + (f" (it was {p_old}+ before {ERA_SPLIT})"
                           if p_old is not None and p_old != p_new else ""))
        if s_new is not None:
            bits.append(f"<strong>{s_new}+</strong> wins at least 3 times in 4"
                        + (f" (was {s_old}+)" if s_old is not None and s_old != s_new else ""))
        if bits:
            parts.append(f"{fmt}s since {ERA_SPLIT}: " + ", and ".join(bits))
    show(fig, takeaway=("; ".join(parts) + ".") if parts else None, key="story_safe",
         table=curve[["format", "era", "band", "band_to", "matches", "won", "win_pct"]]
         .sort_values(["format", "era", "band"]).round(1)
         .rename(columns={"format": "Format", "era": "Era", "band": "Score from",
                          "band_to": "Score to", "matches": "Matches",
                          "won": "Batting-first wins", "win_pct": "Win %"}))


# --------------------------------------------------------------------------
# 2c. halfway pressure
# --------------------------------------------------------------------------

def _halfway(ctx: Ctx, halfway: pd.DataFrame, formats: list[str]) -> None:
    section("Halfway pressure — can this chase still be won?")
    st.caption(f"Every full-length chase still going at halfway (over {HALFWAY['ODI']} in "
               f"an ODI, over {HALFWAY['T20I']} in a T20I). Across: the run rate needed "
               f"from there. Up: how often the chase was won. One line per number of "
               f"wickets already lost. Points with fewer than {MIN_BAND} chases are left "
               f"out. {ctx.footer}")

    if halfway.empty:
        st.info("No full-length chases in this view. Widen the filters.")
        return
    h = halfway.copy()
    # Runs needed / overs left. Halfway means the overs left equal the overs gone.
    h["rate_needed"] = [rn / HALFWAY[f] for rn, f in zip(h["runs_needed"], h["format"])]
    h["rate_band"] = h["rate_needed"].clip(lower=0).floordiv(1).astype(int)
    h["group"] = pd.cut(h["wickets_down"], bins=[-1, 2, 4, 10],
                        labels=list(WICKET_GROUPS)).astype(str)
    pts = (h.groupby(["format", "group", "rate_band"])
           .agg(chases=("chase_won", "size"), won=("chase_won", "sum"))
           .reset_index())
    pts = pts[pts["chases"] >= MIN_BAND].copy()
    if pts.empty:
        st.info(f"No point in this view has {MIN_BAND} chases. Widen the filters.")
        return
    pts["win_pct"] = 100 * pts["won"] / pts["chases"]

    h_formats = [f for f in formats if f in set(pts["format"])]
    fig = make_subplots(rows=1, cols=len(h_formats), shared_yaxes=True,
                        horizontal_spacing=0.07, subplot_titles=h_formats)
    for c, fmt in enumerate(h_formats, start=1):
        for group, colour in WICKET_GROUPS.items():
            g = pts[(pts["format"] == fmt) & (pts["group"] == group)].sort_values("rate_band")
            if g.empty:
                continue
            fig.add_trace(go.Scatter(
                x=g["rate_band"] + 0.5, y=g["win_pct"], mode="lines+markers",
                name=group, legendgroup=group, showlegend=(c == 1),
                line=dict(color=colour, width=2.5),
                marker=dict(size=8, color=colour, line=dict(color=SURFACE, width=2)),
                customdata=g[["rate_band", "chases", "won"]],
                hovertemplate=(f"{fmt}, {group} at halfway<br>needing %{{customdata[0]}}–"
                               "%{customdata[0]}.9 an over: <b>won %{y:.0f}%</b><br>"
                               "%{customdata[2]} of %{customdata[1]} chases<extra></extra>"),
            ), row=1, col=c)
        fig.add_hline(y=50, line=dict(color=MUTED, width=1, dash="dot"), row=1, col=c)
        fig.update_xaxes(title_text="Run rate needed from halfway", row=1, col=c)
    base_layout(fig, height=420)
    legend_below(fig, y=-0.16)
    fig.update_layout(hovermode="closest")
    fig.update_yaxes(range=[0, 102], ticksuffix="%", dtick=25)
    fig.update_yaxes(title_text="Chases won", row=1, col=1)
    panel_titles_left(fig, h_formats)

    # Takeaway: for the "0-2 down" line, the rate at which a chase becomes a
    # coin flip - the first band where it is won less than half the time.
    parts = []
    for fmt in h_formats:
        bits = []
        for group in ("0–2 down", "3–4 down"):
            g = pts[(pts["format"] == fmt) & (pts["group"] == group)].sort_values("rate_band")
            below = g[g["win_pct"] < 50]
            if not below.empty and len(g) > len(below):
                bits.append(f"{group}, needing <strong>{int(below['rate_band'].iloc[0])}+"
                            f"</strong> an over")
        if bits:
            parts.append(f"{fmt}s: chases turn into underdogs at " + "; ".join(bits))
    takeaway = (". ".join(parts) + ". Each extra wicket at halfway knocks the line to the left."
                if parts else None)
    show(fig, takeaway=takeaway, key="story_halfway",
         table=pts.round(1).rename(columns={
             "format": "Format", "group": "Wickets at halfway",
             "rate_band": "Rate needed (from)", "chases": "Chases", "won": "Won",
             "win_pct": "Won %"}))


# --------------------------------------------------------------------------
# 2d. chase or defend
# --------------------------------------------------------------------------

def _chase_or_defend(ctx: Ctx, decided: pd.DataFrame, formats: list[str]) -> None:
    section("Chase or defend — what wins, and what captains choose")
    st.caption("Green: the share of decided matches won by the side batting second. "
               "Grey: the share of toss winners who chose to bowl first, i.e. to chase. "
               f"Dotted line: 50%. Years with fewer than {MIN_MATCHES} decided matches "
               f"are left out. {ctx.footer}")

    yearly = (decided.assign(chose_chase=decided["toss_decision"].eq("field"))
              .groupby(["format", "year"])
              .agg(matches=("match_id", "size"), chase_won=("chase_won", "mean"),
                   chose_chase=("chose_chase", "mean"))
              .reset_index())
    yearly = yearly[yearly["matches"] >= MIN_MATCHES].copy()
    if yearly.empty:
        st.info(f"No year in this view has {MIN_MATCHES} decided matches. Widen the filters.")
        return
    yearly[["chase_won", "chose_chase"]] *= 100

    y_formats = [f for f in formats if f in set(yearly["format"])]
    lines = {"Chasing side won": ("chase_won", EMPHASIS),
             "Toss winner chose to chase": ("chose_chase", CONTEXT_GREY)}
    fig = make_subplots(rows=1, cols=len(y_formats), shared_yaxes=True,
                        horizontal_spacing=0.07, subplot_titles=y_formats)
    for c, fmt in enumerate(y_formats, start=1):
        g = yearly[yearly["format"] == fmt].sort_values("year")
        for name, (col, colour) in lines.items():
            fig.add_trace(go.Scatter(
                x=g["year"], y=g[col], mode="lines+markers", name=name,
                legendgroup=name, showlegend=(c == 1),
                line=dict(color=colour, width=2.5),
                marker=dict(size=7, color=colour, line=dict(color=SURFACE, width=2)),
                customdata=g[["matches"]],
                hovertemplate=(f"{fmt} %{{x}} · {name.lower()}: <b>%{{y:.0f}}%</b>"
                               "<br>%{customdata[0]} decided matches<extra></extra>"),
            ), row=1, col=c)
        fig.add_hline(y=50, line=dict(color=MUTED, width=1, dash="dot"), row=1, col=c)
    base_layout(fig, height=400)
    legend_below(fig)
    fig.update_layout(hovermode="closest")
    fig.update_yaxes(range=[0, 100], ticksuffix="%", dtick=25)
    fig.update_xaxes(dtick=4)
    panel_titles_left(fig, y_formats)

    parts = []
    for fmt in y_formats:
        d = decided[decided["format"] == fmt]
        won = 100 * d["chase_won"].mean()
        if d["year"].nunique() > 3:
            recent = d[d["year"] >= d["year"].max() - 2]
            chose = 100 * recent["toss_decision"].eq("field").mean()
            parts.append(f"{fmt}s — chasing sides won <strong>{won:.0f}%</strong> overall "
                         f"and {100 * recent['chase_won'].mean():.0f}% in the last three "
                         f"years, when <strong>{chose:.0f}%</strong> of toss winners chose "
                         f"to chase")
        else:
            chose = 100 * d["toss_decision"].eq("field").mean()
            parts.append(f"{fmt}s — chasing sides won <strong>{won:.0f}%</strong>, and "
                         f"<strong>{chose:.0f}%</strong> of toss winners chose to chase")
    show(fig, takeaway="; ".join(parts) + ".", key="story_chase",
         table=yearly.round(1).rename(columns={
             "format": "Format", "year": "Year", "matches": "Decided matches",
             "chase_won": "Chasing side won %", "chose_chase": "Chose to chase %"}))


# --------------------------------------------------------------------------
# 2e. does the toss matter?
# --------------------------------------------------------------------------

def _toss(ctx: Ctx, decided: pd.DataFrame, formats: list[str]) -> None:
    section("Does winning the toss win the match?")
    st.caption("How often the side that won the toss went on to win, split by what "
               "they chose. A coin toss that made no difference would sit on the "
               f"dotted 50% line. Decided matches only. {ctx.footer}")

    d = decided.copy()
    d["choice"] = d["toss_decision"].map({"bat": "Chose to bat", "field": "Chose to chase"})
    d = d.dropna(subset=["choice"])
    t = (d.groupby(["format", "choice"])
         .agg(matches=("match_id", "size"), won=("toss_winner_won", "sum"))
         .reset_index())
    t = t[t["matches"] >= MIN_MATCHES].copy()
    if t.empty:
        st.info("Not enough decided matches in this view. Widen the filters.")
        return
    t["win_pct"] = 100 * t["won"] / t["matches"]

    colours = {"Chose to bat": CONTEXT_GREY, "Chose to chase": EMPHASIS}
    fig = go.Figure()
    for choice, colour in colours.items():
        g = t[t["choice"] == choice]
        fig.add_trace(go.Bar(
            x=g["format"], y=g["win_pct"], name=choice,
            marker=dict(color=colour, line=dict(color=SURFACE, width=2)),
            text=[f"{v:.0f}%" for v in g["win_pct"]], textposition="outside",
            textfont=dict(color=INK, size=12), cliponaxis=False,
            customdata=g[["matches", "won"]],
            hovertemplate=(f"%{{x}} · {choice.lower()}: <b>toss winner won %{{y:.1f}}%</b>"
                           "<br>%{customdata[1]} of %{customdata[0]} matches<extra></extra>"),
        ))
    fig.add_hline(y=50, line=dict(color=MUTED, width=1, dash="dot"))
    base_layout(fig, height=340, y_title="Toss winner won")
    fig.update_layout(barmode="group", bargap=0.45, bargroupgap=0.08)
    fig.update_yaxes(range=[0, 75], ticksuffix="%", dtick=25)

    overall = (d.groupby("format")["toss_winner_won"].mean() * 100).round(1)
    parts = [f"{fmt}s <strong>{overall[fmt]:.1f}%</strong>" for fmt in formats if fmt in overall]
    takeaway = ("Toss winners went on to win: " + ", ".join(parts)
                + ". Anything close to 50% means the toss barely matters — the side that "
                  "plays better wins either way.")
    show(fig, takeaway=takeaway, key="story_toss",
         table=t.round(1).rename(columns={"format": "Format", "choice": "Toss choice",
                                          "matches": "Matches", "won": "Toss winner won",
                                          "win_pct": "Won %"}))