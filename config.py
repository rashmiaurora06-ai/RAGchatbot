"""Shared settings for the RAG telecom customer care chatbot (see PRD.md)."""
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")  # NFR-03: secrets come from .env, never from code

DATA_DIR = ROOT / "data"
FAQ_CSV = DATA_DIR / "faq.csv"                 # FR-14
TICKETS_DB = DATA_DIR / "tickets.db"           # FR-15
GUIDE_PDF = DATA_DIR / "telecom_guide.pdf"     # FR-16
CHROMA_DIR = ROOT / "chroma_store"             # FR-17
LOG_DIR = ROOT / "logs"
INTERACTION_LOG = LOG_DIR / "interactions.jsonl"  # FR-05a

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"  # FR-09, NFR-02
GUIDE_CHUNK_SIZE = 600      # FR-16
GUIDE_CHUNK_OVERLAP = 100   # FR-16
TOP_K_PER_COLLECTION = 3    # FR-07

# FR-13 names qwen/qwen3.6-27b, but Groq no longer serves it; qwen3.8-27b is its successor.
LLM_MODEL = "qwen/qwen3.8-27b"
LLM_TEMPERATURE = 0              # FR-12
LLM_REASONING_EFFORT = "none"    # FR-13

# agent_PRD FR-50: how many recent user/assistant exchanges are passed as context.
HISTORY_EXCHANGES = 4

SAMPLE_QUESTIONS = [
    "Why is my mobile internet so slow?",
    "Why is my bill higher than usual?",
    "How do I activate an eSIM?",
    "How do I use my phone in another country?",
    "How do I keep my number when switching to MyTelecom?",
    "How do I unlock my phone to use another carrier?",
    "How do I turn on Wi-Fi Calling?",
    "How do I block spam and robocalls?",
]

# agent_PRD section 8 demo prompts for the Refund Agent.
REFUND_SAMPLES = [
    "I want a refund of $100.",
    "I want a refund of $150.",
    "Give me a refund of $2,000.",
    "I want a refund.",
]
