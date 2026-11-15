"""The NovaCell support assistant: route -> retrieve -> answer -> verify -> escalate.

Flow for each customer message (PRD §4):
  1. Mask PII and run deterministic safety checks (emergency, fraud, "human please").
  2. Route: rewrite follow-ups into a standalone question and classify theme/intent
     (Claude Haiku 5.5, or keyword heuristics when no API key is configured).
  3. Retrieve from FAQ + resolved tickets + guide; refuse if confidence is too low.
  4. Generate a grounded answer with citations (Claude Opus 5.5, structured output).
  5. Verify: citations must be real, every number must appear in the cited sources,
     no promised refunds/credits. Retry once, then fall back to "I'm not sure".
  6. Decide whether to offer or perform a handoff, and log gaps/turns.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import uuid
from dataclasses import dataclass, field

import anthropic

from . import config, store
from .guardrails import detect_signals, makes_promise, mask_pii, unsupported_numbers
from .retrieval import Hit, get_index

log = logging.getLogger("novacell")

THEMES = ["data", "connectivity", "billing", "sim", "roaming", "voice", "device", "account", "other"]
INTENTS = ["general", "account_specific", "transactional", "complaint", "safety_fraud",
           "wants_human", "out_of_scope", "smalltalk"]

# Self-serve paths quoted verbatim from the FAQ, shown for account-specific questions (FR-5.3).
SELF_SERVE = {
    "data": ("Check your data balance: dial *123# or MyTelecom app > My Usage", "FAQ-1"),
    "billing": ("See every charge: MyTelecom > Billing > Download Bill (itemised PDF)", "FAQ-18"),
    "roaming": ("Turn roaming on: MyTelecom > Plan & Services > International Roaming", "FAQ-9"),
    "device": ("Request an unlock: MyTelecom > Device > Request Unlock", "FAQ-19"),
    "account": ("Contact options: call 611, app live chat 8am–10pm, or any store", "FAQ-25"),
}

WELCOME = (
    "Hi, I'm NovaCell's virtual assistant. I'm an AI, and I answer using NovaCell's official help "
    "content only. I can help with mobile data, bills and charges, SIM/eSIM activation, roaming, calls, "
    "and app questions.\n\nI can't see your account details (like your balance or bill) in this chat, and "
    "please don't share passwords, PINs or card numbers here. You can ask for a person at any time."
)
SUGGESTIONS = ["My mobile data is slow", "Why is my bill higher than usual?", "My eSIM won't activate",
               "I'm travelling to Japan next week", "My calls keep dropping", "I can't log in to the app"]

# ---------------------------------------------------------------- prompts

ROUTER_SYSTEM = """You classify messages sent to NovaCell's mobile-operator support chat.
Return JSON only. Fields:
- standalone_question: the customer's latest message rewritten so it makes sense without the earlier
  conversation (resolve "it", "that", "what about Japan?"). Keep the customer's meaning; don't add facts.
- theme: one of data, connectivity, billing, sim, roaming, voice, device, account, other.
- intent: general (a how/why/what question answerable from help content), account_specific (needs
  their own account data: balance, their bill, their plan status), transactional (wants NovaCell to
  do something: refund, plan change, unlock, new eSIM code), complaint, safety_fraud (unauthorised
  changes, hacked account, SIM swap, stolen phone), wants_human, out_of_scope (not about NovaCell mobile
  service), smalltalk (greetings, thanks).
- frustrated: true if the customer sounds angry or fed up."""

ROUTER_SCHEMA = {
    "type": "object",
    "properties": {
        "standalone_question": {"type": "string"},
        "theme": {"type": "string", "enum": THEMES},
        "intent": {"type": "string", "enum": INTENTS},
        "frustrated": {"type": "boolean"},
    },
    "required": ["standalone_question", "theme", "intent", "frustrated"],
    "additionalProperties": False,
}

ANSWER_SYSTEM = """You are NovaCell's customer support assistant, answering mobile customers in a chat window.

