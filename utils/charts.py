"""
Shared chart settings, so every chart in the app looks like one family.

Rules applied here once, instead of in every chart:
  * one y-axis per chart, never two
  * thin marks: 2px lines, bars no wider than they need to be
  * hairline, recessive gridlines; text in ink colours, never series colours
  * a legend whenever there are two or more series
  * hover shows every series at once (the crosshair finds the over)

Colours were checked with the dataviz palette validator (lightness, chroma,
colour-blind separation). The gold is lighter than ideal against white, so
every chart that uses it also carries direct labels and a table view.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Team colours for a match: whoever bats first is always green, whoever bats
# second is always gold - on every chart on the page, so a team keeps its
# colour as you scroll.
BAT_FIRST = "#1F7A4A"
BAT_SECOND = "#B8913F"
INNINGS_COLOURS = {1: BAT_FIRST, 2: BAT_SECOND}

WICKET = "#8D2B28"        # the ball red, used only for "a wicket fell here"
INK = "#132018"
INK_2 = "#3E4C44"
MUTED = "#728078"
GRID = "#E4E8E4"
SURFACE = "#FFFFFF"
PHASE_SHADE = "rgba(19,32,24,0.045)"   # the faint band behind powerplay / last 10

FONT = "Inter, Segoe UI, system-ui, sans-serif"


def base_layout(fig: go.Figure, *, height: int = 380, title: str | None = None,
                x_title: str | None = None, y_title: str | None = None,
                legend: bool = True) -> go.Figure:
    """Apply the house style to a figure. Returns the same figure."""
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=16, t=48 if title else 16, b=8),

# Always pass a title object, with empty text when there is no title.
# Passing None makes Plotly print the word "undefined" in the corner.
        title=dict(text=title or "", x=0, xanchor="left",
                   font=dict(size=15, color=INK, family=FONT)),
        font=dict(family=FONT, size=12, color=INK_2),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left",
                    x=0, font=dict(size=12, color=INK_2), bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor="#FFFFFF", bordercolor=GRID,
                        font=dict(family=FONT, size=12, color=INK)),
        bargap=0.28,
    )
    axis = dict(showline=False, zeroline=False, gridcolor=GRID, gridwidth=1,
                tickfont=dict(size=11, color=MUTED),
                title_font=dict(size=12, color=MUTED))
    fig.update_xaxes(**axis, title_text=x_title)
    fig.update_yaxes(**axis, title_text=y_title, separatethousands=True)
    return fig


def show(fig: go.Figure, *, table: pd.DataFrame | None = None,
         takeaway: str | None = None, key: str | None = None) -> None:
    """Draw a chart with its one-line takeaway and an optional table view.

    The table view means no value is ever reachable ONLY by hovering.
    """
    st.plotly_chart(fig, width="stretch", key=key,
                    config={"displayModeBar": False, "responsive": True})
    if takeaway:
        st.markdown(f'<div class="cb-takeaway">{takeaway}</div>',
                    unsafe_allow_html=True)
    if table is not None:
        with st.expander("Show as table"):
            st.dataframe(table, hide_index=True, width="stretch")


def phase_bands(fig: go.Figure, overs: pd.DataFrame, row: int | None = None,
                col: int | None = None) -> None:
    """Shade the powerplay and the death overs, lightly.

    `overs` is the over-by-over rows of ONE innings (columns over_no and
    phase), straight from fact_over. The bands are read from the phase the
    database already stored, so they are always the same boundaries the
    SQL uses: first 10 and last 10 overs in an ODI, first 6 and last 5 in a
    T20I, and correctly shorter in a rain-reduced match.
    """
    kw = {} if row is None else {"row": row, "col": col}
    for phase in ("powerplay", "death"):
        span = overs.loc[overs["phase"] == phase, "over_no"]
        if not span.empty:
            fig.add_vrect(x0=int(span.min()) - 0.5, x1=int(span.max()) + 0.5,
                          fillcolor=PHASE_SHADE, line_width=0, layer="below", **kw)