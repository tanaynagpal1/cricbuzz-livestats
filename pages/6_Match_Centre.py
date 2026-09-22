"""
Match Centre — pick any of the archive's matches (ODI or T20I) and replay it.

    picker bar      jump to a World Cup final (ODI or T20), or search every match
    match header    result, toss, player of the match, venue
    3 charts        worm · Manhattan · partnership ladder

The match list respects the sidebar filters, so "India v Australia, 2015
onward" in the sidebar narrows the picker to exactly those matches.

Every chart comes with a one-line takeaway worked out from the data, and a
table view, so nothing is only readable by hovering.

ODIs and T20Is differ in length, so every format-specific number on this
page (the shaded phases, the checkpoint in the worm's takeaway, the tick
spacing) comes from the match being shown, never from a fixed "50 overs".
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from utils.charts import (INNINGS_COLOURS, INK, MUTED, SURFACE, WICKET,
                          base_layout, phase_bands, show)
from utils.db_connection import DatabaseError, run_query
from utils.filters import format_label, match_where
from utils.theme import card, page_header, rule, section, tiles


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def match_list(where: str, params: dict) -> pd.DataFrame:
    """Every match the sidebar filters allow, newest first, with a label."""
    df = run_query(f"""
        SELECT m.match_id, m.match_date, m.match_format, t1.team_display AS team1,
               t2.team_display AS team2, s.series_name, m.event_stage, v.city
        FROM fact_match m
        JOIN dim_team   t1 ON t1.team_id  = m.team1_id
        JOIN dim_team   t2 ON t2.team_id  = m.team2_id
        JOIN dim_series s  ON s.series_id = m.series_id
        JOIN dim_venue  v  ON v.venue_id  = m.venue_id
        WHERE {where}
        ORDER BY m.match_date DESC, m.match_id DESC
    """, params)
    stage = df["event_stage"].fillna("").map(lambda x: f"{x}, " if x else "")
    df["label"] = (df["match_date"].astype(str) + " · " + df["match_format"]
                   + " · " + df["team1"] + " v "
                   + df["team2"] + " · " + stage + df["series_name"]
                   + " · " + df["city"])
    return df


# Every name the ICC has used for its World Cups. The T20 event was called
# "World Twenty20" (2007-2012), then "World T20" (2014-2016), then
# "T20 World Cup" (2018 on); Cricsheet keeps the name used at the time.
# Qualifiers are deliberately NOT in this list: their "Final" is not a
# World Cup final.
WORLD_CUPS = (
    "ICC Cricket World Cup", "ICC Women's World Cup",                   # ODI
    "ICC World Twenty20", "ICC Women's World Twenty20",                 # T20, 2007-12
    "World T20", "Women's World T20",                                   # T20, 2014-16
    "ICC Men's T20 World Cup", "ICC Women's T20 World Cup",             # T20, 2018 on
)


@st.cache_data(ttl=3600, show_spinner=False)
def world_cup_finals(where: str, params: dict) -> pd.DataFrame:
    """World Cup finals (ODI and T20, men's and women's) inside the filters.

    Found from the data - stage = 'Final' in a World Cup series - rather
    than typed in, so a future final appears on its own.
    """
    return run_query(f"""
        SELECT m.match_id, EXTRACT(YEAR FROM m.match_date)::int AS year,
               m.gender, m.match_format,
               t1.team_display AS team1, t2.team_display AS team2
        FROM fact_match m
        JOIN dim_series s  ON s.series_id = m.series_id
        JOIN dim_team   t1 ON t1.team_id  = m.team1_id
        JOIN dim_team   t2 ON t2.team_id  = m.team2_id
        WHERE m.event_stage = 'Final'
          AND s.series_name = ANY(:world_cups)
          AND {where}
        ORDER BY m.match_date DESC, m.match_id DESC
    """, {**params, "world_cups": list(WORLD_CUPS)})


@st.cache_data(ttl=3600, show_spinner=False)
def match_header(match_id: int) -> dict:
    df = run_query("""
        SELECT m.match_date, m.match_format, m.victory_type, m.victory_margin, m.victory_method,
               m.toss_decision, m.event_stage, s.series_name,
               v.venue_display, v.city, v.country,
               w.team_display  AS winner,
               tw.team_display AS toss_winner,
               p.player_name   AS player_of_match
        FROM fact_match m
        JOIN dim_series s ON s.series_id = m.series_id
        JOIN dim_venue  v ON v.venue_id  = m.venue_id
        LEFT JOIN dim_team   w  ON w.team_id  = m.winner_id
        LEFT JOIN dim_team   tw ON tw.team_id = m.toss_winner_id
        LEFT JOIN dim_player p  ON p.player_id = m.player_of_match_id
        WHERE m.match_id = :mid
    """, {"mid": match_id})
    return df.iloc[0].to_dict()


@st.cache_data(ttl=3600, show_spinner=False)
def match_innings(match_id: int) -> pd.DataFrame:
    return run_query("""
        SELECT i.innings_no, t.team_display AS team, i.runs_total,
               i.wickets_lost, i.legal_balls, i.extras_total, i.fours,
               i.sixes, i.target_runs
        FROM fact_innings i
        JOIN dim_team t ON t.team_id = i.batting_team_id
        WHERE i.match_id = :mid
        ORDER BY i.innings_no
    """, {"mid": match_id})


@st.cache_data(ttl=3600, show_spinner=False)
def match_overs(match_id: int) -> pd.DataFrame:
    return run_query("""
        SELECT o.innings_no, o.over_no, o.runs, o.wickets, o.fours, o.sixes,
               o.extras, o.cum_runs, o.cum_wickets, o.phase,
               p.player_name AS bowler
        FROM fact_over o
        JOIN dim_player p ON p.player_id = o.bowler_id
        WHERE o.match_id = :mid
        ORDER BY o.innings_no, o.over_no
    """, {"mid": match_id})


@st.cache_data(ttl=3600, show_spinner=False)
def match_partnerships(match_id: int) -> pd.DataFrame:
    return run_query("""
        SELECT pt.innings_no, pt.wicket_no, pt.runs, pt.balls, pt.unbroken,
               p1.player_name AS batter_1, p2.player_name AS batter_2
        FROM fact_partnership pt
        JOIN dim_player p1 ON p1.player_id = pt.batter1_id
        JOIN dim_player p2 ON p2.player_id = pt.batter2_id
        WHERE pt.match_id = :mid
        ORDER BY pt.innings_no, pt.wicket_no
    """, {"mid": match_id})


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def overs_text(balls: int) -> str:
    """300 legal balls -> '50'; 227 -> '37.5' (cricket notation, not decimals)."""
    return f"{balls // 6}" if balls % 6 == 0 else f"{balls // 6}.{balls % 6}"


def score_text(row) -> str:
    wk = int(row["wickets_lost"])
    runs = int(row["runs_total"])
    return f"{runs}" if wk == 10 else f"{runs}/{wk}"


def result_text(h: dict) -> str:
    vt = h["victory_type"]
    method = f" ({h['victory_method']})" if h["victory_method"] else ""
    if vt in ("runs", "wickets") and h["winner"]:
        unit = vt if int(h["victory_margin"]) != 1 else vt[:-1]
        return f"{h['winner']} won by {int(h['victory_margin'])} {unit}{method}"
    if vt == "super over" and h["winner"]:
        return f"Tied — {h['winner']} won the super over"
    if vt == "tie":
        return f"Match tied{method}"
    return "No result"


# --------------------------------------------------------------------------
# page: heading and the picker bar
# --------------------------------------------------------------------------

page_header("Match Centre",
            f"Replay any {format_label()} match in the archive, over by over.",
            eyebrow="Analytics")

where, params = match_where("m")
try:
    matches = match_list(where, params)
    finals = world_cup_finals(where, params)
except DatabaseError as exc:
    st.error(str(exc))
    st.stop()

if matches.empty:
    st.info("No matches fit the filters in the sidebar. Widen them, or press Clear all.")
    st.stop()

labels = dict(zip(matches["match_id"], matches["label"]))


NONE = 0   # the "None" choice in the finals box (no real match_id is 0)


def _jump_to_final() -> None:
    # Runs before the page redraws: copy the chosen final into the match box.
    # Choosing "None" clears the match too, so no match is shown, and the
    # box keeps saying "None" so you can see what you picked.
    choice = st.session_state.get("mc_final")
    if choice in (None, NONE):
        st.session_state["mc_final"] = NONE
        st.session_state["mc_match"] = None
    else:
        st.session_state["mc_match"] = int(choice)


def _picked_from_search() -> None:
    # A match chosen in the search box is no longer "a final picked above",
    # so the finals box goes back to "None" instead of naming the old final.
    if st.session_state.get("mc_final") != st.session_state.get("mc_match"):
        st.session_state["mc_final"] = NONE


# First visit: start on the most recent World Cup final in view, else the
# newest match. Also when a filter change has removed the match on screen.
# But if the user chose "None" on purpose, leave the page empty.
current = st.session_state.get("mc_match", "first visit")
if current == "first visit" or (current is not None and current not in labels):
    if not finals.empty:
        st.session_state["mc_match"] = int(finals["match_id"].iloc[0])
        st.session_state["mc_final"] = int(finals["match_id"].iloc[0])   # box names it
    else:
        st.session_state["mc_match"] = int(matches["match_id"].iloc[0])
        st.session_state["mc_final"] = NONE

pick_left, pick_right = st.columns([1.3, 2.2], vertical_alignment="bottom")
with pick_left:
    final_labels = {NONE: "None"}
    final_labels.update({int(r.match_id): f"{r.year} · {'T20' if r.match_format == 'T20I' else 'ODI'}"
                                          f" · {r.team1} v {r.team2}"
                         for r in finals.itertuples()})
    # A final chosen earlier may have dropped out after a filter change.
    if st.session_state.get("mc_final") not in final_labels:
        st.session_state["mc_final"] = NONE
    st.selectbox(f"Jump to a World Cup final ({len(final_labels) - 1} in view)",
                 options=list(final_labels), format_func=final_labels.get,
                 key="mc_final", on_change=_jump_to_final,
                 disabled=len(final_labels) == 1)
with pick_right:
    st.selectbox(f"Or search all {len(matches):,} matches (type a team, year or ground)",
                 options=list(labels), format_func=labels.get, key="mc_match",
                 index=None, placeholder="Type a team, year or ground",
                 on_change=_picked_from_search)

if st.session_state.get("mc_match") is None:
    st.info("No match selected. Pick a World Cup final on the left, or search "
            "for any match on the right.")
    st.stop()

match_id = int(st.session_state["mc_match"])

# --------------------------------------------------------------------------
# match header
# --------------------------------------------------------------------------

h = match_header(match_id)
inn = match_innings(match_id)
overs = match_overs(match_id)
parts = match_partnerships(match_id)

stage = f"{h['event_stage']} · " if h["event_stage"] else ""
toss = (f"{h['toss_winner']} won the toss and chose to "
        f"{'bat' if h['toss_decision'] == 'bat' else 'bowl'}") if h["toss_winner"] else "Toss not recorded"
potm = f" · Player of the match: <strong>{h['player_of_match']}</strong>" if h["player_of_match"] else ""

card(f"{h['match_format']} · {stage}{h['series_name']} · {pd.Timestamp(h['match_date']):%d %b %Y}", f"""
  <p style="font-size:1.25rem;font-weight:800;color:{INK};margin:0 0 .35rem 0">{result_text(h)}</p>
  <p>{h['venue_display']}, {h['city']} · {toss}{potm}</p>
