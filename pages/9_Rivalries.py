"""
Rivalries — how the big teams do against each other, and any two teams head to head.

    win matrix       the 12 full members against each other: how often the
                     team on the left beat the team on top
    pick two teams   then, for that pair:
        tiles            matches, wins each, ties and no-results, per format
        results strip    every match in date order, coloured by the winner
        running score    the head-to-head lead, match after match
        home and away    each side's win rate at home, away and on neutral grounds
        star players     the top run-scorers and wicket-takers in the rivalry

Everything follows the sidebar filters, except Team and Opponent: this page
has its own two team boxes (they start on the sidebar's choice, if any).
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils.charts import INK, MUTED, SURFACE, base_layout, show
from utils.db_connection import DatabaseError, run_query
from utils.filters import match_where
from utils.story import FULL_MEMBERS
from utils.theme import page_header, rule, section, tiles

# The two sides keep the same colours on every chart on this page.
SIDE_A, SIDE_B = "#1F7A4A", "#B8913F"
NO_RESULT = "#C9CFCA"
MIN_CELL = 5          # matches before a win-matrix cell is shown
TOP_PLAYERS = 8


# --------------------------------------------------------------------------
# the sidebar filters, minus Team and Opponent
# --------------------------------------------------------------------------

def where_without_teams() -> tuple[str, dict]:
    """match_where() with its team/opponent conditions taken out, because
    this page chooses its own two teams."""
    where, params = match_where("m")
    for key in ("f_team", "f_opp"):
        where = re.sub(rf"(\s+AND\s+)?:{key} IN \(m\.team1_id, m\.team2_id\)(\s+AND\s+)?",
                       lambda mt: " AND " if mt.group(1) and mt.group(2) else "", where)
        params.pop(key, None)
    return (where.strip() or "TRUE"), params


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def matrix_rows(where: str, params: dict) -> pd.DataFrame:
    """Every decided match between two full members, once from each side."""
    return run_query(f"""
        WITH d AS (
            SELECT t1.team_name AS a, t2.team_name AS b, w.team_name AS winner
            FROM fact_match m
            JOIN dim_team t1 ON t1.team_id = m.team1_id
            JOIN dim_team t2 ON t2.team_id = m.team2_id
            JOIN dim_team w  ON w.team_id  = m.winner_id
            WHERE m.victory_type IN ('runs', 'wickets')
              AND t1.team_name = ANY(:fm) AND t2.team_name = ANY(:fm)
              AND {where}
        )
        SELECT team, opponent, count(*) AS matches, sum((winner = team)::int) AS won
        FROM (SELECT a AS team, b AS opponent, winner FROM d
              UNION ALL
              SELECT b, a, winner FROM d) x
        GROUP BY 1, 2
    """, {**params, "fm": list(FULL_MEMBERS)})


@st.cache_data(ttl=3600, show_spinner=False)
def team_options(where: str, params: dict) -> pd.DataFrame:
    """Teams with at least one match in view, busiest first."""
    return run_query(f"""
        SELECT t.team_id, t.team_display, count(*) AS matches
        FROM fact_match m
        JOIN dim_team t ON t.team_id IN (m.team1_id, m.team2_id)
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY matches DESC, t.team_display
    """, params)


@st.cache_data(ttl=3600, show_spinner=False)
def opponents_of(where: str, params: dict, a: int) -> pd.DataFrame:
    """Every team that `a` has played in view, most-played first."""
    return run_query(f"""
        SELECT CASE WHEN m.team1_id = :ta THEN m.team2_id ELSE m.team1_id END AS team_id,
               count(*) AS matches
        FROM fact_match m
        WHERE :ta IN (m.team1_id, m.team2_id) AND {where}
        GROUP BY 1
        ORDER BY matches DESC
    """, {**params, "ta": a})


@st.cache_data(ttl=3600, show_spinner=False)
def pair_matches(where: str, params: dict, a: int, b: int) -> pd.DataFrame:
    """Every match between the two teams, oldest first."""
    return run_query(f"""
        SELECT m.match_id, m.match_date, m.match_format AS format,
               m.winner_id, m.victory_type, m.victory_margin, m.event_stage,
               s.series_name, v.venue_display AS ground, v.country, v.home_nation
        FROM fact_match m
        JOIN dim_series s ON s.series_id = m.series_id
        JOIN dim_venue  v ON v.venue_id  = m.venue_id
        WHERE ((m.team1_id = :ta AND m.team2_id = :tb) OR (m.team1_id = :tb AND m.team2_id = :ta))
          AND {where}
        ORDER BY m.match_date, m.match_id
    """, {**params, "ta": a, "tb": b})


@st.cache_data(ttl=3600, show_spinner=False)
def pair_batters(where: str, params: dict, a: int, b: int) -> pd.DataFrame:
    return run_query(f"""
        SELECT p.player_name AS player, t.team_display AS team,
               count(*) AS innings, sum(bt.runs_scored) AS runs,
               sum((NOT bt.is_not_out)::int) AS outs, max(bt.runs_scored) AS best
        FROM fact_batting bt
        JOIN fact_match m ON m.match_id  = bt.match_id
        JOIN dim_player p ON p.player_id = bt.player_id
        JOIN dim_team   t ON t.team_id   = bt.team_id
        WHERE ((m.team1_id = :ta AND m.team2_id = :tb) OR (m.team1_id = :tb AND m.team2_id = :ta))
          AND {where}
        GROUP BY 1, 2
        ORDER BY runs DESC
        LIMIT {TOP_PLAYERS}
    """, {**params, "ta": a, "tb": b})


@st.cache_data(ttl=3600, show_spinner=False)
def pair_bowlers(where: str, params: dict, a: int, b: int) -> pd.DataFrame:
    return run_query(f"""
        SELECT p.player_name AS player, t.team_display AS team,
               count(*) AS innings, sum(w.wickets) AS wickets,
               sum(w.runs_conceded) AS runs, sum(w.balls_bowled) AS balls
        FROM fact_bowling w
        JOIN fact_match m ON m.match_id  = w.match_id
        JOIN dim_player p ON p.player_id = w.player_id
        JOIN dim_team   t ON t.team_id   = w.team_id
        WHERE ((m.team1_id = :ta AND m.team2_id = :tb) OR (m.team1_id = :tb AND m.team2_id = :ta))
          AND {where}
        GROUP BY 1, 2
        ORDER BY wickets DESC, runs
        LIMIT {TOP_PLAYERS}
    """, {**params, "ta": a, "tb": b})


@st.cache_data(ttl=3600, show_spinner=False)
def team_names(ids: tuple[int, ...]) -> dict:
    df = run_query("SELECT team_id, team_name, team_display FROM dim_team "
                   "WHERE team_id = ANY(:ids)", {"ids": list(ids)})
    return {int(r.team_id): (r.team_name, r.team_display) for r in df.itertuples()}


# --------------------------------------------------------------------------
# page
# --------------------------------------------------------------------------

page_header("Rivalries",
            "How the big teams fare against each other — and any two teams, head to head.",
            eyebrow="Analytics")

where, params = where_without_teams()

# ==========================================================================
# the win matrix
# ==========================================================================
section("The win matrix — full members against each other")
st.caption("Each square: how often the team on the left beat the team along the top, in "
           f"decided matches. Green = usually wins, red = usually loses. Squares with fewer "
           f"than {MIN_CELL} matches are left blank. Men's and women's sides of the same "
           "country count together unless you pick one in the sidebar. Team and Opponent in "
           "the sidebar are ignored here.")

try:
    mx = matrix_rows(where, params)
except DatabaseError as exc:
    st.error(str(exc))
    st.stop()

if mx.empty:
    st.info("No matches between full members in this view. Widen the filters.")
else:
    mx["pct"] = np.where(mx["matches"] >= MIN_CELL, 100 * mx["won"] / mx["matches"], np.nan)
    # Order teams by their overall win rate against the others, best at the top.
    overall = (mx.groupby("team")[["won", "matches"]].sum()
               .assign(rate=lambda d: d["won"] / d["matches"]).sort_values("rate"))
    order = list(overall.index)
    grid = mx.pivot(index="team", columns="opponent", values="pct").reindex(
        index=order, columns=order[::-1])
    counts = mx.pivot(index="team", columns="opponent", values="matches").reindex(
        index=order, columns=order[::-1])
    wins = mx.pivot(index="team", columns="opponent", values="won").reindex(
        index=order, columns=order[::-1])
    text = [[("" if np.isnan(v) else f"{v:.0f}") for v in row] for row in grid.values]
    fig = go.Figure(go.Heatmap(
        z=grid.values, x=grid.columns, y=grid.index, zmin=0, zmax=100, zmid=50,
        # Diverging: red below 50%, a light neutral at 50%, green above.
        colorscale=[[0, "#8D2B28"], [0.5, "#F1F2EE"], [1, "#1F7A4A"]],
        text=text, texttemplate="%{text}", textfont=dict(size=11),
        customdata=np.dstack([counts.fillna(0).values, wins.fillna(0).values]),
        hovertemplate=("%{y} v %{x}: <b>won %{z:.0f}%</b><br>%{customdata[1]:.0f} of "
                       "%{customdata[0]:.0f} decided matches<extra></extra>"),
        xgap=2, ygap=2, colorbar=dict(title="Won %", ticksuffix="%", thickness=12),
    ))
    base_layout(fig, height=520, legend=False)
    fig.update_xaxes(side="top", showgrid=False, tickangle=-35,
                     tickfont=dict(size=11, color=INK))
    fig.update_yaxes(showgrid=False, tickfont=dict(size=11, color=INK))
    best = overall.iloc[-1]
    worst = overall.iloc[0]
    show(fig, key="riv_matrix",
         takeaway=(f"Against the other full members, <strong>{overall.index[-1]}</strong> "
                   f"win most often ({100 * best['rate']:.0f}% of "
                   f"{int(best['matches'])} decided matches) and "
                   f"<strong>{overall.index[0]}</strong> least often "
                   f"({100 * worst['rate']:.0f}%)."),
         table=mx.assign(pct=100 * mx["won"] / mx["matches"]).round(1)
         .sort_values(["team", "opponent"])
         .rename(columns={"team": "Team", "opponent": "Opponent", "matches": "Matches",
                          "won": "Won", "pct": "Won %"}))

# ==========================================================================
# pick two teams
# ==========================================================================
rule()
section("Head to head")

try:
    teams = team_options(where, params)
except DatabaseError as exc:
    st.error(str(exc))
    st.stop()
if len(teams) < 2:
    st.info("Fewer than two teams in this view. Widen the filters.")
    st.stop()

names = dict(zip(teams["team_id"].astype(int), teams["team_display"]))


def _pick(key: str, options: list[int], preferred: list[str | None]) -> None:
    """Keep the current choice if it is still offered; otherwise take the
    first preferred name that is offered, else the first option."""
    if st.session_state.get(key) in options:
        return
    for want in preferred:
        for tid in options:
            if want and names.get(tid) == want:
                st.session_state[key] = tid
                return
    st.session_state[key] = options[0]


# Team: the sidebar's Team if chosen, else India, else the busiest side.
_pick("riv_a", list(names), [st.session_state.get("f_team"), "India"])
left, right = st.columns(2)
with left:
    st.selectbox("Team", options=list(names), format_func=names.get, key="riv_a")
a = int(st.session_state["riv_a"])

# Against: only sides the first team has actually played, most-played first.
try:
    opps = opponents_of(where, params, a)
except DatabaseError as exc:
    st.error(str(exc))
    st.stop()
opp_ids = [int(t) for t in opps["team_id"] if int(t) in names]
if not opp_ids:
    st.info(f"{names[a]} have no opponents in this view. Widen the filters.")
    st.stop()
_pick("riv_b", opp_ids, [st.session_state.get("f_opp"), "Australia"])
with right:
    st.selectbox(f"Against ({len(opp_ids)} opponents)", options=opp_ids,
                 format_func=lambda t: f"{names[t]} · "
                                       f"{int(opps.loc[opps['team_id'] == t, 'matches'].iloc[0])} matches",
                 key="riv_b")
b = int(st.session_state["riv_b"])
name_a, name_b = names[a], names[b]
colour = {a: SIDE_A, b: SIDE_B}

try:
    games = pair_matches(where, params, a, b)
    batters = pair_batters(where, params, a, b)
    bowlers = pair_bowlers(where, params, a, b)
    home_of = team_names((a, b))
except DatabaseError as exc:
    st.error(str(exc))
    st.stop()

if games.empty:
    st.info(f"{name_a} and {name_b} have not played each other in this view.")
    st.stop()

games["result"] = np.select(
    [games["winner_id"] == a, games["winner_id"] == b],
    [name_a, name_b], default="Tie / no result")
formats = [f for f in ("ODI", "T20I") if f in set(games["format"])]

# ---- tiles -----------------------------------------------------------------
cells = []
for fmt in formats:
    g = games[games["format"] == fmt]
    wa, wb = int((g["winner_id"] == a).sum()), int((g["winner_id"] == b).sum())
    other = len(g) - wa - wb
    cells += [(f"{fmt}s played", f"{len(g)}",
               f"{g['match_date'].min():%Y}–{g['match_date'].max():%Y}"),
              (f"{name_a} won", f"{wa}", f"{100 * wa / len(g):.0f}%"),
              (f"{name_b} won", f"{wb}", f"{100 * wb / len(g):.0f}%"
               + (f" · {other} tied / no result" if other else ""))]
tiles(cells)

# ---- results strip ---------------------------------------------------------
rule()
section("Every match — the results strip")
st.caption(f"One bar per match, in date order, one row per format. Green: {name_a} won. "
           f"Gold: {name_b} won. Grey: tied or no result. Hover for the match.")
fig = go.Figure()
for label, col in ((name_a, SIDE_A), (name_b, SIDE_B), ("Tie / no result", NO_RESULT)):
    g = games[games["result"] == label]
    if g.empty:
        continue
    margin = np.where(g["victory_type"].isin(["runs", "wickets"]),
                      "by " + g["victory_margin"].fillna(0).astype(int).astype(str) + " "
                      + g["victory_type"].fillna(""), g["victory_type"].fillna(""))
    fig.add_trace(go.Bar(
        x=g["match_date"], y=[1] * len(g), base=[formats.index(f) for f in g["format"]],
        name=label, width=1000 * 60 * 60 * 24 * 20,   # 20 days wide, in milliseconds
        marker=dict(color=col, line=dict(width=0)),
        customdata=np.stack([g["format"], g["ground"], margin, g["series_name"]], axis=-1),
        hovertemplate=("%{customdata[0]} · %{x|%d %b %Y}<br><b>" + label + "</b> %{customdata[2]}"
                       "<br>%{customdata[1]} · %{customdata[3]}<extra></extra>"),
    ))
base_layout(fig, height=110 + 60 * len(formats))
fig.update_layout(barmode="overlay", bargap=0, hovermode="closest")
fig.update_yaxes(tickvals=[i + 0.5 for i in range(len(formats))], ticktext=formats,
                 range=[0, len(formats)], showgrid=False, separatethousands=False)
last10 = games.tail(10)
show(fig, key="riv_strip",
     takeaway=(f"Last {len(last10)} meetings: {name_a} "
               f"<strong>{int((last10['winner_id'] == a).sum())}</strong>, {name_b} "
               f"<strong>{int((last10['winner_id'] == b).sum())}</strong>."),
     table=games[["match_date", "format", "result", "victory_margin", "victory_type",
                  "ground", "series_name"]]
     .rename(columns={"match_date": "Date", "format": "Format", "result": "Winner",
                      "victory_margin": "Margin", "victory_type": "By",
                      "ground": "Ground", "series_name": "Series"}))

# ---- running score ----------------------------------------------------------
rule()
section("The running score — who leads the head-to-head")
st.caption(f"After every match: {name_a}'s wins minus {name_b}'s wins so far. Above zero, "
           f"{name_a} lead the head-to-head; below zero, {name_b} do. One line per format.")
fig = go.Figure()
for fmt in formats:
    g = games[games["format"] == fmt].copy()
    g["lead"] = ((g["winner_id"] == a).astype(int) - (g["winner_id"] == b).astype(int)).cumsum()
    fig.add_trace(go.Scatter(
        x=g["match_date"], y=g["lead"], mode="lines", name=fmt, line_shape="hv",
        line=dict(color=INK if fmt == "ODI" else MUTED, width=2.5,
                  dash="solid" if fmt == "ODI" else "dot"),
        hovertemplate=(fmt + " %{x|%d %b %Y}: " + name_a + " lead by <b>%{y}</b>"
                       "<extra></extra>"),
    ))
fig.add_hline(y=0, line=dict(color=MUTED, width=1))
base_layout(fig, height=340, y_title=f"{name_a} lead")
fig.update_layout(hovermode="closest")
fig.update_yaxes(zeroline=False, tickformat="d")
parts = []
for fmt in formats:
    g = games[games["format"] == fmt]
    lead = int((g["winner_id"] == a).sum() - (g["winner_id"] == b).sum())
    who = name_a if lead > 0 else name_b if lead < 0 else None
    parts.append(f"{fmt}s — " + (f"<strong>{who}</strong> lead by {abs(lead)}" if who
                                 else "all square"))
show(fig, key="riv_running", takeaway="; ".join(parts) + ".")

# ---- home and away ----------------------------------------------------------
rule()
section("Home and away")
st.caption("Each side's win rate against the other, split by where the match was played: "
           "at home, away (at the other side's home), or at a neutral ground. Ties and "
           "no-results count as not won.")
rows = []
for tid, side in ((a, name_a), (b, name_b)):
    other = b if tid == a else a
    home_name, other_name = home_of[tid][0], home_of[other][0]
    where_played = np.where(games["home_nation"] == home_name, "Home",
                            np.where(games["home_nation"] == other_name, "Away", "Neutral"))
    for place in ("Home", "Away", "Neutral"):
        g = games[where_played == place]
        if len(g):
            rows.append({"side": side, "where": place, "matches": len(g),
                         "won": int((g["winner_id"] == tid).sum())})
ha = pd.DataFrame(rows, columns=["side", "where", "matches", "won"])
ha["pct"] = 100 * ha["won"] / ha["matches"]
fig = go.Figure()
for side, col in ((name_a, SIDE_A), (name_b, SIDE_B)):
    g = ha[ha["side"] == side]
    fig.add_trace(go.Bar(
        x=g["where"], y=g["pct"], name=side,
        marker=dict(color=col, line=dict(color=SURFACE, width=2)),
        text=[f"{v:.0f}%" for v in g["pct"]], textposition="outside",
        textfont=dict(color=INK, size=12), cliponaxis=False,
        customdata=g[["won", "matches"]],
        hovertemplate=(side + " · %{x}: <b>won %{y:.0f}%</b><br>%{customdata[0]} of "
                       "%{customdata[1]} matches<extra></extra>"),
    ))
fig.add_hline(y=50, line=dict(color=MUTED, width=1, dash="dot"))
base_layout(fig, height=340, y_title="Won")
fig.update_layout(barmode="group", bargap=0.35)
fig.update_yaxes(range=[0, 110], ticksuffix="%", dtick=25)
home_a = ha[(ha["side"] == name_a) & (ha["where"] == "Home")]
away_a = ha[(ha["side"] == name_a) & (ha["where"] == "Away")]
takeaway = None
if not home_a.empty and not away_a.empty:
    takeaway = (f"{name_a} win <strong>{home_a['pct'].iloc[0]:.0f}%</strong> at home "
                f"against {name_b}, and <strong>{away_a['pct'].iloc[0]:.0f}%</strong> away.")
show(fig, key="riv_home", takeaway=takeaway,
     table=ha.round(1).rename(columns={"side": "Side", "where": "Where",
                                       "matches": "Matches", "won": "Won", "pct": "Won %"}))

# ---- star players -------------------------------------------------------------
rule()
section("The stars of this rivalry")
st.caption(f"Top {TOP_PLAYERS} run-scorers and wicket-takers in matches between the two "
           "sides, all formats in view together. Bar colour shows which side they play for.")
c1, c2 = st.columns(2, gap="large")


def _player_bars(df: pd.DataFrame, value: str, label: str, key: str, note: str) -> None:
    shown = df.iloc[::-1]
    fig = go.Figure(go.Bar(
        y=shown["player"], x=shown[value], orientation="h", showlegend=False,
        marker=dict(color=[SIDE_A if t == name_a else SIDE_B for t in shown["team"]],
                    line=dict(color=SURFACE, width=1)),
        text=[f"{int(v):,}" for v in shown[value]], textposition="outside",
        textfont=dict(color=INK, size=11), cliponaxis=False,
        customdata=shown[["team", "innings"]],
        hovertemplate=("%{y} (%{customdata[0]}): <b>%{x:,} " + label + "</b> in "
                       "%{customdata[1]} innings<extra></extra>"),
    ))
    base_layout(fig, height=60 + 34 * len(shown), x_title=label.capitalize(), legend=False)
    fig.update_xaxes(range=[0, float(shown[value].max()) * 1.2], tickformat=",d")
    fig.update_yaxes(showgrid=False, tickfont=dict(size=11, color=INK))
    top = df.iloc[0]
    show(fig, key=key, takeaway=f"<strong>{top['player']}</strong> ({top['team']}): "
                                f"{int(top[value]):,} {label}{note}.",
         table=df)


with c1:
    if batters.empty:
        st.info("No batting recorded.")
    else:
        _player_bars(batters, "runs", "runs", "riv_bat",
                     f" in {int(batters.iloc[0]['innings'])} innings")
with c2:
    if bowlers.empty or bowlers["wickets"].sum() == 0:
        st.info("No wickets recorded.")
    else:
        _player_bars(bowlers, "wickets", "wickets", "riv_bowl",
                     f" in {int(bowlers.iloc[0]['innings'])} innings")