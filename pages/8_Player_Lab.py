"""
Player Lab — pick any player and see their international career.

    picker          every player who batted or bowled in the filtered matches
    header          role, team, span, and a tile row per format
    batting         every innings on a timeline · runs per year ·
                    record against each opponent · how they get out, and
                    which bowlers get them out most
    bowling         wickets per year · economy and wickets by phase
                    (only for players who bowled regularly)

Everything follows the sidebar filters: "India, 2015 onward, T20I" shows
that slice of the player's career. ODI and T20I figures are never added
together - each format has its own tiles, colour and bars.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils.charts import INK, MUTED, SURFACE, WICKET, base_layout, show
from utils.db_connection import DatabaseError, run_query
from utils.filters import match_where, team_id
from utils.story import FORMAT_COLOURS
from utils.theme import card, page_header, rule, section, tiles

# The bowling section is for real bowlers, not part-timers: it shows when the
# player is a bowler or all-rounder, or has taken this many wickets in view.
MIN_BOWLING_WICKETS = 15
HOW_OUT = {"caught": "Caught", "caught and bowled": "Caught", "bowled": "Bowled",
           "lbw": "LBW", "run out": "Run out", "stumped": "Stumped"}
TOP_OPPONENTS = 10
PHASE_ORDER = ["powerplay", "middle", "death"]
PHASE_NAMES = {"powerplay": "Powerplay", "middle": "Middle overs", "death": "Death overs"}


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def player_list(where: str, params: dict, team: int | None) -> pd.DataFrame:
    """Everyone who batted or bowled in the filtered matches, busiest first.
    With a team chosen, only that team's players."""
    team_rule = "AND x.team_id = :pl_team" if team else ""
    return run_query(f"""
        WITH x AS (
            SELECT b.player_id, b.team_id, b.runs_scored AS runs, 0 AS wkts, b.match_id
            FROM fact_batting b JOIN fact_match m ON m.match_id = b.match_id WHERE {where}
            UNION ALL
            SELECT w.player_id, w.team_id, 0, w.wickets, w.match_id
            FROM fact_bowling w JOIN fact_match m ON m.match_id = w.match_id WHERE {where}
        )
        SELECT p.player_id, p.player_name, p.primary_team,
               count(DISTINCT x.match_id) AS matches, sum(x.runs) AS runs, sum(x.wkts) AS wkts
        FROM x JOIN dim_player p ON p.player_id = x.player_id
        WHERE TRUE {team_rule}
        GROUP BY 1, 2, 3
        ORDER BY matches DESC, runs DESC
    """, {**params, "pl_team": team})


@st.cache_data(ttl=3600, show_spinner=False)
def player_info(player_id: str) -> dict:
    df = run_query("""
        SELECT player_name, primary_team, playing_role, debut, last_match,
               batting_style, bowling_style, gender
        FROM dim_player WHERE player_id = :pid
    """, {"pid": player_id})
    return df.iloc[0].to_dict()


@st.cache_data(ttl=3600, show_spinner=False)
def batting_innings(where: str, params: dict, player_id: str) -> pd.DataFrame:
    """Every innings the player batted in, oldest first."""
    return run_query(f"""
        SELECT m.match_id, m.match_date, m.match_format AS format,
               b.batting_position AS position, b.runs_scored AS runs,
               b.balls_faced AS balls, b.fours, b.sixes, b.is_not_out,
               b.dismissal_kind, bw.player_name AS bowler,
               opp.team_display AS opponent
        FROM fact_batting b
        JOIN fact_match   m   ON m.match_id  = b.match_id
        JOIN dim_team     opp ON opp.team_id = CASE WHEN b.team_id = m.team1_id
                                                    THEN m.team2_id ELSE m.team1_id END
        LEFT JOIN dim_player bw ON bw.player_id = b.dismissed_by_id
        WHERE b.player_id = :pid AND {where}
        ORDER BY m.match_date, m.match_id
    """, {**params, "pid": player_id})


