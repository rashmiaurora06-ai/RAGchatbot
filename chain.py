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
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
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
    ("human", "{question}"),
])

_THINK = re.compile(r"<think>.*?</think>\s*", re.S)


class MissingAPIKey(RuntimeError):
    pass


_chain = None
_chain_key = None


def get_chain():
    """Build the chain, and rebuild it whenever the key in .env changes (no restart needed)."""
    global _chain, _chain_key
    load_dotenv(config.ROOT / ".env", override=True)
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise MissingAPIKey("GROQ_API_KEY is not set. Copy .env.example to .env and add your key.")
    if _chain is None or key != _chain_key:
        llm = ChatGroq(model=config.LLM_MODEL, temperature=config.LLM_TEMPERATURE,
                       reasoning_effort=config.LLM_REASONING_EFFORT, streaming=True, api_key=key)
        _chain = PROMPT | llm | StrOutputParser()
        _chain_key = key
    return _chain


def sources_from(results: dict) -> list[dict]:
    """Flatten retrieval results into rows for the Sources panel (FR-13a)."""
    out = []
    for name, label in COLLECTIONS.items():
        for d in results.get(name, []):
            out.append({"source": label, "id": d.metadata.get("id", "?"),
                        "title": d.metadata.get("title", ""), "text": d.page_content})
    return out


def stream_answer(question: str) -> tuple[list[dict], Iterator[str]]:
    """Retrieve, then return (sources, token stream)."""
    results = retrieve(question)
    context = format_context(results)
    chain = get_chain()

    def tokens() -> Iterator[str]:
        # Some reasoning models emit <think>...</think>; hide it if it ever appears.
        buf, in_think = "", False
        for piece in chain.stream({"context": context, "question": question}):
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
