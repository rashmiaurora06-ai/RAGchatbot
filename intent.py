"""Intent detection (agent_PRD 6.1): requirement_inquiry or refund_request."""
import logging
from typing import Literal

from langchain_core.messages import SystemMessage
from pydantic import BaseModel, Field

from chain import get_llm, to_messages

log = logging.getLogger("assistant")

REQUIREMENT_INQUIRY = "requirement_inquiry"
REFUND_REQUEST = "refund_request"


class Intent(BaseModel):
    """The intent of the customer's latest message."""
    intent: Literal["requirement_inquiry", "refund_request"] = Field(
        description="refund_request if the customer wants money back for a recharge now; "
                    "requirement_inquiry for any question or help request.")


PROMPT = """You classify the customer's LATEST message for a mobile telecom support chat.

- refund_request: the customer wants a refund, or wants a recharge cancelled or reversed, now.
  Also refund_request when the assistant just asked about a refund (which amount, or whether to
  proceed) and the customer is answering that, e.g. "the $100 one" or "$150".
- requirement_inquiry: everything else, including questions ABOUT refunds or cancellations
  (e.g. "How do I cancel a recharge?", "What is the refund policy?") and all support questions.

Earlier messages are context only. Classify the latest message."""


def classify(message: str, history: list[dict] | None = None) -> str:
    """FR-01, FR-04, FR-05: structured intent from the existing LLM configuration."""
    llm = get_llm(streaming=False).with_structured_output(Intent)
    try:
        result = llm.invoke([SystemMessage(PROMPT), *to_messages(history),
                             ("human", f"Latest message to classify:\n{message}")])
        return result.intent
    except Exception as e:  # noqa: BLE001 - a failed classifier must not block support answers
        log.warning("[Intent] classifier failed (%r); defaulting to requirement_inquiry", e)
        return REQUIREMENT_INQUIRY