@st.cache_data(ttl=3600, show_spinner=False)
def bowling_innings(where: str, params: dict, player_id: str) -> pd.DataFrame:
    return run_query(f"""
        SELECT m.match_id, m.match_date, m.match_format AS format,
               w.balls_bowled AS balls, w.runs_conceded AS runs, w.wickets,
               opp.team_display AS opponent
        FROM fact_bowling w
        JOIN fact_match   m   ON m.match_id  = w.match_id
        JOIN dim_team     opp ON opp.team_id = CASE WHEN w.team_id = m.team1_id
                                                    THEN m.team2_id ELSE m.team1_id END
        WHERE w.player_id = :pid AND {where}
        ORDER BY m.match_date, m.match_id
    """, {**params, "pid": player_id})


@st.cache_data(ttl=3600, show_spinner=False)
def bowling_phases(where: str, params: dict, player_id: str) -> pd.DataFrame:
    """Overs bowled by the player, grouped by phase of the innings.

    fact_over credits an over to the bowler who bowled most of it (338
    overs in the archive were finished by a second bowler), and bowler_runs
    excludes byes and leg-byes, which are not the bowler's fault."""
    return run_query(f"""
        SELECT m.match_format AS format, o.phase,
               count(*) AS overs, sum(o.legal_balls) AS balls,
               sum(o.bowler_runs) AS runs, sum(o.bowler_wickets) AS wickets,
               sum(o.dots) AS dots
        FROM fact_over  o
        JOIN fact_match m ON m.match_id = o.match_id
        WHERE o.bowler_id = :pid AND {where}
        GROUP BY 1, 2
    """, {**params, "pid": player_id})


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def batting_summary(b: pd.DataFrame) -> dict:
    outs = int((~b["is_not_out"].astype(bool)).sum())
    runs, balls = int(b["runs"].sum()), int(b["balls"].sum())
    return {
        "innings": len(b), "runs": runs, "outs": outs,
        "average": runs / outs if outs else np.nan,
        "strike_rate": 100 * runs / balls if balls else np.nan,
        "hundreds": int((b["runs"] >= 100).sum()),
        "fifties": int(((b["runs"] >= 50) & (b["runs"] < 100)).sum()),
        "best": b.loc[b["runs"].idxmax()] if len(b) else None,
    }


def fmt_num(v: float, digits: int = 1) -> str:
    return "–" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{digits}f}"


def overs_text(balls: int) -> str:
    return f"{balls // 6}" if balls % 6 == 0 else f"{balls // 6}.{balls % 6}"


# --------------------------------------------------------------------------
# page: heading and picker
# --------------------------------------------------------------------------

page_header("Player Lab", "Pick any player and see their international career, ball by ball.",
            eyebrow="Analytics")

where, params = match_where("m")
try:
    players = player_list(where, params, team_id())
except DatabaseError as exc:
    st.error(str(exc))
    st.stop()

if players.empty:
    st.info("No players fit the filters in the sidebar. Widen them, or press Clear all.")
    st.stop()

labels = {r.player_id: f"{r.player_name} · {r.primary_team or '—'} · {r.matches} matches"
          for r in players.itertuples()}
if st.session_state.get("pl_player") not in labels:
    st.session_state["pl_player"] = players["player_id"].iloc[0]   # busiest player in view
st.selectbox(f"Search {len(labels):,} players (type a name)", options=list(labels),
             format_func=labels.get, key="pl_player")
pid = st.session_state["pl_player"]

try:
    info = player_info(pid)
    bat = batting_innings(where, params, pid)
    bowl = bowling_innings(where, params, pid)
    phases = bowling_phases(where, params, pid)
except DatabaseError as exc:
    st.error(str(exc))
    st.stop()

# --------------------------------------------------------------------------
# header
# --------------------------------------------------------------------------

span = f"{pd.Timestamp(info['debut']):%b %Y} – {pd.Timestamp(info['last_match']):%b %Y}"
styles = " · ".join(s for s in (info.get("batting_style"), info.get("bowling_style")) if s)
card(info["player_name"], f"""
  <p style="font-size:1.05rem;margin:0 0 .3rem 0"><strong>{info['primary_team'] or '—'}</strong>
     · {info['playing_role']} · international career {span}</p>
  <p style="color:var(--cb-muted);margin:0">{styles or 'Batting and bowling style not recorded'}
     · figures below follow the sidebar filters</p>
""")

