"""Central configuration for the NovaCell support assistant.

Every threshold and policy knob the PRD says ops should be able to tune lives here.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "prd_exercise" / "data"
FAQ_CSV = DATA_DIR / "faq.csv"
TICKETS_DB = DATA_DIR / "tickets.db"
GUIDE_PDFS = [DATA_DIR / "telecom_guide.pdf"]

# Runtime state (content edits, gap queue, handoffs, feedback, transcripts)
STATE_DB = ROOT / "runtime" / "assistant.db"

# --- Models -----------------------------------------------------------------
# Answer generation uses Claude Opus 5.5. Routing/classification uses the smaller
# Claude Haiku 5.5, per PRD §5 ("use a smaller model for classification and routing").
ANSWER_MODEL = os.environ.get("NOVACELL_ANSWER_MODEL", "claude-opus-5-5")
ROUTER_MODEL = os.environ.get("NOVACELL_ROUTER_MODEL", "claude-haiku-5-5")
ANSWER_EFFORT = os.environ.get("NOVACELL_ANSWER_EFFORT", "low")  # chat: keep latency low

# --- Retrieval & confidence (FR-4) ---------------------------------------------
TOP_K = 6
# Minimum BM25 score of the best chunk, and minimum share of the question's key
# terms found in the retrieved chunks, before we attempt an answer at all.
MIN_TOP_SCORE = 2.0
MIN_TERM_COVERAGE = 0.34
# Stricter per-theme overrides (FR-4.3) – billing answers must be very well supported.
THEME_MIN_TOP_SCORE = {"billing": 3.0}

# Source priority when sources disagree (FR-1.8): lower number wins.
SOURCE_PRIORITY = {"faq": 1, "guide": 2, "ticket": 3}

# --- Escalation (FR-6) ---------------------------------------------------------
LIVE_CHAT_OPEN_HOUR = 8    # live chat 8am–10pm per FAQ #25
LIVE_CHAT_CLOSE_HOUR = 22
MAX_CONSECUTIVE_UNSURE = 2  # two "I don't know" in a row -> offer human
MAX_THUMBS_DOWN = 2

# --- Guide ingestion: audience filtering (FR-1.6) ------------------------------
# Whole sections of the internal guide that must never reach customers.
GUIDE_EXCLUDED_SECTIONS = ["Network Security and Fraud Prevention"]
# Paragraphs (by their leading label) that are internal-only.
GUIDE_EXCLUDED_PARAGRAPH_PREFIXES = ["SIM Security:", "SIM Swap Fraud:", "Technical Mechanism:"]

ADMIN_TOKEN = os.environ.get("NOVACELL_ADMIN_TOKEN", "")
