"""Command-line chat (FR-18). Type 'quit' to exit (FR-19), 'clear' to reset the conversation.

Run:  .venv/bin/python main.py
"""
import time

from assistant import Assistant
from chain import MissingAPIKey, log_event, new_id
from retriever import missing_collections


def main() -> None:
    missing = missing_collections()
    if missing:
        print(f"The knowledge base is empty ({', '.join(missing)}). Run: python ingest_all.py")
        return
    session_id = new_id()
    assistant = Assistant()
    history: list[dict] = []
    print("US Telecom Customer Care Assistant. Ask a question, or type 'quit' to exit.\n")
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
        if question.lower() == "clear":
            history = []
            assistant.reset()
            print("Conversation cleared.\n")
            continue
        t0 = time.time()
        try:
            turn = assistant.respond(question, history)
            sources = turn.sources
            print("\nAssistant: ", end="", flush=True)
            answer = ""
            if turn.tokens is not None:
                for tok in turn.tokens:
                    answer += tok
                    print(tok, end="", flush=True)
                print("\n\nSources: " + ", ".join(f"{s['source']}:{s['id']}" for s in sources) + "\n")
            else:
                answer = turn.text
                print(answer.replace("**", "") + "\n")
        except MissingAPIKey as e:
            print(f"\n{e}")
            return
        except Exception as e:
            answer, sources = "", []
            print(f"\nSorry, something went wrong ({e}). Please try again, or call 611.\n")
        history += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        log_event({"type": "answer", "channel": "cli", "session_id": session_id, "question": question,
                   "answer": answer, "latency_s": round(time.time() - t0, 2),
                   "sources": [f"{s['source']}:{s['id']}" for s in sources]})
    print("Goodbye!")


if __name__ == "__main__":
    main()