formats = [f for f in ("ODI", "T20I") if f in set(bat["format"]) | set(bowl["format"])]
for fmt in formats:
    b = bat[bat["format"] == fmt]
    w = bowl[bowl["format"] == fmt]
    cells = []
    if len(b):
        s = batting_summary(b)
        best = s["best"]
        cells += [
            (f"{fmt} runs", f"{s['runs']:,}", f"{s['innings']} innings"),
            ("Average", fmt_num(s["average"]), f"strike rate {fmt_num(s['strike_rate'])}"),
            ("100s / 50s", f"{s['hundreds']} / {s['fifties']}",
             f"best {int(best['runs'])}{'*' if best['is_not_out'] else ''} v {best['opponent']}"),
        ]
    if len(w) and w["balls"].sum() > 0:
        wk, runs, balls = int(w["wickets"].sum()), int(w["runs"].sum()), int(w["balls"].sum())
        best_w = w.sort_values(["wickets", "runs"], ascending=[False, True]).iloc[0]
        cells += [
            (f"{fmt} wickets", f"{wk}", f"{overs_text(balls)} overs"),
            ("Economy", fmt_num(6 * runs / balls, 2),
             f"average {fmt_num(runs / wk if wk else np.nan)}"),
            ("Best bowling", f"{int(best_w['wickets'])}/{int(best_w['runs'])}",
             f"v {best_w['opponent']}"),
        ]
    if cells:
        tiles(cells)

if bat.empty and bowl.empty:
    st.info("This player did not bat or bowl in the matches the filters select.")
    st.stop()

# --------------------------------------------------------------------------
# batting
# --------------------------------------------------------------------------

