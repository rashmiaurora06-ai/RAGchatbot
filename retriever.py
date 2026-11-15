"""Merged retriever: top-3 from each collection, queried in parallel (FR-06, FR-07, FR-08).

To add a knowledge source (NFR-06): write an ingest_<name>.py that fills a new Chroma
collection, then add it to COLLECTIONS below.
"""
from langchain_core.documents import Document
from langchain_core.runnables import RunnableParallel

import config
from vectorstore import collection_count, get_store

# collection name -> label shown to the LLM and in the Sources panel
COLLECTIONS = {
    "faq": "FAQ",
    "tickets": "TICKETS",
    "guides": "GUIDES",
}


def build_retriever() -> RunnableParallel:
    return RunnableParallel({
        name: get_store(name).as_retriever(search_kwargs={"k": config.TOP_K_PER_COLLECTION})
        for name in COLLECTIONS
    })


_retriever = None


def retrieve(question: str) -> dict[str, list[Document]]:
    """Return {collection: [docs]} — up to 9 documents in total."""
    global _retriever
    if _retriever is None:
        _retriever = build_retriever()
    return _retriever.invoke(question)


def format_context(results: dict[str, list[Document]]) -> str:
    """Source-labelled context block for the prompt."""
    sections = []
    for name, label in COLLECTIONS.items():
        docs = results.get(name, [])
        body = "\n\n".join(f"[{d.metadata.get('id', '?')}]\n{d.page_content}" for d in docs) or "(none)"
        sections.append(f"=== {label} ===\n{body}")
    return "\n\n".join(sections)


def missing_collections() -> list[str]:
    """Collections that are empty, so the UI can tell the operator to run the ingest scripts."""
    return [name for name in COLLECTIONS if collection_count(name) == 0]
