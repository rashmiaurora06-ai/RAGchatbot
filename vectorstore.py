"""Chroma vector store helpers shared by the ingest scripts and the retriever."""
import threading
from functools import lru_cache

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

import config

_lock = threading.Lock()
_client = None
_stores: dict[str, Chroma] = {}


@lru_cache(maxsize=1)
def get_embeddings() -> HuggingFaceEmbeddings:
    # Runs locally; the model (~90 MB) downloads from Hugging Face on first use.
    return HuggingFaceEmbeddings(model_name=config.EMBEDDING_MODEL,
                                 encode_kwargs={"normalize_embeddings": True})


def get_client():
    """One shared Chroma client per process. Creating several at once (e.g. from
    Streamlit's threads) makes Chroma fail with 'Could not connect to tenant'."""
    global _client
    with _lock:
        if _client is None:
            _client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
        return _client


def get_store(collection: str) -> Chroma:
    client = get_client()
    with _lock:
        if collection not in _stores:
            _stores[collection] = Chroma(collection_name=collection, client=client,
                                         embedding_function=get_embeddings(),
                                         collection_metadata={"hnsw:space": "cosine"})
        return _stores[collection]


def rebuild_collection(collection: str, docs: list[Document], ids: list[str]) -> int:
    """Replace a collection's contents. Safe to re-run: same input gives the same store (FR-17)."""
    get_store(collection).delete_collection()
    with _lock:
        _stores.pop(collection, None)
    store = get_store(collection)
    store.add_documents(docs, ids=ids)
    return len(docs)


def collection_count(collection: str) -> int:
    return get_store(collection)._collection.count()
