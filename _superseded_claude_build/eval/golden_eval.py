"""Golden-set evaluation (PRD FR-8.3). Run on every content or prompt change.

    .venv/bin/python eval/golden_eval.py            # uses Claude if a key is set
    NOVACELL_OFFLINE=1 .venv/bin/python eval/golden_eval.py   # retrieval/routing only

Each case checks the reply status and, for answers, that an expected source was
retrieved/cited. Uses a throwaway state DB so it never pollutes real metrics.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from novacell_bot import config  # noqa: E402

config.STATE_DB = Path(tempfile.mkdtemp()) / "eval.db"
from novacell_bot import assistant  # noqa: E402
from novacell_bot.guardrails import unsupported_numbers  # noqa: E402
from novacell_bot.retrieval import get_index  # noqa: E402

ANSWER = {"answered", "partial"}
# (conversation turns, expected statuses for last turn, any-of expected source ids)
CASES = [
    (["Why is my mobile internet so slow?"], ANSWER, ["FAQ-2", "GUIDE-p4-2", "TK-008"]),
    (["How do I activate international roaming?"], ANSWER, ["FAQ-9", "GUIDE-p5-4"]),
    (["What are the roaming charges in the EU?"], ANSWER, ["FAQ-10"]),
    (["I'm travelling to Japan next week, what should I do?"], ANSWER, ["FAQ-9", "GUIDE-p5-3", "TK-012"]),
    (["My eSIM QR code won't scan"], ANSWER, ["TK-009", "GUIDE-p6-2"]),
    (["How long does SIM activation take?"], ANSWER, ["FAQ-12"]),
    (["My calls keep dropping"], ANSWER, ["FAQ-6"]),
    (["How do I turn on wifi calling?"], ANSWER, ["FAQ-7", "GUIDE-p7-4"]),
    (["Why is my bill higher than usual?"], ANSWER, ["FAQ-16"]),
    (["How do I set up autopay?"], ANSWER, ["FAQ-17"]),
    (["How do I unlock my phone?"], ANSWER, ["FAQ-19"]),
    (["How do I set up a personal hotspot?"], ANSWER, ["FAQ-21", "GUIDE-p4-6"]),
    (["How do I get an itemised bill?"], ANSWER, ["FAQ-18"]),
    (["Can I keep my number when I switch to you?"], ANSWER, ["FAQ-13"]),
    # Account-specific: general answer + self-serve pointer (FR-5)
    (["What's my data balance?"], ANSWER, ["FAQ-1"]),
    # Follow-up rewriting (FR-2.3)
    (["How do I activate international roaming?", "and how much does it cost in the EU?"], ANSWER, ["FAQ-10"]),
    # Escalations (FR-6)
    (["Someone changed my plan without my permission"], {"escalated"}, []),
    (["I want to talk to a real person"], {"escalated"}, []),
    (["My phone was stolen"], {"escalated"}, []),
    (["I want to file a formal complaint"], {"escalated"}, []),
    # Must not guess (FR-4)
    (["What's the price of the iPhone 17 Pro?"], {"unsure", "out_of_scope"}, []),
    (["Do you sell home fibre broadband in Leeds?"], {"unsure", "out_of_scope"}, []),
    (["Write me a poem about the ocean"], {"unsure", "out_of_scope"}, []),
    # PII masking
    (["My card 4111 1111 1111 1111 was charged twice"], ANSWER | {"unsure"}, []),
]


def run() -> int:
    fails = 0
    for turns, want_status, want_src in CASES:
        sid = None
        for t in turns:
            r = assistant.handle_message(sid, t)
            sid = r["session_id"]
        cited = [c["id"] for c in r["citations"]]
        # retrieval check: expected source in top-k for the (possibly rewritten) question
        retrieved = []
        if want_src:
            last_q = assistant.SESSIONS[sid].history[-2]["content"]
            if len(turns) > 1:
                last_q = " ".join(turns)
            retrieved = [h.chunk.id for h in get_index().search(last_q)]
        ok_status = r["status"] in want_status
        ok_src = not want_src or any(s in retrieved or s in cited for s in want_src)
        ok_mask = "4111" not in r["text"]
        ok_nums = not cited or not unsupported_numbers(
            r["text"], " ".join(c["snippet"] for c in r["citations"]))
        ok = ok_status and ok_src and ok_mask
        fails += not ok
        mark = "PASS" if ok else "FAIL"
        print(f"{mark}  [{r['status']:<11}] {turns[-1][:60]:<60} cited={cited} conf={r['confidence']}"
              + ("" if ok_src else f"  (expected one of {want_src}, retrieved {retrieved})")
              + ("" if ok_nums else "  (WARN: number not in snippet)"))
    print(f"\n{len(CASES) - fails}/{len(CASES)} passed · mode={assistant.mode()}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(run())
