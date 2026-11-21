"""Answer generation: source-labelled context -> Qwen3.6-27B on Groq -> streamed text.

Shared by the Streamlit app (app.py) and the CLI (main.py).
"""
import json
import os
import re
import time
import uuid
from collections.abc import Iterator

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_groq import ChatGroq

import config
from retriever import COLLECTIONS, format_context, retrieve

SYSTEM_PROMPT = """You are a friendly, knowledgeable customer care assistant for a mobile telecom operator.
You help customers with mobile connectivity, billing, SIM and eSIM, roaming, voice calls, and
account or app questions.

Rules:
1. Answer ONLY from the CONTEXT below. Do not use any outside or general knowledge. Never invent
   prices, fees, timelines, speeds, policies or procedures that are not in the context.
2. If the context does not contain enough information to answer, say so clearly, then tell the
   customer to call 611 (free from their mobile) or use the MyTelecom app for help.
3. FAQ entries are official answers. TICKETS are past cases that show how similar problems were
   resolved by support staff; present those fixes as something support can do for the customer, not
   as a promise, and don't mention ticket IDs or other customers. GUIDES give technical background.
4. Write in plain, simple language. For troubleshooting, give short numbered steps.
5. Be concise: usually under 150 words.

CONTEXT
{context}"""

PROMPT = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    MessagesPlaceholder("history", optional=True),  # agent_PRD FR-46: recent conversation
    ("human", "{question}"),
])

_THINK = re.compile(r"<think>.*?</think>\s*", re.S)


class MissingAPIKey(RuntimeError):
    pass


_llms: dict = {}
_chain = None
_chain_llm = None


def get_llm(streaming: bool = False) -> ChatGroq:
    """The one LLM configuration, shared by RAG, intent detection and the Refund Agent.
    Rebuilt whenever the key in .env changes (no restart needed)."""
    load_dotenv(config.ROOT / ".env", override=True)
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise MissingAPIKey("GROQ_API_KEY is not set. Copy .env.example to .env and add your key.")
    if _llms.get(("key", streaming)) != key:
        _llms[streaming] = ChatGroq(model=config.LLM_MODEL, temperature=config.LLM_TEMPERATURE,
                                    reasoning_effort=config.LLM_REASONING_EFFORT,
                                    streaming=streaming, api_key=key)
        _llms[("key", streaming)] = key
    return _llms[streaming]


def get_chain():
    global _chain, _chain_llm
    llm = get_llm(streaming=True)
    if _chain is None or llm is not _chain_llm:
        _chain = PROMPT | llm | StrOutputParser()
        _chain_llm = llm
    return _chain


def to_messages(history: list[dict] | None) -> list[BaseMessage]:
    """[{role, content}] -> LangChain messages, keeping only the last HISTORY_EXCHANGES (FR-50)."""
    recent = (history or [])[-2 * config.HISTORY_EXCHANGES:]
    return [HumanMessage(m["content"]) if m["role"] == "user" else AIMessage(m["content"])
            for m in recent if m.get("content")]


def strip_think(text: str) -> str:
    return _THINK.sub("", text or "").strip()


def sources_from(results: dict) -> list[dict]:
    """Flatten retrieval results into rows for the Sources panel (FR-13a)."""
    out = []
    for name, label in COLLECTIONS.items():
        for d in results.get(name, []):
            out.append({"source": label, "id": d.metadata.get("id", "?"),
                        "title": d.metadata.get("title", ""), "text": d.page_content})
    return out


def stream_answer(question: str, history: list[dict] | None = None) -> tuple[list[dict], Iterator[str]]:
    """Retrieve, then return (sources, token stream).

    History is passed to the LLM as context only; retrieval still uses just the question (FR-49).
    """
    results = retrieve(question)
    context = format_context(results)
    chain = get_chain()

    def tokens() -> Iterator[str]:
        # Some reasoning models emit <think>...</think>; hide it if it ever appears.
        buf, in_think = "", False
        for piece in chain.stream({"context": context, "question": question,
                                   "history": to_messages(history)}):
            buf += piece
            if not in_think and "<think>" in buf:
                in_think = True
            if in_think:
                if "</think>" in buf:
                    buf = _THINK.sub("", buf)
                    in_think = False
                else:
                    continue
            if buf:
                yield buf
                buf = ""
        if buf and not in_think:
            yield buf

    return sources_from(results), tokens()


# ---- interaction log (FR-05a) ----------------------------------------------

def log_event(event: dict) -> None:
    config.LOG_DIR.mkdir(exist_ok=True)
    event = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **event}
    with open(config.INTERACTION_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def new_id() -> str:
    return uuid.uuid4().hex[:12]
