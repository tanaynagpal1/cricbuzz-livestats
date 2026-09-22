"""
SQL Analytics — the 25 analytics queries, each shown next to the SQL that produced it.

    level tabs      Beginner (Q1-8) · Intermediate (Q9-16) · Advanced (Q17-25)
    each query      the question it answers, the result table (searchable and
                    downloadable), and the exact SQL, read from sql/queries/
    run all 25      a health check that runs every query and reports rows
                    and time - useful before a demo

The queries run exactly as written in their .sql files, so the sidebar
filters do not apply on this page. The SQL shown is the file itself, via
utils/queries.py, so what is displayed and what runs can never differ.
"""

from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from utils import queries as Q
from utils.db_connection import DatabaseError
from utils.theme import card, page_header, rule, section, tiles

LEVELS = {"beginner": "Beginner", "intermediate": "Intermediate", "advanced": "Advanced"}


@st.cache_data(ttl=3600, show_spinner=False)
def run_timed(name: str) -> tuple[pd.DataFrame, float]:
    """Run one query file; return its result and how long it took (seconds).
    Cached for an hour, so switching between queries is instant after the
    first run."""
    start = time.perf_counter()
    df = Q.run(name)
    return df, time.perf_counter() - start


def show_query(q: Q.Query) -> None:
    """The question, the result and the SQL for one query."""
    card(q.label, f"<p style='margin:0'>{q.question or 'No question text in the file header.'}</p>")

    try:
        with st.spinner(f"Running {q.name}.sql…"):
            df, seconds = run_timed(q.name)
    except DatabaseError as exc:
        st.error(f"{q.name}.sql failed: {exc}")
        st.code(q.sql, language="sql")
        return

    result_tab, sql_tab = st.tabs([f"Result · {len(df):,} rows", "SQL"])
    with result_tab:
        st.caption(f"{len(df):,} rows × {len(df.columns)} columns · ran in {seconds:.2f} s "
                   f"(the first time; repeat views come from a one-hour cache).")
        search = st.text_input("Search the result", key=f"sql_search_{q.name}",
                               placeholder="Type to keep only rows containing this text")
        shown = df
        if search:
            mask = df.astype(str).apply(
                lambda col: col.str.contains(search, case=False, regex=False)).any(axis=1)
            shown = df[mask]
            st.caption(f"{len(shown):,} of {len(df):,} rows contain “{search}”.")
        st.dataframe(shown, hide_index=True, width="stretch", height=min(560, 40 + 35 * len(shown)))
        st.download_button("Download as CSV", data=df.to_csv(index=False).encode("utf-8"),
                           file_name=f"{q.name}.csv", mime="text/csv",
                           key=f"sql_dl_{q.name}")
    with sql_tab:
        st.caption(f"The file sql/queries/{q.name}.sql, exactly as it runs.")
        st.code(q.sql, language="sql", line_numbers=True, wrap_lines=True)


# --------------------------------------------------------------------------
# page
# --------------------------------------------------------------------------

page_header("SQL Analytics",
            "All 25 analytics queries, each shown alongside the SQL that produced it.",
            eyebrow="Analytics")

queries = Q.all_queries()
if not queries:
    st.error(f"No query files found in {Q.QUERY_DIR}. Each query should be a file "
             "named q01.sql … q25.sql in sql/queries/.")
    st.stop()

counts = {level: len(Q.by_tier(level)) for level in LEVELS}
tiles([
    ("Queries", f"{len(queries)}", "one .sql file each"),
    ("Beginner", f"{counts['beginner']}", "filters, joins, grouping"),
    ("Intermediate", f"{counts['intermediate']}", "multi-table joins, CTEs"),
    ("Advanced", f"{counts['advanced']}", "window functions, ranking"),
])
st.caption("These queries are the project's SQL deliverable and run exactly as written, so the "
           "sidebar filters do not apply on this page. Men's and women's cricket, and ODIs "
           "and T20Is, are included unless a query says otherwise.")

tabs = st.tabs([f"{name} · Q{min(q.number for q in Q.by_tier(level)):02d}–"
                f"Q{max(q.number for q in Q.by_tier(level)):02d}"
                for level, name in LEVELS.items() if counts[level]])
for tab, level in zip(tabs, [lv for lv in LEVELS if counts[lv]]):
    with tab:
        group = Q.by_tier(level)
        labels = {q.name: q.label for q in group}
        chosen = st.selectbox("Choose a query", options=list(labels),
                              format_func=labels.get, key=f"sql_pick_{level}")
        show_query(Q.get(chosen))

# --------------------------------------------------------------------------
# health check
# --------------------------------------------------------------------------

rule()
section("Run all 25")
st.caption("Runs every query file and reports how many rows it returned and how long it "
           "took. A quick check that the database and all 25 files are in order.")
if st.button("Run all 25 queries", key="sql_run_all"):
    rows = []
    progress = st.progress(0.0, text="Starting…")
    for i, q in enumerate(queries, start=1):
        progress.progress(i / len(queries), text=f"Running {q.name}.sql ({i} of {len(queries)})")
        try:
            df, seconds = run_timed(q.name)
            rows.append({"Query": q.label, "Level": LEVELS[q.tier], "Rows": len(df),
                         "Seconds": round(seconds, 2), "Status": "OK"})
        except DatabaseError as exc:
            rows.append({"Query": q.label, "Level": LEVELS[q.tier], "Rows": 0,
                         "Seconds": None, "Status": f"Failed: {exc}"})
    progress.empty()
    report = pd.DataFrame(rows)
    ok = int((report["Status"] == "OK").sum())
    (st.success if ok == len(report) else st.warning)(
        f"{ok} of {len(report)} queries ran successfully.")
    st.dataframe(report, hide_index=True, width="stretch")