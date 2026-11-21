"""Streamlit chat UI for the RAG telecom customer care chatbot.

Run:  .venv/bin/streamlit run app.py
"""
import time

import streamlit as st

import config
from assistant import Assistant
from chain import MissingAPIKey, log_event, new_id
from refund import USERS, rupees
from retriever import missing_collections

st.set_page_config(page_title="Telecom Customer Care", page_icon="📱", layout="centered")

if "session_id" not in st.session_state:
    st.session_state.session_id = new_id()
if "messages" not in st.session_state:
    st.session_state.messages = []  # [{role, content, sources?, id?}]
if "pending" not in st.session_state:
    st.session_state.pending = None
if "assistant" not in st.session_state:
    st.session_state.assistant = Assistant()  # holds the Refund Agent and simulated account data


def reset_conversation() -> None:
    """FR-48 + UI 11: clear history and any pending refund."""
    st.session_state.messages = []
    st.session_state.session_id = new_id()
    st.session_state.pending = None
    st.session_state.assistant.reset()


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


def render_steps(steps: list[str]) -> None:
    """Section 12: the workflow steps, without any model reasoning."""
    with st.expander("Agent steps"):
        st.code("\n".join(steps), language=None)


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
    st.subheader("Try the refund agent")
    for i, q in enumerate(config.REFUND_SAMPLES):
        if st.button(q, key=f"refund_sample_{i}", use_container_width=True):
            st.session_state.pending = q
    st.divider()
    # Stands in for the signed-in user; the chat never asks for a user ID (FR-15 to FR-17).
    user_ids = list(USERS)
    current = st.session_state.assistant.user_id
    chosen = st.selectbox("Demo account (signed-in user)", user_ids, index=user_ids.index(current),
                          format_func=lambda u: f"{USERS[u]['name']} ({u})")
    if chosen != current:
        st.session_state.assistant = Assistant(chosen)
        reset_conversation()
        st.rerun()
    with st.expander("Recharges on this account"):
        acct = st.session_state.assistant.tools.get_user_account(chosen)
        for r in acct["recharges"]:
            st.caption(f"{rupees(r['recharge_amount'])} · {r['recharge_age_days']} days ago · "
                       f"{r['recharge_status']} · {r['refund_status']}")
    if st.button("🗑️ Clear conversation", use_container_width=True):  # FR-04, FR-48
        reset_conversation()
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
        if m["role"] == "assistant" and m.get("steps"):
            render_steps(m["steps"])
        if m["role"] == "assistant" and m.get("id") and (m.get("sources") or m.get("steps")):
            render_feedback(m["id"])

# ---------------------------------------------------------------- refund confirmation (UI 11)
assistant = st.session_state.assistant
if assistant.pending_refund is not None:
    with st.container(border=True):
        st.markdown(f"**Refund eligible: {rupees(assistant.pending_refund)}**")
        st.write("Do you want to proceed with this refund?")
        c1, c2 = st.columns(2)
        # The buttons send the same words a user could type, through the same confirmation check.
        if c1.button("✅ Confirm Refund", type="primary", use_container_width=True):
            st.session_state.pending = "Yes, proceed"
        if c2.button("✖️ Cancel", use_container_width=True):
            st.session_state.pending = "Cancel"

# ---------------------------------------------------------------- new turn (FR-01)
typed = st.chat_input("Type your question…")
question = typed or st.session_state.pending
st.session_state.pending = None

if question:
    history = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]  # FR-46
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        message_id = new_id()
        t0 = time.time()
        sources, steps, intent = [], [], None
        try:
            with st.spinner("Working on it…"):
                turn = assistant.respond(question, history)
            intent, steps, sources = turn.intent, turn.steps, turn.sources
            if turn.tokens is not None:
                answer = st.write_stream(turn.tokens)  # FR-05: token-by-token streaming
            else:
                answer = turn.text
                st.markdown(answer)
        except MissingAPIKey as e:
            st.error(str(e))
            st.stop()
        except Exception as e:  # network / API errors
            answer = ("Sorry, I'm having trouble answering right now. Please try again, or call 611 "
                      "(free from your mobile) or use the MyTelecom app.")
            st.warning(answer)
            if "invalid_api_key" in repr(e) or "401" in repr(e):
                st.error("Operator note: Groq rejected the API key. Check GROQ_API_KEY in .env.")
            log_event({"type": "error", "session_id": st.session_state.session_id, "error": repr(e)})
        latency = round(time.time() - t0, 2)
        if sources:
            render_sources(sources)
        if steps and intent == "refund_request":
            render_steps(steps)
        if sources or (steps and intent == "refund_request"):
            render_feedback(message_id)

    st.session_state.messages.append({"role": "assistant", "content": answer, "sources": sources,
                                      "steps": steps if intent == "refund_request" else [],
                                      "id": message_id})
    log_event({"type": "answer", "session_id": st.session_state.session_id, "message_id": message_id,
               "intent": intent, "question": question, "answer": answer, "latency_s": latency,
               "steps": steps, "sources": [f"{s['source']}:{s['id']}" for s in sources]})
    st.rerun()  # redraw so the confirmation card shows (or disappears) under the latest message