""")

tiles([
    (f"{r['team']} · innings {int(r['innings_no'])}", score_text(r),
     f"{overs_text(int(r['legal_balls']))} overs · {int(r['fours'])} fours · "
     f"{int(r['sixes'])} sixes · {int(r['extras_total'])} extras")
    for _, r in inn.iterrows()
])

if overs.empty:
    st.info("This match has no over-by-over record (it may have been abandoned "
            "before a ball was bowled).")
    st.stop()

team_of = dict(zip(inn["innings_no"].astype(int), inn["team"]))
last_over = int(overs["over_no"].max())

# Format-specific numbers, all taken from the match on screen.
is_t20 = h["match_format"] == "T20I"
phase_note = ("first 6 overs (powerplay) and last 5" if is_t20
              else "first 10 overs (powerplay) and last 10")
checkpoint_at = 10 if is_t20 else 30        # "after N overs" in the worm takeaway
tick = 2 if last_over <= 25 else 5          # x-axis spacing

# The worm draws both innings on one axis; shade the phases of the longer
# innings (the first, unless the chase ran longer after a rain reduction).
longest = int(overs.groupby("innings_no")["over_no"].max().idxmax())

# --------------------------------------------------------------------------
# chart 1: the worm
# --------------------------------------------------------------------------

rule()
section("The worm — how both innings grew")
st.caption("Running score at the end of each over. Dots mark the overs in which "
           f"wickets fell (bigger dot = more wickets). Shaded: {phase_note}.")

fig = go.Figure()
for n, g in overs.groupby("innings_no"):
    n = int(n)
    colour = INNINGS_COLOURS.get(n, MUTED)
    # Start every worm at 0 runs before the first over.
    x = [0, *g["over_no"]]
    y = [0, *g["cum_runs"]]
    fig.add_trace(go.Scatter(
        x=x, y=y, mode="lines", name=team_of.get(n, f"Innings {n}"),
        line=dict(color=colour, width=2.5, shape="linear"),
        hovertemplate="%{y} runs<extra>" + team_of.get(n, "") + "</extra>",
    ))
    w = g[g["wickets"] > 0]
    fig.add_trace(go.Scatter(
        x=w["over_no"], y=w["cum_runs"], mode="markers", showlegend=False,
        marker=dict(color=colour, size=7 + 3 * w["wickets"],
                    line=dict(color=SURFACE, width=2)),
        customdata=w[["wickets", "cum_wickets", "bowler"]],
        hovertemplate=("Over %{x}: %{customdata[0]} wicket(s) · "
                       "%{y}/%{customdata[1]} · bowler %{customdata[2]}<extra></extra>"),
    ))

# Direct labels at the end of each line: the final score. When both innings
# finish close together (a tight finish), nudge the labels apart vertically
# so they don't print on top of each other.
ends = overs.groupby("innings_no").tail(1).sort_values("cum_runs", ascending=False)
close = len(ends) == 2 and abs(int(ends["cum_runs"].iloc[0]) - int(ends["cum_runs"].iloc[1])) < 15
for rank, (_, end) in enumerate(ends.iterrows()):
    fig.add_annotation(x=end["over_no"], y=end["cum_runs"], xanchor="left",
                       yanchor="middle", xshift=8, showarrow=False,
                       yshift=(9 if rank == 0 else -9) if close else 0,
                       text=f"<b>{int(end['cum_runs'])}/{int(end['cum_wickets'])}</b>",
                       font=dict(color=INK, size=12))

target = inn.loc[inn["innings_no"] == 2, "target_runs"].dropna()
if not target.empty:
    fig.add_hline(y=float(target.iloc[0]), line=dict(color=MUTED, width=1),
                  annotation_text=f"Target {int(target.iloc[0])}",
                  annotation_position="top left",
                  annotation_font=dict(color=MUTED, size=11))

phase_bands(fig, overs[overs["innings_no"] == longest])
base_layout(fig, height=420, x_title="Over", y_title="Runs")
fig.update_layout(hovermode="x unified")
fig.update_xaxes(range=[0, last_over + (2 if is_t20 else 4)], dtick=tick)

# Takeaway: who was ahead at the same stage of their innings, and when.
wide = overs.pivot_table(index="over_no", columns="innings_no", values="cum_runs")
takeaway = None
if {1, 2}.issubset(wide.columns):
    both = wide.dropna()
    lead = (both[2] - both[1])
    # How often the side ahead changed (ignoring overs where they were level).
    sides = lead[lead != 0].apply(lambda v: v > 0)
    swaps = int((sides != sides.shift()).sum()) - 1 if len(sides) else 0
    t1, t2 = team_of.get(1, "Team 1"), team_of.get(2, "Team 2")
    checkpoint = min(checkpoint_at, int(both.index.max()))
    a, b = int(both.loc[checkpoint, 1]), int(both.loc[checkpoint, 2])
    ahead = t1 if a > b else t2 if b > a else None
    takeaway = (f"After {checkpoint} overs: {t1} {a}, {t2} {b}"
                + (f" — <strong>{ahead}</strong> ahead by {abs(a - b)}." if ahead else " — level."))
    if swaps > 0:
        takeaway += (f" Comparing the two innings over by over, the lead changed "
                     f"hands <strong>{swaps} time{'s' if swaps != 1 else ''}</strong>.")

worm_table = overs.pivot_table(index="over_no", columns="innings_no",
                               values="cum_runs").rename(columns=team_of).reset_index()
show(fig, takeaway=takeaway, key="worm",
     table=worm_table.rename(columns={"over_no": "Over"}))

# --------------------------------------------------------------------------
# chart 2: the Manhattan
# --------------------------------------------------------------------------

rule()
section("The Manhattan — runs in every over")
st.caption("One column per over, one panel per innings, same scale in both so the "
           f"heights compare directly. Red balls mark wickets. Shaded: {phase_note}.")

n_inn = int(overs["innings_no"].nunique())
fig = make_subplots(rows=n_inn, cols=1, shared_xaxes=True, shared_yaxes=True,
                    vertical_spacing=0.12,
                    subplot_titles=[team_of.get(n, f"Innings {n}")
                                    for n in sorted(overs["innings_no"].unique())])
y_top = int(overs["runs"].max()) + 5
for row, (n, g) in enumerate(overs.groupby("innings_no"), start=1):
    colour = INNINGS_COLOURS.get(int(n), MUTED)
    fig.add_trace(go.Bar(
        x=g["over_no"], y=g["runs"], marker=dict(color=colour, line=dict(width=0)),
        name=team_of.get(int(n), ""), showlegend=False,
        customdata=g[["bowler", "fours", "sixes", "extras", "wickets"]],
        hovertemplate=("Over %{x}: <b>%{y} runs</b><br>bowler %{customdata[0]}<br>"
                       "%{customdata[1]} fours · %{customdata[2]} sixes · "
                       "%{customdata[3]} extras · %{customdata[4]} wkt<extra></extra>"),
    ), row=row, col=1)
    w = g[g["wickets"] > 0]
    fig.add_trace(go.Scatter(
        x=w["over_no"], y=w["runs"] + 2.2, mode="markers", showlegend=False,
        marker=dict(color=WICKET, size=8 + 2 * (w["wickets"] - 1),
                    line=dict(color=SURFACE, width=2)),
        hovertemplate="Over %{x}: wicket<extra></extra>",
    ), row=row, col=1)
    phase_bands(fig, g, row=row, col=1)

base_layout(fig, height=250 * n_inn + 60, legend=False)
fig.update_yaxes(range=[0, y_top], title_text="Runs")
fig.update_xaxes(dtick=tick)
fig.update_xaxes(title_text="Over", row=n_inn, col=1)
fig.update_annotations(font=dict(size=13, color=INK), x=0, xanchor="left")

big = overs.loc[overs["runs"].idxmax()]
quiet = overs.groupby("innings_no")["runs"].apply(lambda s: int((s == 0).sum()))
takeaway = (f"Biggest over: <strong>{int(big['runs'])} runs</strong> — over "
            f"{int(big['over_no'])} of {team_of.get(int(big['innings_no']))}'s innings, "
            f"bowled by {big['bowler']}. Scoreless overs: "
            + ", ".join(f"{team_of.get(int(k))} {v}" for k, v in quiet.items()) + ".")

show(fig, takeaway=takeaway, key="manhattan",
     table=overs[["innings_no", "over_no", "bowler", "runs", "wickets",
                  "fours", "sixes", "extras"]]
     .assign(innings_no=lambda d: d["innings_no"].map(team_of))
     .rename(columns={"innings_no": "Batting", "over_no": "Over"}))

# --------------------------------------------------------------------------
# chart 3: the partnership ladder
# --------------------------------------------------------------------------

rule()
section("Partnership ladder — who built each innings")
st.caption("One bar per partnership, in order: 1st wicket at the top. The biggest "
           "stand in each innings is in full colour; the rest are lighter.")


def short_name(name: str) -> str:
    """'S Mandhana' -> 'Mandhana', 'N de Klerk' -> 'de Klerk', 'Shafali Verma' -> 'Verma'.

    Cricsheet names start with initials for most players. Drop the initials
    and keep everything after them; otherwise keep the surname.
    """
    bits = name.split()
    if len(bits) > 1 and bits[0].isupper() and len(bits[0]) <= 4:
        return " ".join(bits[1:])
    return bits[-1]


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


x_max = float(parts["runs"].max()) * 1.3 if not parts.empty else 10
cols = st.columns(n_inn, gap="large")
for col, (n, g) in zip(cols, parts.groupby("innings_no")):
    n = int(n)
    colour = INNINGS_COLOURS.get(n, MUTED)
    g = g.sort_values("wicket_no")
    best = g["runs"].idxmax()

    # Emphasis, not a rainbow: the biggest stand at full strength, the rest
    # the same colour but faded, so the eye lands on the one that mattered.
    opacity = [1.0 if i == best else 0.35 for i in g.index]
    surnames = g["batter_1"].map(short_name) + " & " + g["batter_2"].map(short_name)
    text = [f"{int(r)}{'*' if u else ''} ({int(b)})"
            for r, b, u in zip(g["runs"], g["balls"], g["unbroken"])]

    fig = go.Figure(go.Bar(
        y=[f"{int(w)}. {nm}" for w, nm in zip(g["wicket_no"], surnames)],
        x=g["runs"], orientation="h",
        marker=dict(color=colour, opacity=opacity, line=dict(width=0)),
        text=text, textposition="outside", cliponaxis=False,
        textfont=dict(color=INK, size=11),
        customdata=g[["batter_1", "batter_2", "balls"]],
        hovertemplate=("%{customdata[0]} & %{customdata[1]}<br>"
                       "<b>%{x} runs</b> off %{customdata[2]} balls<extra></extra>"),
    ))
    base_layout(fig, height=70 + 32 * len(g), title=team_of.get(n), legend=False)
    fig.update_layout(bargap=0.35)
    fig.update_yaxes(autorange="reversed", showgrid=False,
                     tickfont=dict(size=11, color=INK))
    fig.update_xaxes(showticklabels=False, showgrid=False, range=[0, x_max])

    top = g.loc[best]
    share = round(100 * top["runs"] / max(int(g["runs"].sum()), 1))
    with col:
        show(fig, key=f"ladder_{n}",
             takeaway=(f"Best stand: <strong>{top['batter_1']} & {top['batter_2']}</strong>, "
                       f"{int(top['runs'])} for the {ordinal(int(top['wicket_no']))} wicket "
                       f"— {share}% of the innings."),
             table=g[["wicket_no", "batter_1", "batter_2", "runs", "balls", "unbroken"]]
             .rename(columns={"wicket_no": "Wicket", "batter_1": "Batter",
                              "batter_2": "Partner", "runs": "Runs", "balls": "Balls",
                              "unbroken": "Unbroken"}))

st.caption("An asterisk marks an unbroken partnership. Partnership runs include "
           "extras; balls exclude wides.")