if not bat.empty:
    rule()
    section("Every innings — the career timeline")
    st.caption("One dot per innings, in date order. Up: runs scored. Ringed dots were not "
               "out. Dotted lines mark 50 and 100. Hover for the match.")

    fig = go.Figure()
    for fmt in formats:
        g = bat[bat["format"] == fmt]
        if g.empty:
            continue
        not_out = g["is_not_out"].astype(bool)
        fig.add_trace(go.Scatter(
            x=g["match_date"], y=g["runs"], mode="markers", name=fmt,
            marker=dict(size=[10 if r >= 100 else 7 for r in g["runs"]],
                        color=[SURFACE if n else FORMAT_COLOURS[fmt] for n in not_out],
                        line=dict(color=FORMAT_COLOURS[fmt], width=2)),
            customdata=np.stack([g["opponent"], g["balls"],
                                 np.where(not_out, "not out", g["dismissal_kind"].fillna(""))],
                                axis=-1),
            hovertemplate=(fmt + " %{x|%d %b %Y} v %{customdata[0]}<br><b>%{y}</b> off "
                           "%{customdata[1]} balls · %{customdata[2]}<extra></extra>"),
        ))
    for ref in (50, 100):
        fig.add_hline(y=ref, line=dict(color=MUTED, width=1, dash="dot"))
    base_layout(fig, height=380, y_title="Runs in the innings")
    fig.update_layout(hovermode="closest")
    fig.update_yaxes(rangemode="tozero")

    s_all = batting_summary(bat)
    best = s_all["best"]
    show(fig, key="pl_timeline",
         takeaway=(f"{s_all['innings']} innings, <strong>{s_all['runs']:,} runs</strong>, "
                   f"{s_all['hundreds']} hundreds and {s_all['fifties']} fifties. Best: "
                   f"<strong>{int(best['runs'])}{'*' if best['is_not_out'] else ''}</strong> "
                   f"v {best['opponent']}, {pd.Timestamp(best['match_date']):%d %b %Y}."),
         table=bat[["match_date", "format", "opponent", "position", "runs", "balls",
                    "fours", "sixes", "is_not_out", "dismissal_kind"]]
         .rename(columns={"match_date": "Date", "format": "Format", "opponent": "Opponent",
                          "position": "Position", "runs": "Runs", "balls": "Balls",
                          "fours": "4s", "sixes": "6s", "is_not_out": "Not out",
                          "dismissal_kind": "How out"}))

    # ---- runs per year ------------------------------------------------------
    rule()
    section("Runs per year")
    st.caption("Total runs in each calendar year, by format. Hover for the average and "
               "strike rate that year.")
    yearly = []
    for (fmt, year), g in bat.assign(year=pd.to_datetime(bat["match_date"]).dt.year) \
                             .groupby(["format", "year"]):
        s = batting_summary(g)
        yearly.append({"format": fmt, "year": year, "innings": s["innings"], "runs": s["runs"],
                       "average": s["average"], "strike_rate": s["strike_rate"]})
    yearly = pd.DataFrame(yearly)
    fig = go.Figure()
    for fmt in formats:
        g = yearly[yearly["format"] == fmt]
        if g.empty:
            continue
        fig.add_trace(go.Bar(
            x=g["year"], y=g["runs"], name=fmt,
            marker=dict(color=FORMAT_COLOURS[fmt], line=dict(color=SURFACE, width=1)),
            customdata=g[["innings", "average", "strike_rate"]].fillna(0),
            hovertemplate=(fmt + " %{x}: <b>%{y} runs</b><br>%{customdata[0]} innings · "
                           "average %{customdata[1]:.1f} · strike rate %{customdata[2]:.1f}"
                           "<extra></extra>"),
        ))
    base_layout(fig, height=320, y_title="Runs")
    fig.update_layout(barmode="group", bargap=0.2, hovermode="x unified")
    fig.update_yaxes(tickformat=",d")
    fig.update_xaxes(dtick=1 if yearly["year"].nunique() <= 12 else 2)
    top = yearly.loc[yearly["runs"].idxmax()]
    show(fig, key="pl_years",
         takeaway=(f"Best year: <strong>{int(top['year'])}</strong>, with "
                   f"{int(top['runs']):,} {top['format']} runs in {int(top['innings'])} innings "
                   f"(average {fmt_num(top['average'])})."),
         table=yearly.round(1).rename(columns={"format": "Format", "year": "Year",
                                               "innings": "Innings", "runs": "Runs",
                                               "average": "Average",
                                               "strike_rate": "Strike rate"}))

    # ---- against each opponent ---------------------------------------------
    rule()
    section(f"Against each opponent — top {TOP_OPPONENTS} by runs")
    st.caption("Runs against each side, all formats in view together. Hover for innings, "
               "average and strike rate.")
    opp = []
    for team, g in bat.groupby("opponent"):
        s = batting_summary(g)
        opp.append({"opponent": team, "innings": s["innings"], "runs": s["runs"],
                    "average": s["average"], "strike_rate": s["strike_rate"],
                    "hundreds": s["hundreds"]})
    opp = pd.DataFrame(opp).sort_values("runs", ascending=False)
    shown = opp.head(TOP_OPPONENTS).iloc[::-1]
    fig = go.Figure(go.Bar(
        y=shown["opponent"], x=shown["runs"], orientation="h", showlegend=False,
        marker=dict(color=FORMAT_COLOURS["ODI"], line=dict(color=SURFACE, width=1)),
        text=[f"{int(r):,}" for r in shown["runs"]], textposition="outside",
        textfont=dict(color=INK, size=11), cliponaxis=False,
        customdata=shown[["innings", "average", "strike_rate", "hundreds"]].fillna(0),
        hovertemplate=("v %{y}: <b>%{x:,} runs</b><br>%{customdata[0]} innings · average "
                       "%{customdata[1]:.1f} · strike rate %{customdata[2]:.1f} · "
                       "%{customdata[3]} hundreds<extra></extra>"),
    ))
    base_layout(fig, height=80 + 30 * len(shown), x_title="Runs", legend=False)
    fig.update_yaxes(showgrid=False, tickfont=dict(size=11, color=INK))
    fig.update_layout(bargap=0.3)
    q = opp[opp["innings"] >= 5]
    takeaway = None
    if not q.empty and q["average"].notna().any():
        fav = q.loc[q["average"].idxmax()]
        takeaway = (f"Most runs against <strong>{opp.iloc[0]['opponent']}</strong> "
                    f"({int(opp.iloc[0]['runs']):,}). Highest average (5+ innings): "
                    f"<strong>{fav['opponent']}</strong>, {fmt_num(fav['average'])}.")
    show(fig, key="pl_opp", takeaway=takeaway,
         table=opp.round(1).rename(columns={"opponent": "Opponent", "innings": "Innings",
                                            "runs": "Runs", "average": "Average",
                                            "strike_rate": "Strike rate",
                                            "hundreds": "100s"}))

    # ---- how they get out ---------------------------------------------------
    outs = bat[~bat["is_not_out"].astype(bool)]
    if len(outs):
        rule()
        section("How they get out — and who gets them out")
        left, right = st.columns(2, gap="large")
        with left:
            how = outs["dismissal_kind"].map(HOW_OUT).fillna("Other").value_counts()
            how_pct = (100 * how / how.sum()).iloc[::-1]
            fig = go.Figure(go.Bar(
                y=how_pct.index, x=how_pct.values, orientation="h", showlegend=False,
                marker=dict(color=WICKET, line=dict(color=SURFACE, width=1)),
                text=[f"{v:.0f}%" for v in how_pct.values], textposition="outside",
                textfont=dict(color=INK, size=11), cliponaxis=False,
                customdata=how.iloc[::-1].values,
                hovertemplate="%{y}: <b>%{x:.0f}%</b> (%{customdata} times)<extra></extra>",
            ))
            base_layout(fig, height=60 + 34 * len(how_pct), x_title="Share of dismissals",
                        legend=False)
            fig.update_xaxes(ticksuffix="%", range=[0, how_pct.max() * 1.2])
            fig.update_yaxes(showgrid=False, tickfont=dict(size=11, color=INK))
            show(fig, key="pl_how",
                 takeaway=f"Out <strong>{how.index[0].lower()}</strong> in "
                          f"{100 * how.iloc[0] / how.sum():.0f}% of {int(how.sum())} dismissals.",
                 table=how.reset_index().rename(columns={"dismissal_kind": "How out",
                                                         "index": "How out", "count": "Times"}))
        with right:
            by = outs.dropna(subset=["bowler"])["bowler"].value_counts().head(8)
            if by.empty:
                st.info("No bowler is credited with these dismissals (run outs only).")
            else:
                shown = by.iloc[::-1]
                fig = go.Figure(go.Bar(
                    y=shown.index, x=shown.values, orientation="h", showlegend=False,
                    marker=dict(color=MUTED, line=dict(color=SURFACE, width=1)),
                    text=[str(v) for v in shown.values], textposition="outside",
                    textfont=dict(color=INK, size=11), cliponaxis=False,
                    hovertemplate="%{y}: <b>%{x}</b> dismissals<extra></extra>",
                ))
                base_layout(fig, height=60 + 34 * len(shown), x_title="Times dismissed",
                            legend=False)
                fig.update_xaxes(tickformat="d", range=[0, shown.max() * 1.25])
                fig.update_yaxes(showgrid=False, tickfont=dict(size=11, color=INK))
                show(fig, key="pl_by",
                     takeaway=f"<strong>{by.index[0]}</strong> has dismissed them most: "
                              f"{int(by.iloc[0])} times.",
                     table=by.reset_index().rename(columns={"bowler": "Bowler",
                                                            "index": "Bowler",
                                                            "count": "Dismissals"}))