GROUNDING (most important)
- Use ONLY the numbered SOURCES provided in the message. Never use outside knowledge about telecoms,
  other carriers, prices, or policies. If the sources don't contain the answer, set answer_status to
  "not_in_sources" and say briefly that you don't have that information.
- Every price, fee, speed, time, percentage, phone number and menu path you write must appear in a
  source you cite. Copy numbers exactly. Never estimate or round.
- If sources conflict, follow the higher-priority one (FAQ > Guide > Past case) and leave out the
  conflicting detail rather than presenting both.
- "Past case" sources describe what NovaCell staff did for one customer. Use them to explain likely
  causes and what NovaCell support can do, never as something the customer can do themselves and never
  as a guaranteed outcome. Do not mention case numbers, other customers, or internal system names
  (HLR, BSS, RNC, IMS, CDR, portal back-ends).

WHAT YOU CAN'T DO
- You cannot see or change the customer's account. For questions about their own balance, bill,
  plan or settings: (1) say plainly you can't see their account from this chat, (2) give the general
  answer from the sources, (3) point to the self-serve path in the sources or offer a NovaCell agent.
- Never promise or imply refunds, credits, compensation, waivers or exceptions. You may say a NovaCell
  agent can review it.
- Never ask for passwords, PINs, PUKs, full card numbers, SIM serials or date of birth.
- When the fix needs NovaCell staff (re-provisioning a SIM, a new eSIM code, removing call barring,
  a network investigation, account changes), set needs_staff_action true and say a NovaCell agent can
  do it.

STYLE
- Plain, friendly language at about an 8th-grade reading level. Short: usually under 120 words.
- Numbered steps for troubleshooting. Explain jargon (e.g. "APN (your phone's mobile data settings)").
- Don't write "according to the sources" or show source IDs in the answer text; list them in citations.
- If something depends on the plan, say so and tell them where to check.
- Ask at most one clarifying question, and only if the question is too vague to answer.

