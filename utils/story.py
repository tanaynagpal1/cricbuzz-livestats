"""
Shared pieces for The Story page: settings, the "full members only" rule,
and small chart helpers.

The page itself is pages/7_The_Story.py. Each chapter lives in its own file
(utils/story_ch1.py, story_ch2.py, ...) so a chapter can be changed or added
without touching the others.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go

from utils.charts import INK

# --------------------------------------------------------------------------
# settings used by more than one chapter
# --------------------------------------------------------------------------

# One colour per format, the same on every chart. Checked with the palette
# validator: the pair is colour-blind safe; the gold is light on white, so
# every chart also carries direct labels or a legend, and a table view.
FORMAT_COLOURS = {"ODI": "#1F7A4A", "T20I": "#B8913F"}

# "The one that matters" and "for comparison": emphasis, not a rainbow.
EMPHASIS = "#1F7A4A"
CONTEXT_GREY = "#9AA59F"

# A year needs this many matches before it is plotted.
MIN_MATCHES = 20

# The 12 ICC full members. dim_team.team_name has no "Women" in it, so the
# same list covers the men's and the women's sides.
FULL_MEMBERS = ("Afghanistan", "Australia", "Bangladesh", "England", "India",
                "Ireland", "New Zealand", "Pakistan", "South Africa",
                "Sri Lanka", "West Indies", "Zimbabwe")


@dataclass(frozen=True)
class Ctx:
    """Everything a chapter needs to know about the current view."""
    where: str            # SQL condition on fact_match m (sidebar filters)
    params: dict          # its parameters
    full_members: bool    # the page's "Full members only" switch
    scope_note: str       # "all internationals" / "full members only"
    who: str              # "Men's", "Women's" or a note that both are mixed

    @property
    def footer(self) -> str:
        """The line that ends every caption: which matches are counted."""
        return f"{self.scope_note.capitalize()} · {self.who}."


def scope(where: str, full_members: bool) -> str:
    """The sidebar filters, plus the full-members rule when it is on."""
    if not full_members:
        return where
    return (f"{where} AND m.team1_id IN (SELECT team_id FROM dim_team WHERE team_name = ANY(:fm)) "
            f"AND m.team2_id IN (SELECT team_id FROM dim_team WHERE team_name = ANY(:fm))")


def scope_params(params: dict) -> dict:
    """The sidebar parameters plus the full-members list."""
    return {**params, "fm": list(FULL_MEMBERS)}


# --------------------------------------------------------------------------
# chart helpers
# --------------------------------------------------------------------------

def end_labels(fig: go.Figure, ends: list[tuple[float, float, str]]) -> None:
    """Direct labels at the end of each line, in ink colour (never the series
    colour). When two lines finish close together, the labels are pushed
    apart so they never print on top of each other."""
    ends = sorted(ends, key=lambda e: e[1], reverse=True)
    close = False
    if len(ends) == 2:
        values = [e[1] for e in ends]
        top = max(abs(v) for v in values) or 1
        close = (max(values) - min(values)) < 0.08 * top
    for rank, (x, y, text) in enumerate(ends):
        fig.add_annotation(x=x, y=y, text=f"<b>{text}</b>", showarrow=False,
                           xanchor="left", yanchor="middle", xshift=10,
                           yshift=(10 if rank == 0 else -10) if close else 0,
                           font=dict(color=INK, size=12))


def year_axis(fig: go.Figure, years: pd.Series) -> None:
    """Year axis that stops at the last year with data, with room on the
    right for the end labels."""
    fig.update_xaxes(dtick=2, range=[years.min() - 0.5, years.max() + 0.5])
    fig.update_layout(margin=dict(r=90))


def panel_titles_left(fig: go.Figure, titles: list[str]) -> None:
    """Left-align subplot titles ("ODI", "T20I") over their own panel."""
    fig.update_annotations(font=dict(size=13, color=INK))
    for i, ann in enumerate(a for a in fig.layout.annotations if a.text in titles):
        ann.update(xanchor="left",
                   x=fig.layout["xaxis" + ("" if i == 0 else str(i + 1))].domain[0])


def legend_below(fig: go.Figure, y: float = -0.12) -> None:
    """Legend under the chart, so it never collides with panel titles."""
    fig.update_layout(margin=dict(t=40, b=10),
                      legend=dict(orientation="h", y=y, yanchor="top", x=0))


def first_last(g: pd.DataFrame, col: str, n: int = 3) -> tuple[float, float, str, str]:
    """Average of `col` over the first n and the last n years in `g`."""
    g = g.sort_values("year")
    a, b = g.head(n), g.tail(n)

    def span(d: pd.DataFrame) -> str:
        if len(d) == 1:
            return str(d["year"].iloc[0])
        return f"{d['year'].min()}–{str(d['year'].max())[-2:]}"

    return float(a[col].mean()), float(b[col].mean()), span(a), span(b)