"""Command-line chat (FR-18). Type 'quit' to exit (FR-19).

Run:  .venv/bin/python main.py
"""
import time

from chain import MissingAPIKey, log_event, new_id, stream_answer
from retriever import missing_collections


def main() -> None:
    missing = missing_collections()
    if missing:
        print(f"The knowledge base is empty ({', '.join(missing)}). Run: python ingest_all.py")
        return
    session_id = new_id()
    print("Telecom Customer Care Assistant. Ask a question, or type 'quit' to exit.\n")
    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        if question.lower() == "quit":
            break
        t0 = time.time()
        try:
            sources, tokens = stream_answer(question)
            print("\nAssistant: ", end="", flush=True)
            answer = ""
            for tok in tokens:
                answer += tok
                print(tok, end="", flush=True)
            print("\n\nSources: " + ", ".join(f"{s['source']}:{s['id']}" for s in sources) + "\n")
        except MissingAPIKey as e:
            print(f"\n{e}")
            return
        except Exception as e:
            answer, sources = "", []
            print(f"\nSorry, something went wrong ({e}). Please try again, or call 611.\n")
        log_event({"type": "answer", "channel": "cli", "session_id": session_id, "question": question,
                   "answer": answer, "latency_s": round(time.time() - t0, 2),
                   "sources": [f"{s['source']}:{s['id']}" for s in sources]})
    print("Goodbye!")


if __name__ == "__main__":
    main()
