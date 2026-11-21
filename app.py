"""Streamlit chat UI for the US Telecom Customer Care Assistant.

Customers sign in (or create an account), then chat. Accounts, each customer's simulated billing
account and all conversations are stored in the SQLite database in db.py.

Run:  .venv/bin/streamlit run app.py
"""
import time

import streamlit as st

import config
import db
from assistant import Assistant
from chain import MissingAPIKey, log_event, new_id
from refund import dollars
from retriever import missing_collections

st.set_page_config(page_title="US Telecom Customer Care", page_icon="📱", layout="centered")


@st.cache_resource(show_spinner=False)
def init_db() -> bool:
    db.init()
    return True


init_db()


# ---------------------------------------------------------------- session helpers

def start_new_chat() -> None:
    """FR-48 + UI 11: an empty conversation with no pending refund."""
    st.session_state.messages = []
    st.session_state.conversation_id = None
    st.session_state.session_id = new_id()
    st.session_state.pending = None
    if "assistant" in st.session_state:
        st.session_state.assistant.reset()


def sign_in(user: dict) -> None:
    store = db.DbAccountStore(user["id"])
    st.session_state.user = user
    st.session_state.assistant = Assistant(store.key, store=store)
    start_new_chat()


def sign_out() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def open_chat(conversation_id: int) -> None:
    user = st.session_state.user
    start_new_chat()
    st.session_state.conversation_id = conversation_id
    st.session_state.messages = db.get_messages(conversation_id, user["id"])
    for m in st.session_state.messages:  # show saved thumbs ratings
        if m.get("rating") and m.get("id"):
            st.session_state[f"fb_{m['id']}"] = 1 if m["rating"] == "up" else 0


# ---------------------------------------------------------------- sign in / create account

def render_auth() -> None:
    st.title("US Telecom Customer Care Assistant")
    st.caption("Sign in to chat with customer care. Your conversations are saved to your account.")
    sign_in_tab, sign_up_tab = st.tabs(["Sign in", "Create account"])
    with sign_in_tab:
        with st.form("sign_in"):
            email = st.text_input("Email", autocomplete="email")
            password = st.text_input("Password", type="password", autocomplete="current-password")
            if st.form_submit_button("Sign in", type="primary", use_container_width=True):
                try:
                    sign_in(db.authenticate(email, password))
                    st.rerun()
                except db.AuthError as e:
                    st.error(str(e))
    with sign_up_tab:
        with st.form("sign_up"):
            name = st.text_input("Name", autocomplete="name")
            email = st.text_input("Email", autocomplete="email")
            password = st.text_input(f"Password (at least {db.MIN_PASSWORD_LENGTH} characters)",
                                     type="password", autocomplete="new-password")
            confirm = st.text_input("Confirm password", type="password", autocomplete="new-password")
            if st.form_submit_button("Create account", type="primary", use_container_width=True):
                try:
                    if password != confirm:
                        raise db.AuthError("The passwords don't match.")
                    sign_in(db.create_user(email, name, password))
                    st.rerun()
                except db.AuthError as e:
                    st.error(str(e))


if "user" not in st.session_state:
    render_auth()
    st.stop()

user = st.session_state.user
assistant = st.session_state.assistant


# ---------------------------------------------------------------- rendering helpers

def render_sources(sources: list[dict]) -> None:
    """FR-13a: expandable list of every retrieved document."""
    with st.expander(f"Sources ({len(sources)})"):
        for s in sources:
            st.markdown(f"**{s['source']} · {s['id']}** — {s['title']}")
            st.caption(s["text"])


def on_feedback(message_id: str) -> None:
    value = st.session_state.get(f"fb_{message_id}")
    rating = None if value is None else ("up" if value == 1 else "down")
    db.set_rating(user["id"], message_id, rating)
    if rating:
        log_event({"type": "feedback", "session_id": st.session_state.session_id, "user_id": user["id"],
                   "message_id": message_id, "rating": rating})


def render_steps(steps: list[str]) -> None:
    """Section 12: the workflow steps, without any model reasoning."""
    with st.expander("Agent steps"):
        st.code("\n".join(steps), language=None)


