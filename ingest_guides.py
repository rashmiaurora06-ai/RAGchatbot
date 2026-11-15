"""Chunk data/telecom_guide.pdf (600 chars, 100 overlap) into the `guides` collection (FR-16)."""
import re

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config
from vectorstore import rebuild_collection

COLLECTION = "guides"


def _clean(text: str) -> str:
    # Drop the repeated running header and page footer from each page.
    text = re.sub(r"Telecom Technical Reference Guide\s*-\s*Internal Use Only", "", text)
    text = re.sub(r"\n\s*Page \d+\s*$", "", text.strip())
    return text.strip()


def load():
    pages = PyPDFLoader(str(config.GUIDE_PDF)).load()
    for p in pages:
        p.page_content = _clean(p.page_content)
    pages = [p for p in pages if p.page_content]
    splitter = RecursiveCharacterTextSplitter(chunk_size=config.GUIDE_CHUNK_SIZE,
                                              chunk_overlap=config.GUIDE_CHUNK_OVERLAP)
    chunks = splitter.split_documents(pages)
    ids = []
    for i, c in enumerate(chunks, start=1):
        page = int(c.metadata.get("page", 0)) + 1  # PyPDFLoader pages are 0-based
        first_line = c.page_content.strip().splitlines()[0]
        c.metadata = {"source": "GUIDE", "id": f"GUIDE-p{page}-c{i}", "page": page,
                      "title": first_line[:80], "file": config.GUIDE_PDF.name}
        ids.append(f"guide-{i}")
    return chunks, ids


def main() -> None:
    docs, ids = load()
    n = rebuild_collection(COLLECTION, docs, ids)
    print(f"guides: ingested {n} chunks from {config.GUIDE_PDF.name}")


if __name__ == "__main__":
    main()
