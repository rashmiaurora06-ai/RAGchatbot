"""HTTP server for the NovaCell support assistant (customer chat + ops console).

Run:  .venv/bin/python server.py      then open http://localhost:8000  (ops: /admin)
"""
from __future__ import annotations

import logging
import secrets
import time
from collections import Counter

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from novacell_bot import assistant, config, store
from novacell_bot.retrieval import get_index, rebuild_index

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("novacell.server")

ADMIN_TOKEN = config.ADMIN_TOKEN or secrets.token_urlsafe(12)
STATIC = config.ROOT / "static"
app = FastAPI(title="NovaCell Support Assistant")


# ------------------------------------------------------------ customer API

class ChatIn(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=2000)


class HandoffIn(BaseModel):
    session_id: str
    reason: str = "customer_requested"


class FeedbackIn(BaseModel):
    session_id: str
    message_id: str = ""
    kind: str  # thumb | resolved
    value: str  # up/down | yes/no


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/admin")
def admin_page():
    return FileResponse(STATIC / "admin.html")


@app.get("/api/welcome")
def welcome():
    s = assistant.get_session(None)
    return {"session_id": s.id, "text": assistant.WELCOME, "suggestions": assistant.SUGGESTIONS,
            "mode": assistant.mode(), "live_chat_open": assistant.live_chat_open()}


@app.post("/api/chat")
def chat(body: ChatIn):
    t0 = time.time()
    out = assistant.handle_message(body.session_id, body.message)
    out["latency_ms"] = int((time.time() - t0) * 1000)
    return out


@app.post("/api/handoff")
def handoff(body: HandoffIn):
    s = assistant.get_session(body.session_id)
    h = assistant.create_handoff(s, body.reason)
    s.history.append({"role": "assistant", "content": h["message"]})
    return h


@app.post("/api/feedback")
def feedback(body: FeedbackIn):
    return {"ok": True, "follow_up": assistant.record_feedback(body.session_id, body.message_id, body.kind, body.value)}


@app.get("/api/health")
def health():
    return {"ok": True, "mode": assistant.mode(), "chunks": len(get_index().chunks)}


# ------------------------------------------------------------ ops console API

def _auth(token: str | None):
    if not token or not secrets.compare_digest(token, ADMIN_TOKEN):
        raise HTTPException(401, "invalid admin token")


class DraftIn(BaseModel):
    source_id: str | None = None
    question: str = Field(min_length=5)
    answer: str = Field(min_length=5)
    category: str
    author: str = Field(min_length=1)


class ApproveIn(BaseModel):
    approver: str = Field(min_length=1)


class RetireIn(BaseModel):
    source_id: str
    approver: str = Field(min_length=1)


@app.get("/api/admin/metrics")
def metrics(x_admin_token: str | None = Header(None)):
    _auth(x_admin_token)
    turns = store.rows("SELECT role, meta FROM turns WHERE role='assistant'")
    import json
    statuses = Counter(json.loads(t["meta"]).get("status") for t in turns)
    themes = Counter((json.loads(t["meta"]).get("route") or {}).get("theme") for t in turns)
    fb = store.rows("SELECT kind, value, COUNT(*) n FROM feedback GROUP BY kind, value")
    handoffs = store.rows("SELECT reason, COUNT(*) n FROM handoffs GROUP BY reason")
    sessions = store.rows("SELECT COUNT(DISTINCT session_id) n FROM turns")[0]["n"]
    escalated_sessions = store.rows("SELECT COUNT(DISTINCT session_id) n FROM handoffs")[0]["n"]
    cited = Counter()
    for t in turns:
        cited.update(json.loads(t["meta"]).get("citations") or [])
    never = [c.id for c in get_index().chunks if c.id not in cited]
    return {
        "conversations": sessions,
        "assistant_messages": len(turns),
        "status_counts": dict(statuses),
        "theme_counts": {k or "none": v for k, v in themes.items()},
        "containment_rate": round(1 - escalated_sessions / sessions, 3) if sessions else None,
        "handoffs_by_reason": {h["reason"]: h["n"] for h in handoffs},
        "feedback": {f"{f['kind']}:{f['value']}": f["n"] for f in fb},
        "top_cited": cited.most_common(10),
        "never_cited_count": len(never),
        "open_gaps": store.rows("SELECT COUNT(*) n FROM gaps WHERE resolved=0")[0]["n"],
        "mode": assistant.mode(),
    }


@app.get("/api/admin/content")
def content(x_admin_token: str | None = Header(None)):
    _auth(x_admin_token)
    live = [{"id": c.id, "question": c.title, "answer": c.text.split("\nA: ", 1)[-1], "category": c.category,
             "ops_edited": c.meta.get("ops_edited", False)}
            for c in get_index().chunks if c.source == "faq"]
    drafts = store.rows("SELECT * FROM content WHERE status='draft' ORDER BY id DESC")
    history = store.rows("SELECT id, source_id, status, author, approver, published_at FROM content "
                         "WHERE status != 'draft' ORDER BY id DESC LIMIT 50")
    return {"live": live, "drafts": drafts, "history": history}


@app.post("/api/admin/content/draft")
def draft(body: DraftIn, x_admin_token: str | None = Header(None)):
    _auth(x_admin_token)
    return {"id": store.save_draft(body.source_id, body.question, body.answer, body.category, body.author)}


@app.post("/api/admin/content/{draft_id}/publish")
def publish(draft_id: int, body: ApproveIn, x_admin_token: str | None = Header(None)):
    _auth(x_admin_token)
    try:
        store.publish(draft_id, body.approver)
    except ValueError as e:
        raise HTTPException(400, str(e))
    idx = rebuild_index()  # live immediately – no engineering release
    return {"ok": True, "chunks": len(idx.chunks)}


@app.post("/api/admin/content/retire")
def retire(body: RetireIn, x_admin_token: str | None = Header(None)):
    _auth(x_admin_token)
    store.retire(body.source_id, body.approver)
    idx = rebuild_index()
    return {"ok": True, "chunks": len(idx.chunks)}


@app.get("/api/admin/gaps")
def gaps(x_admin_token: str | None = Header(None)):
    _auth(x_admin_token)
    return store.rows("SELECT * FROM gaps WHERE resolved=0 ORDER BY id DESC LIMIT 200")


@app.post("/api/admin/gaps/{gap_id}/resolve")
def resolve_gap(gap_id: int, x_admin_token: str | None = Header(None)):
    _auth(x_admin_token)
    store.execute("UPDATE gaps SET resolved=1 WHERE id=?", (gap_id,))
    return {"ok": True}


@app.get("/api/admin/handoffs")
def handoffs(x_admin_token: str | None = Header(None)):
    _auth(x_admin_token)
    import json
    out = store.rows("SELECT * FROM handoffs ORDER BY id DESC LIMIT 100")
    for h in out:
        h["package"] = json.loads(h["package"] or "{}")
    return out


if __name__ == "__main__":
    get_index()
    log.info("Mode: %s | knowledge chunks: %d", assistant.mode(), len(get_index().chunks))
    if not config.ADMIN_TOKEN:
        log.info("Ops console token for this run (set NOVACELL_ADMIN_TOKEN to fix it): %s", ADMIN_TOKEN)
    uvicorn.run(app, host="127.0.0.1", port=8000)
