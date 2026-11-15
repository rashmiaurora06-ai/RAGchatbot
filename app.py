"""Streamlit chat UI for the RAG telecom customer care chatbot.

Run:  .venv/bin/streamlit run app.py
"""
import time

import streamlit as st

import config
from chain import MissingAPIKey, log_event, new_id, stream_answer
from retriever import missing_collections

st.set_page_config(page_title="Telecom Customer Care", page_icon="📱", layout="centered")

if "session_id" not in st.session_state:
    st.session_state.session_id = new_id()
if "messages" not in st.session_state:
    st.session_state.messages = []  # [{role, content, sources?, id?}]
if "pending" not in st.session_state:
    st.session_state.pending = None


def render_sources(sources: list[dict]) -> None:
    """FR-13a: expandable list of every retrieved document."""
    with st.expander(f"Sources ({len(sources)})"):
        for s in sources:
            st.markdown(f"**{s['source']} · {s['id']}** — {s['title']}")
            st.caption(s["text"])


def on_feedback(message_id: str) -> None:
    value = st.session_state.get(f"fb_{message_id}")
    if value is not None:
        log_event({"type": "feedback", "session_id": st.session_state.session_id,
                   "message_id": message_id, "rating": "up" if value == 1 else "down"})


def render_feedback(message_id: str) -> None:
    """FR-05a: thumbs up/down on every assistant answer, written to the interaction log."""
    st.feedback("thumbs", key=f"fb_{message_id}", on_change=on_feedback, args=(message_id,))


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("📱 Customer Care")
    st.caption("Answers come only from our FAQ, past support cases and technical guides.")
    st.subheader("Try a sample question")
    for i, q in enumerate(config.SAMPLE_QUESTIONS):  # FR-02
        if st.button(q, key=f"sample_{i}", use_container_width=True):
            st.session_state.pending = q
    st.divider()
    if st.button("🗑️ Clear conversation", use_container_width=True):  # FR-04
        st.session_state.messages = []
        st.session_state.session_id = new_id()
        st.session_state.pending = None
        st.rerun()
    st.caption("Need a person? Call **611** (free from your mobile) or use the MyTelecom app.")

st.title("Telecom Customer Care Assistant")

@st.cache_resource(show_spinner=False)
def build_knowledge_base(names: tuple[str, ...]) -> None:
    """Build any empty collections from data/. Runs once per server process, so a fresh
    deploy (where chroma_store/ isn't in git) works without running ingest_all.py by hand."""
    import ingest_faq
    import ingest_guides
    import ingest_tickets

    ingesters = {"faq": ingest_faq.main, "tickets": ingest_tickets.main, "guides": ingest_guides.main}
    for name in names:
        ingesters[name]()


missing = missing_collections()
if missing:
    with st.spinner("Setting up the knowledge base for the first time. This takes a minute or two…"):
        try:
            build_knowledge_base(tuple(missing))
        except Exception as e:  # noqa: BLE001 - show the operator what went wrong
            st.error(f"Couldn't build the knowledge base: {e}")
            st.stop()
    missing = missing_collections()
    if missing:
        st.error(f"The knowledge base is still empty ({', '.join(missing)}). Run `python ingest_all.py`.")
        st.stop()

if not st.session_state.messages:
    st.info("Hi! Ask me about mobile data, bills, SIM/eSIM, roaming, calls or the MyTelecom app. "
            "I can't see your account details.")

# ---------------------------------------------------------------- history (FR-03)
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m["role"] == "assistant" and m.get("sources"):
            render_sources(m["sources"])
            render_feedback(m["id"])

# ---------------------------------------------------------------- new turn (FR-01)
typed = st.chat_input("Type your question…")
question = typed or st.session_state.pending
st.session_state.pending = None

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        message_id = new_id()
        t0 = time.time()
        try:
            with st.spinner("Searching our help content…"):
                sources, tokens = stream_answer(question)
            answer = st.write_stream(tokens)  # FR-05: token-by-token streaming
        except MissingAPIKey as e:
            st.error(str(e))
            st.stop()
        except Exception as e:  # network / API errors
            answer = ("Sorry, I'm having trouble answering right now. Please try again, or call 611 "
                      "(free from your mobile) or use the MyTelecom app.")
            st.warning(answer)
            if "invalid_api_key" in repr(e) or "401" in repr(e):
                st.error("Operator note: Groq rejected the API key. Check GROQ_API_KEY in .env.")
            sources = []
            log_event({"type": "error", "session_id": st.session_state.session_id, "error": repr(e)})
        latency = round(time.time() - t0, 2)
        if sources:
            render_sources(sources)
            render_feedback(message_id)

    st.session_state.messages.append({"role": "assistant", "content": answer, "sources": sources,
                                      "id": message_id})
    log_event({"type": "answer", "session_id": st.session_state.session_id, "message_id": message_id,
               "question": question, "answer": answer, "latency_s": latency,
               "sources": [f"{s['source']}:{s['id']}" for s in sources]})
