"""Load data/faq.csv into the `faq` collection: one row = one document (FR-14)."""
import csv

from langchain_core.documents import Document

import config
from vectorstore import rebuild_collection

COLLECTION = "faq"


def load() -> tuple[list[Document], list[str]]:
    docs, ids = [], []
    with open(config.FAQ_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            docs.append(Document(
                page_content=f"Q: {row['question'].strip()}\nA: {row['answer'].strip()}",
                metadata={"source": "FAQ", "id": f"FAQ-{row['id']}", "category": row["category"].strip(),
                          "title": row["question"].strip()},
            ))
            ids.append(f"faq-{row['id']}")
    return docs, ids


def main() -> None:
    docs, ids = load()
    n = rebuild_collection(COLLECTION, docs, ids)
    print(f"faq: ingested {n} documents")


if __name__ == "__main__":
    main()
