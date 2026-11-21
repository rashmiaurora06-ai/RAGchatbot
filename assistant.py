"""Routes each message: intent detection -> existing RAG pipeline or Refund Agent (agent_PRD 7).

Shared by the Streamlit app (app.py) and the CLI (main.py).
"""
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field

from chain import stream_answer
from intent import REFUND_REQUEST, REQUIREMENT_INQUIRY, classify
from refund import DEMO_USER_ID, AccountStore, RefundTools
from refund_agent import RefundAgent, parse_confirmation

log = logging.getLogger("assistant")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(message)s")


@dataclass
class Turn:
    intent: str
    steps: list[str] = field(default_factory=list)
    # requirement_inquiry: sources + streamed tokens from the existing RAG chain
    sources: list[dict] = field(default_factory=list)
    tokens: Iterator[str] | None = None
    # refund_request: a finished reply from the Refund Agent
    text: str = ""
    state: str = ""
    awaiting_confirmation: bool = False


class Assistant:
    def __init__(self, user_id: str = DEMO_USER_ID):
        self.user_id = user_id  # stands in for the authenticated session user (FR-16)
        self.tools = RefundTools(AccountStore())
        self.agent = RefundAgent(self.tools, user_id)

    def reset(self) -> None:
        """Clear conversation: drops any pending refund. Simulated account data is kept."""
        self.agent.reset()

    @property
    def pending_refund(self):
        return self.agent.pending_amount if self.agent.awaiting_confirmation else None

    def respond(self, message: str, history: list[dict] | None = None) -> Turn:
        # A clear yes/no while a refund is waiting goes straight to the agent's state machine.
        if self.agent.awaiting_confirmation and parse_confirmation(message):
            return self._refund_turn(self.agent.resolve(message), ["[Intent] refund_confirmation"])

        intent = classify(message, history)
        steps = [f"[Intent] {intent}"]
        log.info(steps[0])

        if intent == REFUND_REQUEST:
            reply = (self.agent.resolve(message) if self.agent.awaiting_confirmation  # ambiguous -> re-ask
                     else self.agent.handle(message, history))
            return self._refund_turn(reply, steps)

        sources, tokens = stream_answer(message, history)  # existing RAG pipeline, unchanged
        return Turn(intent=REQUIREMENT_INQUIRY, steps=steps, sources=sources, tokens=tokens,
                    awaiting_confirmation=self.agent.awaiting_confirmation)

    @staticmethod
    def _refund_turn(reply, steps: list[str]) -> Turn:
        return Turn(intent=REFUND_REQUEST, steps=steps + reply.steps, text=reply.text,
                    state=reply.state, awaiting_confirmation=reply.awaiting_confirmation)