# --------------------------------------------------------------------------
# bowling
# --------------------------------------------------------------------------

is_bowler = (info["playing_role"] in ("Bowler", "All-rounder")
             or bowl["wickets"].sum() >= MIN_BOWLING_WICKETS)
if is_bowler and len(bowl) and bowl["balls"].sum() > 0:
    rule()
    section("Bowling — wickets per year")
    st.caption("Wickets in each calendar year, by format. Hover for the economy rate.")
    wy = (bowl.assign(year=pd.to_datetime(bowl["match_date"]).dt.year)
          .groupby(["format", "year"])
          .agg(innings=("match_id", "size"), wickets=("wickets", "sum"),
               runs=("runs", "sum"), balls=("balls", "sum")).reset_index())
    wy["economy"] = 6 * wy["runs"] / wy["balls"].replace(0, np.nan)
    fig = go.Figure()
    for fmt in formats:
        g = wy[wy["format"] == fmt]
        if g.empty:
            continue
        fig.add_trace(go.Bar(
            x=g["year"], y=g["wickets"], name=fmt,
            marker=dict(color=FORMAT_COLOURS[fmt], line=dict(color=SURFACE, width=1)),
            customdata=g[["innings", "economy"]].fillna(0),
            hovertemplate=(fmt + " %{x}: <b>%{y} wickets</b><br>%{customdata[0]} innings · "
                           "economy %{customdata[1]:.2f}<extra></extra>"),
        ))
    base_layout(fig, height=320, y_title="Wickets")
    fig.update_layout(barmode="group", bargap=0.2, hovermode="x unified")
    fig.update_yaxes(tickformat="d", rangemode="tozero")
    fig.update_xaxes(dtick=1 if wy["year"].nunique() <= 12 else 2)
    top = wy.loc[wy["wickets"].idxmax()]
    show(fig, key="pl_wkts",
         takeaway=(f"<strong>{int(bowl['wickets'].sum())} wickets</strong> in {len(bowl)} "
                   f"innings. Best year: {int(top['year'])}, {int(top['wickets'])} "
                   f"{top['format']} wickets."),
         table=wy.round(2).rename(columns={"format": "Format", "year": "Year",
                                           "innings": "Innings", "wickets": "Wickets",
                                           "runs": "Runs", "balls": "Balls",
                                           "economy": "Economy"}))

    if not phases.empty:
        rule()
        section("Bowling — economy by phase of the innings")
        st.caption("Runs conceded per over in the powerplay, the middle overs and the death "
                   "overs (ODI: first 10 / last 10 overs; T20I: first 6 / last 5). Byes and "
                   "leg-byes are not counted against the bowler. Hover for wickets and "
                   "dot balls.")
        ph = phases.copy()
        ph["economy"] = 6 * ph["runs"] / ph["balls"].replace(0, np.nan)
        ph["dot_pct"] = 100 * ph["dots"] / ph["balls"].replace(0, np.nan)
        ph["phase_name"] = ph["phase"].map(PHASE_NAMES)
        fig = go.Figure()
        for fmt in formats:
            g = ph[ph["format"] == fmt].set_index("phase").reindex(PHASE_ORDER).dropna(
                subset=["overs"]).reset_index()
            if g.empty:
                continue
            fig.add_trace(go.Bar(
                x=g["phase"].map(PHASE_NAMES), y=g["economy"], name=fmt,
                marker=dict(color=FORMAT_COLOURS[fmt], line=dict(color=SURFACE, width=1)),
                text=[f"{v:.2f}" for v in g["economy"]], textposition="outside",
                textfont=dict(color=INK, size=11), cliponaxis=False,
                customdata=g[["overs", "wickets", "dot_pct"]].fillna(0),
                hovertemplate=(fmt + " · %{x}: <b>economy %{y:.2f}</b><br>%{customdata[0]:.0f}"
                               " overs · %{customdata[1]:.0f} wickets · %{customdata[2]:.0f}% "
                               "dot balls<extra></extra>"),
            ))
        base_layout(fig, height=340, y_title="Runs per over")
        fig.update_layout(barmode="group", bargap=0.35)
        fig.update_yaxes(rangemode="tozero")
        busiest = ph.loc[ph["overs"].idxmax()]
        show(fig, key="pl_phase",
             takeaway=(f"Bowls most in the <strong>{busiest['phase_name'].lower()}</strong> "
                       f"({int(busiest['overs'])} {busiest['format']} overs, economy "
                       f"{busiest['economy']:.2f})."),
             table=ph[["format", "phase_name", "overs", "wickets", "economy", "dot_pct"]]
             .round(2).rename(columns={"format": "Format", "phase_name": "Phase",
                                       "overs": "Overs", "wickets": "Wickets",
                                       "economy": "Economy", "dot_pct": "Dot balls %"}))