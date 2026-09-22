"""
Ask AI — a cricket chatbot that answers from the database when it can.

    database answers   Gemini writes one read-only SQL query, the app runs
                       it, and the answer is built only from the rows that
                       came back. The SQL and the table are shown under it.
    general answers    questions the archive cannot answer (Tests, IPL,
                       before 2002, rules...) are answered from the model's
                       own knowledge, and clearly labelled as such.
    memory             the conversation is kept for this browser session, so
                       follow-ups like "and in T20Is?" work. "New chat"
                       clears it; nothing is stored after the tab closes.

All the logic is in utils/chat_ai.py. The sidebar filters do not apply.
"""

from __future__ import annotations

import streamlit as st

from utils import chat_ai
from utils.db_connection import DatabaseError
from utils.theme import page_header

MAX_QUESTIONS = 30          # per session, to protect the free Gemini quota
SUGGESTIONS = [
    "Who has scored the most ODI runs for India since 2015?",
    "Best economy rate in T20Is for bowlers with 50+ wickets?",
    "How often do teams win after choosing to bowl first in ODIs?",
    "Who won the 2023 men's ODI World Cup final, and by how much?",
    "What is the lbw rule in cricket?",
]
BADGES = {
    "database": ":green-badge[:material/database: From the database]",
    "general": ":orange-badge[:material/lightbulb: General cricket knowledge — not from the database]",
    "error": ":red-badge[:material/error: Could not answer]",
}

page_header("Ask AI",
            "Ask about any ODI or T20 international since 2002 in plain English — "
            "answers come from the database, with the SQL shown.",
            eyebrow="Ask AI")

if not chat_ai.api_key():
    st.info("The assistant is switched off because no **GEMINI_API_KEY** is set. Add it to "
            "`.env` locally, or to the app's secrets on Streamlit Cloud, then restart.",
            icon=":material/key:")
    st.stop()

st.session_state.setdefault("ai_messages", [])
messages: list[dict] = st.session_state["ai_messages"]
asked = sum(1 for m in messages if m["role"] == "user")


def _new_chat() -> None:
    st.session_state["ai_messages"] = []
    st.session_state.pop("ai_suggest", None)          # or the old pick would re-ask


left, right = st.columns([5, 1], vertical_alignment="center")
left.caption("Read-only: the assistant can look at the data but never change it. "
             "The sidebar filters do not apply here."
             + (f" · Model: {chat_ai.model_name()}" if chat_ai.model_name() else "")
             + f" · {asked} of {MAX_QUESTIONS} questions used this session")
right.button("New chat", icon=":material/restart_alt:", on_click=_new_chat,
             disabled=not messages, width="stretch", key="ai_new")


def show_reply(m: dict, i: int) -> None:
    st.markdown(BADGES.get(m.get("source"), ""))
    st.markdown(m["content"])
    if m.get("sql"):
        with st.expander("How this was worked out: SQL and result"):
            st.code(m["sql"], language="sql", wrap_lines=True)
            data = m.get("data")
            if data is not None:
                st.caption(f"{len(data):,} rows" + (" (capped)" if len(data) >= chat_ai.MAX_ROWS else ""))
                st.dataframe(data, hide_index=True, width="stretch",
                             height=min(420, 40 + 35 * len(data)))
                st.download_button("Download as CSV", data.to_csv(index=False).encode("utf-8"),
                                   file_name="ask_ai_result.csv", mime="text/csv",
                                   key=f"ai_dl_{i}")


for i, m in enumerate(messages):
    with st.chat_message(m["role"], avatar=":material/person:" if m["role"] == "user"
                         else ":material/sports_cricket:"):
        if m["role"] == "user":
            st.markdown(m["content"])
        else:
            show_reply(m, i)

question = None
if not messages:
    st.markdown("**Try one of these, or type your own below:**")
    question = st.pills("Suggestions", SUGGESTIONS, label_visibility="collapsed",
                        key="ai_suggest")

typed = st.chat_input("Ask about players, teams, matches, grounds…",
                      disabled=asked >= MAX_QUESTIONS, key="ai_input")
question = typed or question
if asked >= MAX_QUESTIONS:
    st.caption("Question limit reached for this session. Press **New chat** to start again.")

if question:
    history = list(messages)
    messages.append({"role": "user", "content": question})
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(question)
    with st.chat_message("assistant", avatar=":material/sports_cricket:"):
        with st.spinner("Thinking…"):
            try:
                reply = chat_ai.ask(question, history)
                answer = {"role": "assistant", "content": reply.content,
                          "source": reply.source, "sql": reply.sql, "data": reply.data}
            except (chat_ai.ChatError, DatabaseError) as exc:
                answer = {"role": "assistant", "content": str(exc), "source": "error"}
        messages.append(answer)
    st.rerun()