"""Turn the three NovaCell knowledge sources into customer-safe, citable chunks.

Rules applied here come straight from PRD FR-1:
  * FAQ  – customer-ready; ops edits/additions/retirements from the admin console
           override the seed CSV without an engineering release (FR-1.2).
  * Tickets – only status='resolved' rows (FR-1.4); PII scrubbed (FR-1.5); sentences
           about credits/refunds/compensation removed so they're never quoted as
           policy (FR-1.8 / FR-3.6); tagged as "agent action" when the fix needed staff.
  * Guide – internal-only sections/paragraphs excluded and agent-only sentences
           dropped (FR-1.6).
"""
from __future__ import annotations

import csv
import re
import sqlite3
from dataclasses import dataclass, field

from pypdf import PdfReader

from . import config, store
from .guardrails import mask_pii


@dataclass
class Chunk:
    id: str             # citation id shown to users, e.g. FAQ-9, TK-004, GUIDE-p5-2
    source: str         # faq | ticket | guide
    title: str
    text: str
    category: str = "general"
    meta: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        if self.source == "faq":
            return f"FAQ: {self.title}"
        if self.source == "ticket":
            return f"Past case {self.id}: {self.title}"
        return f"Guide – {self.title} (p.{self.meta.get('page')})"


# ---------------------------------------------------------------- FAQ

def load_faq() -> list[Chunk]:
    chunks: dict[str, Chunk] = {}
    with open(config.FAQ_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cid = f"FAQ-{row['id']}"
            chunks[cid] = Chunk(cid, "faq", row["question"].strip(),
                                f"Q: {row['question'].strip()}\nA: {row['answer'].strip()}",
                                row["category"].strip())
    # Ops overrides (published edits, new entries, retirements)
    for r in store.published_content():
        if r["status"] == "retired":
            chunks.pop(r["source_id"], None)
        else:
            chunks[r["source_id"]] = Chunk(r["source_id"], "faq", r["question"],
                                           f"Q: {r['question']}\nA: {r['answer']}", r["category"],
                                           {"ops_edited": True})
    return list(chunks.values())


# ---------------------------------------------------------------- Tickets

_COMPENSATION = re.compile(r"(?i)(goodwill|compensation|credit|refund|offered|as a gesture|upgrade deal)")
_AGENT_ACTION = re.compile(r"(?i)(remotely|backend|via the (?:hlr|bss)|portal|generated|reconfigured|"
                           r"deactivated|enabled .* on the (?:customer's )?(?:profile|account)|extended|"
                           r"refreshed|reset credentials|network team|repair crew|field team|escalated|"
                           r"manually|soft-provisioned|verified identity)")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def load_tickets() -> list[Chunk]:
    con = sqlite3.connect(config.TICKETS_DB)
    con.row_factory = sqlite3.Row
    out = []
    for r in con.execute("SELECT * FROM tickets WHERE status = 'resolved' ORDER BY ticket_id"):
        resolution = " ".join(s for s in _sentences(r["resolution"]) if not _COMPENSATION.search(s))
        agent_action = bool(_AGENT_ACTION.search(r["resolution"]))
        text = (f"Symptom: {mask_pii(r['description'])}\n"
                f"What resolved it: {mask_pii(resolution)}\n"
                f"Fix required a NovaCell staff action: {'yes' if agent_action else 'no'}")
        out.append(Chunk(r["ticket_id"], "ticket", r["issue_type"], text, r["category"],
                         {"agent_action": agent_action}))
    con.close()
    return out


# ---------------------------------------------------------------- Guide PDF

_SECTION = re.compile(r"^\s*(\d+)\.\s+(.+)$")
_AGENT_SENTENCE = re.compile(r"(?i)\b(agents?|internal use)\b")
_GUIDE_CATEGORY = {
    "Mobile Networks": "connectivity", "Connectivity": "connectivity", "Data Plans": "data",
    "Roaming": "roaming", "SIM": "sim", "VoLTE": "voice", "Billing": "billing",
}


def _guide_category(section: str) -> str:
    for k, v in _GUIDE_CATEGORY.items():
        if k.lower() in section.lower():
            return v
    return "general"


def load_guide(path) -> list[Chunk]:
    reader = PdfReader(str(path))
    out: list[Chunk] = []
    for pno, page in enumerate(reader.pages, start=1):
        lines = [l for l in (page.extract_text() or "").splitlines()
                 if l.strip() and "Internal Use Only" not in l and not re.fullmatch(r"\s*Page \d+\s*", l)]
        section = None
        body: list[str] = []
        for line in lines:
            m = _SECTION.match(line)
            if m and section is None:
                section = m.group(2).strip()
            else:
                body.append(line.strip())
        if not section or any(x.lower() in section.lower() for x in config.GUIDE_EXCLUDED_SECTIONS):
            continue
        # Re-flow the page into paragraphs: a paragraph starts at "Label:" / "Step N" / "- ".
        paras: list[str] = []
        for line in body:
            starts_new = re.match(r"^(Step \d+|[A-Za-z][\w /()&'-]{2,40}:|- )", line)
            if starts_new or not paras:
                paras.append(line)
            else:
                paras[-1] += " " + line
        for i, p in enumerate(paras, start=1):
            if any(p.startswith(x) for x in config.GUIDE_EXCLUDED_PARAGRAPH_PREFIXES):
                continue
            kept = " ".join(s for s in _sentences(p) if not _AGENT_SENTENCE.search(s))
            if len(kept) < 40:
                continue
            out.append(Chunk(f"GUIDE-p{pno}-{i}", "guide", section, kept, _guide_category(section),
                             {"page": pno, "doc": path.name}))
    return out


def build_corpus() -> list[Chunk]:
    chunks = load_faq() + load_tickets()
    for pdf in config.GUIDE_PDFS:
        chunks += load_guide(pdf)
    return chunks


if __name__ == "__main__":
    corpus = build_corpus()
    from collections import Counter
    print(Counter(c.source for c in corpus))
    for c in corpus:
        print(f"--- {c.id} [{c.category}] {c.label}\n{c.text[:300]}")
