"""Convenience: run every ingest script. Each one is idempotent, so re-running is safe."""
import ingest_faq
import ingest_guides
import ingest_tickets

if __name__ == "__main__":
    ingest_faq.main()
    ingest_tickets.main()
    ingest_guides.main()
