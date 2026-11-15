"""Lexical (BM25) retrieval over the knowledge corpus, with telecom synonyms.

BM25 needs no embedding service, works offline, and makes every match explainable
(which terms hit which chunk). The index is rebuilt in-process whenever ops publish
content, so changes go live in seconds (FR-1.2, NFR freshness).
"""
from __future__ import annotations

import math
import re
import threading
from collections import Counter
from dataclasses import dataclass

from . import config
from .ingest import Chunk, build_corpus

_STOP = set("""a an the and or but if of to in on at for from by with about as is are was were be been being
i me my we our you your it its this that these those do does did doing have has had can could should would
will shall may might must so than then there here what which who whom how why when where not no yes just
please hi hello thanks thank help need want get got also any some all very really still keep""".split())

# Customer words -> words the sources use. Applied to queries only.
_SYNONYMS = {
    "slow": ["speed", "throttled", "congestion"], "internet": ["data"], "wifi": ["wi-fi"],
    "abroad": ["roaming", "travel"], "travel": ["roaming"], "travelling": ["roaming"], "trip": ["roaming"],
    "overseas": ["roaming"], "international": ["roaming"],
    "bill": ["billing", "charges"], "charged": ["charges", "bill"], "charge": ["charges", "bill"],
    "expensive": ["bill", "charges"], "higher": ["bill"], "pay": ["payment", "billing"],
    "esim": ["sim", "qr", "esim"], "activate": ["activation"], "activating": ["activation"],
    "dropping": ["drop", "drops"], "dropped": ["drop", "drops"], "calls": ["call", "voice"],
    "signal": ["coverage", "signal"], "login": ["log", "password"], "password": ["reset", "log"],
    "hotspot": ["tethering", "hotspot"], "tether": ["hotspot"], "unlock": ["unlock", "unlocked"],
    "switch": ["porting", "port"], "keep": ["port"], "volte": ["volte", "hd"],
}


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9][a-z0-9\-]*", text.lower().replace("e-sim", "esim"))
    return [_stem(w) for w in words if w not in _STOP and len(w) > 1]


def expand_query(text: str) -> list[str]:
    toks = tokenize(text)
    extra = []
    for w in re.findall(r"[a-z0-9\-]+", text.lower()):
        extra += [_stem(s) for s in _SYNONYMS.get(w, [])]
    return toks + extra


@dataclass
class Hit:
    chunk: Chunk
    score: float


class Index:
    def __init__(self, chunks: list[Chunk], k1: float = 1.4, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        # Titles are short and precise; weight them by repeating.
        self.docs = [tokenize(f"{c.title} {c.title} {c.text} {c.category}") for c in chunks]
        self.tf = [Counter(d) for d in self.docs]
        self.avgdl = sum(len(d) for d in self.docs) / max(len(self.docs), 1)
        df = Counter(t for d in self.docs for t in set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = config.TOP_K, theme: str | None = None) -> list[Hit]:
        q = expand_query(query)
        scores = []
        for i, tf in enumerate(self.tf):
            dl = len(self.docs[i])
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            if s <= 0:
                continue
            c = self.chunks[i]
            if theme and c.category == theme:
                s *= 1.15
            if c.source == "faq":
                s *= 1.10  # FAQ is the highest-priority, customer-ready source
            scores.append(Hit(c, s))
        scores.sort(key=lambda h: h.score, reverse=True)
        return scores[:k]

    @staticmethod
    def coverage(query: str, hits: list[Hit]) -> float:
        """Share of the question's own key terms that appear in the retrieved chunks."""
        q = set(tokenize(query))
        if not q:
            return 0.0
        seen = set()
        for h in hits:
            seen |= set(tokenize(f"{h.chunk.title} {h.chunk.text}"))
        expanded = {t for t in q if t in seen or any(_stem(s) in seen for s in _SYNONYMS.get(t, []))}
        return len(expanded) / len(q)


_index: Index | None = None
_lock = threading.Lock()


def get_index() -> Index:
    global _index
    with _lock:
        if _index is None:
            _index = Index(build_corpus())
        return _index


def rebuild_index() -> Index:
    global _index
    with _lock:
        _index = Index(build_corpus())
        return _index