Return JSON with: answer (customer-facing text), citations (IDs of the sources you used, e.g. "FAQ-9"),
answer_status ("answered" | "partial" | "not_in_sources"), needs_staff_action (boolean)."""

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
        "answer_status": {"type": "string", "enum": ["answered", "partial", "not_in_sources"]},
        "needs_staff_action": {"type": "boolean"},
    },
    "required": ["answer", "citations", "answer_status", "needs_staff_action"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------- session

@dataclass
class Session:
    id: str
    history: list[dict] = field(default_factory=list)  # [{"role": "user"|"assistant", "content": str}]
    unsure_streak: int = 0
    thumbs_down: int = 0
    last_theme: str = "other"
    last_intent: str = "general"
    suggested: list[dict] = field(default_factory=list)  # citations shown so far
    handoff_ref: str | None = None


SESSIONS: dict[str, Session] = {}


def get_session(session_id: str | None) -> Session:
    if session_id and session_id in SESSIONS:
        return SESSIONS[session_id]
    s = Session(id=session_id or uuid.uuid4().hex)
    SESSIONS[s.id] = s
    return s


# ---------------------------------------------------------------- Claude client

def _client() -> anthropic.Anthropic | None:
    if os.environ.get("NOVACELL_OFFLINE") == "1":
        return None
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return None
    return anthropic.Anthropic(max_retries=2, timeout=30.0)


CLIENT = _client()


def mode() -> str:
    return "claude" if CLIENT else "offline"


def _first_text(resp) -> str:
    for b in resp.content:
        if b.type == "text":
            return b.text
    raise ValueError("no text block in response")


def _route_llm(session: Session, msg: str) -> dict:
    convo = "\n".join(f"{t['role'].upper()}: {t['content']}" for t in session.history[-6:])
    resp = CLIENT.messages.create(
        model=config.ROUTER_MODEL,
        max_tokens=1024,
        system=ROUTER_SYSTEM,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": ROUTER_SCHEMA}},
        messages=[{"role": "user", "content": f"Conversation so far:\n{convo or '(none)'}\n\nLatest message: {msg}"}],
    )
    if resp.stop_reason == "refusal":
        raise ValueError("router refused")
    return json.loads(_first_text(resp))


_THEME_WORDS = {
    "roaming": ["roam", "abroad", "travel", "trip", "overseas", "japan", "europe", "eu ", "country"],
    "billing": ["bill", "charge", "payment", "pay ", "autopay", "invoice", "price", "cost", "refund"],
    "sim": ["sim", "esim", "e-sim", "port", "activation", "activate", "qr"],
    "voice": ["call", "voicemail", "volte", "wi-fi calling", "wifi calling", "echo", "spam"],
    "data": ["data", "internet", "slow", "speed", "hotspot", "4g", "5g", "lte", "mbps"],
    "connectivity": ["signal", "coverage", "outage", "no service", "network"],
    "account": ["log in", "login", "password", "app", "account", "contact"],
    "device": ["unlock", "phone", "device", "handset"],
}


def _route_heuristic(session: Session, msg: str, sig: dict) -> dict:
    low = msg.lower()
    theme = next((t for t, ws in _THEME_WORDS.items() if any(w in low for w in ws)), None)
    standalone = msg
    if theme is None and session.last_theme != "other" and len(msg.split()) <= 6:
        theme = session.last_theme  # short follow-up like "what about Japan?"
        prev = next((t["content"] for t in reversed(session.history) if t["role"] == "user"), "")
        standalone = f"{prev} {msg}"
    intent = ("safety_fraud" if sig["fraud"] else "wants_human" if sig["wants_human"]
              else "complaint" if sig["complaint"] else "transactional" if sig["transactional"]
              else "account_specific" if sig["account_specific"] else "general")
    if intent == "general" and low.strip(" !.?") in {"hi", "hello", "hey", "thanks", "thank you", "ok", "bye"}:
        intent = "smalltalk"
    return {"standalone_question": standalone, "theme": theme or "other", "intent": intent,
            "frustrated": sig["frustrated"]}


def _sources_block(hits: list[Hit]) -> str:
    parts = []
    for h in hits:
        c = h.chunk
        kind = {"faq": "FAQ", "guide": "Guide", "ticket": "Past case"}[c.source]
        parts.append(f"[{c.id}] ({kind}; priority {config.SOURCE_PRIORITY[c.source]}) {c.title}\n{c.text}")
    return "\n\n".join(parts)


def _answer_llm(session: Session, question: str, route: dict, hits: list[Hit], extra_rule: str = "") -> dict:
    convo = "\n".join(f"{t['role'].upper()}: {t['content']}" for t in session.history[-6:])
    note = ""
    if route["intent"] == "account_specific":
        note = "\nNOTE: This is about the customer's own account, which you cannot see. Follow the 3-step pattern."
    elif route["intent"] == "transactional":
        note = "\nNOTE: The customer wants NovaCell to do something you can't do from chat. Explain and offer an agent."
    user = (f"SOURCES\n{_sources_block(hits)}\n\nCONVERSATION SO FAR\n{convo or '(none)'}\n\n"
            f"CUSTOMER QUESTION\n{question}{note}{extra_rule}")
    resp = CLIENT.beta.messages.create(
        model=config.ANSWER_MODEL,
        max_tokens=4096,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # re-run on a fallback model if the request is declined
        system=[{"type": "text", "text": ANSWER_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        output_config={"effort": config.ANSWER_EFFORT,
                       "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}},
        messages=[{"role": "user", "content": user}],
    )
    if resp.stop_reason == "refusal":
        return {"answer": "", "citations": [], "answer_status": "not_in_sources", "needs_staff_action": False}
    return json.loads(_first_text(resp))


def _answer_offline(question: str, route: dict, hits: list[Hit]) -> dict:
    """Degraded mode (no model available): return the best customer-facing source verbatim."""
    for h in hits:
        c = h.chunk
        if c.source == "faq":
            return {"answer": c.text.split("\nA: ", 1)[-1], "citations": [c.id],
                    "answer_status": "answered", "needs_staff_action": False}
        if c.source == "guide":
            return {"answer": c.text, "citations": [c.id], "answer_status": "partial",
                    "needs_staff_action": False}
    return {"answer": "", "citations": [], "answer_status": "not_in_sources", "needs_staff_action": False}


# ---------------------------------------------------------------- escalation

def live_chat_open(now: dt.datetime | None = None) -> bool:
    h = (now or dt.datetime.now()).hour
    return config.LIVE_CHAT_OPEN_HOUR <= h < config.LIVE_CHAT_CLOSE_HOUR


def create_handoff(session: Session, reason: str) -> dict:
    """FR-6.1/6.2: hand the full context to a person; route fraud to the security queue."""
    if session.handoff_ref:
        return {"ref": session.handoff_ref, "message": f"You're already in the queue (reference {session.handoff_ref})."}
    queue = "security" if session.last_intent == "safety_fraud" else session.last_theme
    is_open = live_chat_open()
    channel = "live_chat" if is_open else "callback"
    package = {
        "transcript": session.history,
        "theme": session.last_theme, "intent": session.last_intent, "queue": queue,
        "reason": reason, "sources_already_shown": session.suggested[-10:],
    }
    ref = store.log_handoff(session.id, reason, session.last_theme, session.last_intent, channel, package)
    session.handoff_ref = ref
    if is_open:
        msg = (f"I'm connecting you to a NovaCell agent now (reference {ref}). They'll see this conversation, "
               "so you won't need to repeat yourself.")
    else:
        msg = (f"Our live chat team is available 8am–10pm. I've created a request (reference {ref}) with this "
               "conversation attached, and an agent will contact you when the team is back. "
               "For urgent issues you can also call 611.")
    return {"ref": ref, "channel": channel, "queue": queue, "message": msg}


# ---------------------------------------------------------------- main entry

def _reply(session: Session, text: str, *, status: str, route: dict | None = None, citations=None,
           offer_handoff: str | None = None, handoff: dict | None = None, self_serve=None,
           related=None, confidence: float | None = None) -> dict:
    mid = uuid.uuid4().hex[:12]
    session.history.append({"role": "assistant", "content": text})
    meta = {"status": status, "route": route, "citations": [c["id"] for c in citations or []],
            "offer_handoff": offer_handoff, "handoff": handoff, "confidence": confidence, "mode": mode()}
    store.log_turn(session.id, mid, "assistant", text, meta)
    return {"session_id": session.id, "message_id": mid, "text": text, "status": status,
            "citations": citations or [], "offer_handoff": offer_handoff, "handoff": handoff,
            "self_serve": self_serve, "related": related or [],
            "theme": (route or {}).get("theme"), "intent": (route or {}).get("intent"),
            "confidence": confidence, "mode": mode()}


def _cite(hit_by_id: dict, ids: list[str]) -> list[dict]:
    out = []
    for i in ids:
        h = hit_by_id.get(i)
        if h:
            out.append({"id": i, "label": h.chunk.label, "source": h.chunk.source, "snippet": h.chunk.text[:400]})
    return out


def handle_message(session_id: str | None, raw: str) -> dict:
    session = get_session(session_id)
    msg = mask_pii(raw.strip())[:2000]
    sig = detect_signals(raw)
    store.log_turn(session.id, uuid.uuid4().hex[:12], "user", msg, {"signals": sig})
    session.history.append({"role": "user", "content": msg})

    prefix = ""
    if sig["shared_secret"]:
        prefix = ("For your security I've hidden the personal details you shared. Please don't send "
                  "passwords, PINs or card numbers in chat.\n\n")

    # 1. Deterministic safety routing – never depends on the model.
    if sig["emergency"]:
        session.last_intent = "safety_fraud"
        return _reply(session, prefix + "If you or someone else is in danger, please call your local emergency "
                      "number right away. I'm a support assistant and can't help with emergencies.",
                      status="emergency", offer_handoff="emergency")
    if sig["fraud"]:
        session.last_intent, session.last_theme = "safety_fraud", "account"
        h = create_handoff(session, "safety_fraud")
        text = (prefix + "This could be a security issue, so I'm passing you straight to a person instead of "
                "troubleshooting here. " + h["message"] + "\n\nIf your phone or SIM was lost or stolen, call 611 "
                "immediately so the SIM can be blocked. Don't share passwords or verification codes with anyone.")
        idx = get_index()
        faq11 = next((c for c in idx.chunks if c.id == "FAQ-11"), None)
        cites = [{"id": "FAQ-11", "label": faq11.label, "source": "faq", "snippet": faq11.text}] if faq11 else []
        return _reply(session, text, status="escalated", handoff=h, citations=cites,
                      route={"theme": "account", "intent": "safety_fraud"})
    if sig["wants_human"]:
        h = create_handoff(session, "customer_requested")
        return _reply(session, prefix + h["message"], status="escalated", handoff=h,
                      route={"theme": session.last_theme, "intent": "wants_human"})
    if sig["complaint"]:
        session.last_intent = "complaint"
        h = create_handoff(session, "complaint")
        return _reply(session, prefix + "I'm sorry this has been frustrating. Complaints and contract changes are "
                      "handled by our team, so I'm passing this on. " + h["message"], status="escalated", handoff=h,
                      route={"theme": session.last_theme, "intent": "complaint"})

    # 2. Route.
    try:
        route = _route_llm(session, msg) if CLIENT else _route_heuristic(session, msg, sig)
    except Exception as e:  # degrade gracefully (NFR availability)
        log.warning("router failed, using heuristics: %s", e)
        route = _route_heuristic(session, msg, sig)
    # Deterministic signals can only make routing more conservative.
    if sig["account_specific"] and route["intent"] == "general":
        route["intent"] = "account_specific"
    if sig["transactional"] and route["intent"] in ("general", "account_specific"):
        route["intent"] = "transactional"
    if route["intent"] == "safety_fraud":
        session.last_intent = "safety_fraud"
        h = create_handoff(session, "safety_fraud")
        return _reply(session, prefix + "This could be a security issue, so I'm passing you to a person. " + h["message"],
                      status="escalated", handoff=h, route=route)
    if route["intent"] == "wants_human":
        h = create_handoff(session, "customer_requested")
        return _reply(session, prefix + h["message"], status="escalated", handoff=h, route=route)
    session.last_theme = route["theme"] if route["theme"] != "other" else session.last_theme
    session.last_intent = route["intent"]

    if route["intent"] == "smalltalk":
        return _reply(session, prefix + "Happy to help! What can I help you with today? You can ask about data, "
                      "bills, SIM/eSIM, roaming, calls or the app.", status="smalltalk", route=route)
    if route["intent"] == "out_of_scope":
        return _reply(session, prefix + "Sorry, I can only help with NovaCell mobile service questions, like data, "
                      "bills, SIM/eSIM, roaming, calls and the app.", status="out_of_scope", route=route)

    # 3. Retrieve + confidence gate (FR-4).
    question = route["standalone_question"] or msg
    hits = get_index().search(question, theme=route["theme"])
    top = hits[0].score if hits else 0.0
    cov = get_index().coverage(question, hits[:3])
    min_top = config.THEME_MIN_TOP_SCORE.get(route["theme"], config.MIN_TOP_SCORE)
    confidence = round(min(1.0, top / 10.0) * 0.6 + cov * 0.4, 2)
    hit_by_id = {h.chunk.id: h for h in hits}
    self_serve = None
    if route["intent"] in ("account_specific", "transactional") and route["theme"] in SELF_SERVE:
        text_, sid = SELF_SERVE[route["theme"]]
        self_serve = {"text": text_, "source": sid}

    if top < min_top or cov < config.MIN_TERM_COVERAGE:
        return _unsure(session, msg, route, hits, prefix, self_serve, confidence, "low_retrieval_confidence")

    # 4. Generate + 5. verify.
    try:
        result = _answer_llm(session, question, route, hits) if CLIENT else _answer_offline(question, route, hits)
        for attempt in range(2):
            cited = [c for c in result["citations"] if c in hit_by_id]
            src_text = " ".join(hit_by_id[c].chunk.text for c in cited) or " ".join(h.chunk.text for h in hits)
            bad_nums = unsupported_numbers(result["answer"], src_text)
            promise = makes_promise(result["answer"])
            ok = bool(cited) and not bad_nums and not promise
            if result["answer_status"] == "not_in_sources" or ok or not CLIENT or attempt == 1:
                break
            log.warning("answer failed verification (nums=%s promise=%s cited=%s); retrying", bad_nums, promise, cited)
            rule = ("\n\nYOUR PREVIOUS ANSWER WAS REJECTED. "
                    + (f"These numbers are not in the cited sources: {bad_nums}. " if bad_nums else "")
                    + ("It promised a refund/credit. " if promise else "")
                    + ("It cited no valid source IDs. " if not cited else "")
                    + "Answer again using only what the sources say.")
            result = _answer_llm(session, question, route, hits, extra_rule=rule)
    except Exception as e:
        log.exception("answer generation failed: %s", e)
        result, ok = _answer_offline(question, route, hits), True
        cited = result["citations"]

    if result["answer_status"] == "not_in_sources" or not ok:
        return _unsure(session, msg, route, hits, prefix, self_serve, confidence,
                       "not_in_sources" if result["answer_status"] == "not_in_sources" else "failed_verification")

    citations = _cite(hit_by_id, cited)
    session.suggested += [c["id"] for c in citations]
    session.unsure_streak = 0

    offer = None
    if route["intent"] in ("account_specific", "transactional"):
        offer = "account_review"
    if result.get("needs_staff_action"):
        offer = "staff_action"
    if route.get("frustrated") or sig["frustrated"] or session.thumbs_down >= config.MAX_THUMBS_DOWN:
        offer = "frustration"
    status = "answered" if result["answer_status"] == "answered" else "partial"
    return _reply(session, prefix + result["answer"].strip(), status=status, route=route, citations=citations,
                  offer_handoff=offer, self_serve=self_serve, confidence=confidence)


def _unsure(session, msg, route, hits, prefix, self_serve, confidence, reason) -> dict:
    session.unsure_streak += 1
    store.log_gap(msg, route["theme"], reason)
    related = [{"id": h.chunk.id, "label": h.chunk.title} for h in hits if h.chunk.source == "faq"][:3]
    text = prefix + "I'm not sure about that one, and I'd rather not guess."
    if self_serve:
        text += " I can't see your account from this chat."
    if related:
        text += " These help articles might be related:"
    else:
        text += " A NovaCell agent can help."
    offer = "unsure" if session.unsure_streak >= 1 else None
    if session.unsure_streak >= config.MAX_CONSECUTIVE_UNSURE:
        text += "\n\nSince I haven't been able to answer, would you like me to connect you with a person?"
    return _reply(session, text, status="unsure", route=route, offer_handoff=offer, self_serve=self_serve,
                  related=related, confidence=confidence)


def record_feedback(session_id: str, message_id: str, kind: str, value: str) -> dict | None:
    store.log_feedback(session_id, message_id, kind, value)
    s = SESSIONS.get(session_id)
    if s and kind == "thumb" and value == "down":
        s.thumbs_down += 1
        if s.thumbs_down >= config.MAX_THUMBS_DOWN:
            return {"offer_handoff": "frustration",
                    "text": "Sorry that wasn't helpful. Would you like to talk to a person?"}
    return None
