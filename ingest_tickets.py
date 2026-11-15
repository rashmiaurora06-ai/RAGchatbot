"""Load resolved tickets from data/tickets.db into the `tickets` collection (FR-15).

One resolved ticket = one document. Tickets with any other status (e.g. 'escalated')
are skipped, since they don't describe a confirmed resolution.
"""
import sqlite3

from langchain_core.documents import Document

import config
from vectorstore import rebuild_collection

COLLECTION = "tickets"


def load() -> tuple[list[Document], list[str]]:
    con = sqlite3.connect(config.TICKETS_DB)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT ticket_id, category, issue_type, description, resolution "
                       "FROM tickets WHERE status = 'resolved' ORDER BY ticket_id").fetchall()
    con.close()
    docs, ids = [], []
    for r in rows:
        docs.append(Document(
            page_content=(f"Issue: {r['issue_type']}\nProblem: {r['description']}\n"
                          f"Resolution: {r['resolution']}"),
            metadata={"source": "TICKET", "id": r["ticket_id"], "category": r["category"],
                      "title": r["issue_type"]},
        ))
        ids.append(f"ticket-{r['ticket_id']}")
    return docs, ids


def main() -> None:
    docs, ids = load()
    n = rebuild_collection(COLLECTION, docs, ids)
    print(f"tickets: ingested {n} resolved tickets")


if __name__ == "__main__":
    main()
