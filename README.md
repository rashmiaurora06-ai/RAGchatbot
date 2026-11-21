# RAG Telecom Customer Care Chatbot

A chatbot that answers Tier-1 telecom support questions using only three knowledge
sources: the FAQ, resolved support tickets and the technical PDF guide. Built to
[PRD.md](PRD.md).

**Stack:** LangChain · ChromaDB · local `all-MiniLM-L6-v2` embeddings ·
`qwen/qwen3.8-27b` on Groq (temperature 0, `reasoning_effort="none"`) · Streamlit, plus a CLI.
The PRD names `qwen/qwen3.6-27b`, but Groq no longer serves it, so the app uses its successor.
Change `LLM_MODEL` in `config.py` to switch models.

To save your Groq key without it showing on screen, run `zsh set_groq_key.sh`.

## Setup

Everything installs into the project-local `.venv`, never the global Python.

```bash
uv venv --python 3.13 .venv
```

```bash
uv pip install --python .venv/bin/python -r requirements.txt
```

(Or `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.)

```bash
cp .env.example .env
```

Then put your Groq key in `.env` (`GROQ_API_KEY=...`).

## Build the knowledge base

```bash
.venv/bin/python ingest_all.py
```

This runs `ingest_faq.py`, `ingest_tickets.py` and `ingest_guides.py`. Each one is idempotent,
so it rebuilds its collection in `chroma_store/` from `data/`. The embedding model (~90 MB)
downloads on the first run. The app reads the stored collections and doesn't re-ingest on start.

| Collection | Source | Documents |
|---|---|---|
| `faq` | `data/faq.csv` | 1 per row (25) |
| `tickets` | `data/tickets.db` | 1 per **resolved** ticket (19; the 1 escalated ticket is skipped) |
| `guides` | `data/telecom_guide.pdf` | 600-char chunks, 100-char overlap (36) |

## Run

Web app:

```bash
.venv/bin/streamlit run app.py
```

CLI (type `quit` to exit):

```bash
.venv/bin/python main.py
```

## How it works

1. `retriever.py` queries the three Chroma collections in parallel, top 3 each (9 docs).
2. `chain.py` puts them into the prompt labelled `FAQ` / `TICKETS` / `GUIDES`, and tells the
   model to answer only from that context. If the context isn't enough, it says so and points
   to 611 or the MyTelecom app.
3. The answer streams token by token. A **Sources** expander lists all 9 retrieved documents.
4. 👍 / 👎 ratings, questions, answers, sources and latency are written to `logs/interactions.jsonl`.

## Refund Agent (agentic capability)

Built to [agent_PRD.md](agent_PRD.md). Every message first goes through **intent detection**
(`intent.py`, same Groq model, structured output):

- `requirement_inquiry` → the existing RAG pipeline, unchanged.
- `refund_request` → the **Refund Agent** (`refund_agent.py`).

The agent is an LLM tool-calling loop that can call only `get_user_account` and
`validate_refund`. As soon as validation returns, application code takes over:

| Outcome | What happens |
|---|---|
| Not eligible (too old, already refunded, more than the recharge, ≤ 0) | Rejected with the reason |
| Eligible, ₹499 or less | Confirmation card (**Confirm Refund** / **Cancel**, or type "Yes, proceed"), then `process_refund` |
| Eligible, above ₹499 | `submit_to_support`, the user is told Support will review it, turn ends |

Guardrails live in code, not the prompt. `refund.py` holds the rules, the ₹499 limit, the
simulated accounts and all four tools. `process_refund` and `submit_to_support` are never
offered to the LLM, and both re-validate before acting. A state machine only runs a refund
from `awaiting_confirmation` after an exact "yes" phrase; anything ambiguous gets asked again.
The agent may only use an amount the customer actually typed, or the single refundable
recharge when they gave none.

- The demo user is `user_123` (Rahul: ₹999 and ₹499 recharges). The sidebar can switch to
  `user_234`, whose ₹299 recharge is 15 days old, to demo the 7-day window.
- Refunds are simulated and stored per browser session. No billing system is called.
- The last 4 exchanges are passed as context to both routes. Retrieval still uses only the
  current question. **Clear conversation** resets the history and any pending refund.
- Each refund answer has an **Agent steps** expander (`[Intent] …`, `[Agent] validate_refund(…)`, …).
  Steps are also written to `logs/interactions.jsonl`.
- In the CLI, type `clear` to reset the conversation.

Rule and state-machine tests (no API calls):

```bash
.venv/bin/python test_refund.py
```

## Updating knowledge (support ops)

- Edit `data/faq.csv`, then run `.venv/bin/python ingest_faq.py`.
- Add resolved tickets to `data/tickets.db`, then run `.venv/bin/python ingest_tickets.py`.
- Replace the PDF, then run `.venv/bin/python ingest_guides.py`.

Restart the app after re-ingesting.

**New source:** write an `ingest_<name>.py` that fills a new collection (see `vectorstore.rebuild_collection`),
then add it to `COLLECTIONS` in `retriever.py`.

## Files

| File | Purpose |
|---|---|
| `config.py` | Paths, model names, chunk sizes, top-k, sample questions |
| `vectorstore.py` | Chroma + embedding helpers |
| `ingest_*.py` | Ingest scripts, one per source |
| `retriever.py` | Merged parallel retriever and context formatting |
| `chain.py` | Prompt, Groq/Qwen chain, streaming, interaction log |
| `app.py` | Streamlit UI |
| `main.py` | CLI REPL |