def render_feedback(message_id: str) -> None:
    """FR-05a: thumbs up/down on every assistant answer, saved with the message."""
    st.feedback("thumbs", key=f"fb_{message_id}", on_change=on_feedback, args=(message_id,))


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("📱 Customer Care")
    st.caption(f"Signed in as **{user['name']}** ({user['email']})")
    if st.button("➕ New chat", type="primary", use_container_width=True):
        start_new_chat()
        st.rerun()

    st.subheader("Your chats")
    chats = db.list_conversations(user["id"])
    if not chats:
        st.caption("No saved chats yet.")
    for c in chats:
        current = c["id"] == st.session_state.conversation_id
        if st.button(c["title"], key=f"chat_{c['id']}", use_container_width=True,
                     type="secondary" if not current else "tertiary", disabled=current):
            open_chat(c["id"])
            st.rerun()
    if st.session_state.conversation_id is not None:
        if st.button("🗑️ Delete this chat", use_container_width=True):
            db.delete_conversation(st.session_state.conversation_id, user["id"])
            start_new_chat()
            st.rerun()

    st.divider()
    with st.expander("Try a sample question", expanded=not st.session_state.messages):
        for i, q in enumerate(config.SAMPLE_QUESTIONS):  # FR-02
            if st.button(q, key=f"sample_{i}", use_container_width=True):
                st.session_state.pending = q
    with st.expander("Try the refund agent"):
        for i, q in enumerate(config.REFUND_SAMPLES):
            if st.button(q, key=f"refund_sample_{i}", use_container_width=True):
                st.session_state.pending = q

    with st.expander("Your account"):
        acct = assistant.tools.get_user_account(assistant.user_id)
        st.caption(f"Plan: {acct['plan']} · Bill credit balance: {dollars(acct['bill_credit_balance'])}")
        st.caption("Recent recharges (simulated):")
        for r in acct["recharges"]:
            st.caption(f"{dollars(r['recharge_amount'])} · {r['recharge_age_days']} days ago · "
                       f"{r['recharge_status']} · {r['refund_status']}")
        with st.form("change_password", clear_on_submit=True):
            st.markdown("**Change password**")
            current_pw = st.text_input("Current password", type="password", autocomplete="current-password")
            new_pw = st.text_input("New password", type="password", autocomplete="new-password")
            if st.form_submit_button("Update password", use_container_width=True):
                try:
                    db.change_password(user["id"], current_pw, new_pw)
                    st.success("Password updated.")
                except db.AuthError as e:
                    st.error(str(e))
    if st.button("Sign out", use_container_width=True):
        sign_out()
        st.rerun()
    st.caption("Need a person? Call **611** (free from your mobile) or use the MyTelecom app.")

st.title("US Telecom Customer Care Assistant")


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
    st.info(f"Hi {user['name']}! Ask me about mobile data, bills, SIM/eSIM, roaming, calls or the MyTelecom "
            "app. I can also help with refunds on your recent recharges.")

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
if assistant.pending_refund is not None:
    amount = dollars(assistant.pending_refund)
    with st.container(border=True):
        if assistant.agent.state == "awaiting_refund_method":
            st.markdown(f"**Refund request for Support review: {amount}**")
            st.write("How would you prefer to receive it if it's approved?")
        else:
            st.markdown(f"**Refund eligible: {amount}**")
            st.write("Do you want to proceed with this refund? Choose how to receive it.")
        c1, c2, c3 = st.columns(3)
        # The buttons send the same words a user could type, through the same confirmation check.
        if c1.button("💳 Refund to original payment", type="primary", use_container_width=True):
            st.session_state.pending = "Refund to original payment"
        if c2.button("🧾 Credit to future bills", use_container_width=True):
            st.session_state.pending = "Credit to future bills"
        if c3.button("✖️ Cancel", use_container_width=True):
            st.session_state.pending = "Cancel"

# ---------------------------------------------------------------- new turn (FR-01)
typed = st.chat_input("Type your question…")
question = typed or st.session_state.pending
st.session_state.pending = None

if question:
    history = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]  # FR-46
    if st.session_state.conversation_id is None:
        st.session_state.conversation_id = db.create_conversation(user["id"], question)
    conversation_id = st.session_state.conversation_id
    db.add_message(conversation_id, user["id"], "user", question)
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
            log_event({"type": "error", "session_id": st.session_state.session_id, "user_id": user["id"],
                       "error": repr(e)})
        latency = round(time.time() - t0, 2)

    shown_steps = steps if intent == "refund_request" else []
    db.add_message(conversation_id, user["id"], "assistant", answer, message_key=message_id, intent=intent,
                   sources=sources, steps=shown_steps)
    st.session_state.messages.append({"role": "assistant", "content": answer, "sources": sources,
                                      "steps": shown_steps, "id": message_id, "intent": intent})
    log_event({"type": "answer", "session_id": st.session_state.session_id, "user_id": user["id"],
               "conversation_id": conversation_id, "message_id": message_id, "intent": intent,
               "question": question, "answer": answer, "latency_s": latency,
               "steps": steps, "sources": [f"{s['source']}:{s['id']}" for s in sources]})
    st.rerun()  # redraw: saved message with feedback, chat list, and the confirmation card if any
