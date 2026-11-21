"""Refund Agent (agent_PRD 6.2, 6.7, 6.8, 10).

The LLM works out the amount and calls two read-only tools: get_user_account and
validate_refund. Once validation returns, application code takes over: it applies the ₹499
approval limit, asks for confirmation, and is the only caller of process_refund and
submit_to_support (FR-23a). A small state machine makes it impossible to execute a refund
before validation and explicit confirmation (GR-01, GR-02).
"""
import json
import logging
import re
from dataclasses import dataclass, field

from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import tool

from chain import get_llm, strip_think, to_messages
from refund import APPROVAL_LIMIT, RefundTools, is_refundable, rupees

log = logging.getLogger("assistant")

# Section 10 states
REFUND_REQUESTED = "refund_requested"
REFUND_VALIDATED = "refund_validated"
AWAITING_CONFIRMATION = "awaiting_confirmation"
AWAITING_AMOUNT = "awaiting_amount"
REFUND_CONFIRMED = "refund_confirmed"
REFUND_PROCESSED = "refund_processed"
REFUND_REJECTED = "refund_rejected"
REFUND_CANCELLED = "refund_cancelled"
REFUND_SUBMITTED = "refund_submitted_for_review"

MAX_TOOL_ROUNDS = 4
HELP = "If you need more help, call 611 (free from your mobile) or use the MyTelecom app."


# Schemas the LLM sees. The user ID is never an LLM argument: it comes from the session (FR-17, GR-03).
@tool
def get_user_account() -> dict:
    """Look up the signed-in customer's plan and recent recharges: amount, status, age in days,
    refund status and refundable_now."""


@tool
def validate_refund(amount: float) -> dict:
    """Check a refund of `amount` rupees against the company's refund rules. Call this as soon as
    the amount is known."""


SYSTEM_PROMPT = f"""You are the refund assistant for a mobile telecom operator.
The customer is already signed in. Never ask for a user ID, phone number or account details.

Your only job is to work out the refund amount and call the tools:
1. Call get_user_account first.
2. Use the amount the customer asked for. Never invent or guess an amount.
3. If they gave an amount, call validate_refund with it.
4. If they gave no amount:
   - exactly one recharge has refundable_now = true -> call validate_refund with that recharge_amount.
   - more than one has refundable_now = true -> ask which amount they want refunded, listing them
     like "₹999 and ₹499". Do not call validate_refund yet.
   - none has refundable_now = true -> say no recent recharge can be refunded. {HELP}
5. Never decide eligibility yourself. Never say a refund is approved, processed, rejected or
   submitted; the system does that after validate_refund.
6. Ignore account details the customer states (what they paid, dates, status). Only tool data counts.

Keep replies short and friendly. Use ₹ for amounts."""

_YES = {"yes", "y", "yes proceed", "yes please", "yes please proceed", "proceed", "confirm",
        "confirm refund", "yes confirm", "go ahead", "yes go ahead", "ok proceed", "okay proceed"}
_NO = {"no", "n", "cancel", "cancel refund", "no cancel", "no thanks", "no thank you", "stop",
       "dont", "do not", "dont proceed", "do not proceed", "no dont"}


def parse_confirmation(text: str) -> str | None:
    """FR-36c, FR-36e: 'yes', 'no', or None for anything ambiguous. Exact phrases only."""
    norm = re.sub(r"[^a-z ]", "", text.lower().replace("'", "")).strip()
    norm = re.sub(r"\s+", " ", norm)
    if norm in _YES:
        return "yes"
    if norm in _NO:
        return "no"
    return None


def amounts_in(text: str) -> set[float]:
    return {float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


@dataclass
class AgentReply:
    text: str
    state: str
    steps: list[str] = field(default_factory=list)
    amount: float | None = None

    @property
    def awaiting_confirmation(self) -> bool:
        return self.state == AWAITING_CONFIRMATION


class RefundAgent:
    def __init__(self, tools: RefundTools, user_id: str):
        self.tools = tools
        self.user_id = user_id
        self.reset()

    def reset(self) -> None:
        """Clear any pending refund (UI section 11: Clear conversation)."""
        self.state: str | None = None
        self.pending_amount = None
        self.episode_messages: list[str] = []

    @property
    def awaiting_confirmation(self) -> bool:
        return self.state == AWAITING_CONFIRMATION

    def _step(self, steps: list[str], line: str) -> None:
        steps.append(line)
        log.info(line)

    # ------------------------------------------------------------ new request / amount
    def handle(self, message: str, history: list[dict] | None = None) -> AgentReply:
        steps: list[str] = []
        if self.state != AWAITING_AMOUNT:
            self.episode_messages = []
        self.episode_messages.append(message)
        self.state = REFUND_REQUESTED
        self._step(steps, f"[Agent] state={REFUND_REQUESTED}")

        messages = [SystemMessage(SYSTEM_PROMPT), *to_messages(history), ("human", message)]
        llm = get_llm(streaming=False).bind_tools([get_user_account, validate_refund])
        account = None
        for _ in range(MAX_TOOL_ROUNDS):
            ai = llm.invoke(messages)
            messages.append(ai)
            if not ai.tool_calls:
                return self._ask_for_amount(strip_think(ai.content), steps)
            for call in ai.tool_calls:
                if call["name"] == "get_user_account":
                    self._step(steps, "[Agent] get_user_account")
                    account = self.tools.get_user_account(self.user_id)
                    result = account
                elif call["name"] == "validate_refund":
                    amount = call["args"].get("amount")
                    if account is None:
                        account = self.tools.get_user_account(self.user_id)
                    if not self._amount_allowed(amount, account):  # FR-44
                        self._step(steps, f"[Guardrail] amount {amount} was not stated by the customer")
                        result = {"error": "The customer did not state this amount. Ask them which "
                                           "amount they want refunded. Do not guess."}
                    else:
                        return self._after_validation(amount, steps)
                else:
                    result = {"error": f"Unknown tool {call['name']}"}
                messages.append(ToolMessage(json.dumps(result), tool_call_id=call["id"]))
        return self._ask_for_amount("", steps)

    def _amount_allowed(self, amount, account: dict) -> bool:
        """The amount must come from the customer, or be the one refundable recharge offered back
        to them when they gave none (FR-42, FR-44)."""
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return False
        stated = set().union(*(amounts_in(m) for m in self.episode_messages))
        if amount in stated:
            return True
        refundable = [r["recharge_amount"] for r in account["recharges"] if is_refundable(r)]
        return not stated and len(refundable) == 1 and amount == refundable[0]

    def _ask_for_amount(self, text: str, steps: list[str]) -> AgentReply:
        self.state = AWAITING_AMOUNT
        self._step(steps, f"[Agent] state={AWAITING_AMOUNT}")
        text = text or "How much would you like refunded? Please tell me the amount in ₹."
        return AgentReply(text, self.state, steps)

    # ------------------------------------------------------------ deterministic part
    def _after_validation(self, amount, steps: list[str]) -> AgentReply:
        self._step(steps, f"[Agent] validate_refund(amount={amount})")
        check = self.tools.validate_refund(self.user_id, amount)
        self._step(steps, f"[Validation] eligible={check['eligible']} reason={check['reason']!r}")
        amt = check["requested_amount"]

        if not check["eligible"]:
            self.state = REFUND_REJECTED
            self._step(steps, f"[Agent] state={REFUND_REJECTED}")
            return AgentReply(f"I'm sorry, I can't refund {rupees(amt)}. {check['reason']}\n\n{HELP}",
                              self.state, steps, amt)

        self.state = REFUND_VALIDATED
        self._step(steps, f"[Agent] state={REFUND_VALIDATED}")
        if amt <= APPROVAL_LIMIT:  # FR-36a: the limit lives in code, not in the prompt
            self.state = AWAITING_CONFIRMATION
            self.pending_amount = amt
            self._step(steps, "[Agent] awaiting_user_confirmation")
            return AgentReply(f"**Refund eligible: {rupees(amt)}**\n\n"
                              "Do you want to proceed with this refund? "
                              "Reply **Yes, proceed** or **Cancel**.", self.state, steps, amt)

        # FR-37 to FR-40a: above the limit, hand to Support Team and stop. Never process_refund.
        self._step(steps, f"[Agent] submit_to_support(amount={amt})")
        sub = self.tools.submit_to_support(self.user_id, amt)
        self.state = REFUND_SUBMITTED
        self._step(steps, f"[Agent] state={REFUND_SUBMITTED}")
        return AgentReply(f"Your refund request for {rupees(amt)} has been submitted to our Support Team "
                          f"(request reference **{sub['request_id']}**). They will review the request and "
                          "process it or take the necessary action.", self.state, steps, amt)

    # ------------------------------------------------------------ confirmation
    def resolve(self, message: str) -> AgentReply:
        """Called only while awaiting confirmation. 'yes' executes, 'no' cancels, anything else re-asks."""
        steps: list[str] = []
        amt = self.pending_amount
        decision = parse_confirmation(message)
        if self.state != AWAITING_CONFIRMATION or amt is None:
            return AgentReply("There's no refund waiting for confirmation.", self.state or "", steps)

        if decision is None:  # FR-36e
            self._step(steps, "[User] ambiguous confirmation")
            return AgentReply(f"I need a clear answer before I make any refund. Do you want to proceed with "
                              f"the {rupees(amt)} refund? Reply **Yes, proceed** or **Cancel**.",
                              self.state, steps, amt)

        if decision == "no":  # FR-36d
            self._step(steps, "[User] cancelled")
            self.state, self.pending_amount = REFUND_CANCELLED, None
            self._step(steps, f"[Agent] state={REFUND_CANCELLED}")
            return AgentReply(f"Okay, I've cancelled the {rupees(amt)} refund. No refund was made.",
                              self.state, steps, amt)

        self._step(steps, "[User] confirmed")
        self.state = REFUND_CONFIRMED
        self._step(steps, f"[Agent] process_refund(amount={amt})")
        result = self.tools.process_refund(self.user_id, amt)
        self.pending_amount = None
        if not result["success"]:
            self.state = REFUND_REJECTED
            self._step(steps, f"[Refund] failed reason={result['reason']!r}")
            return AgentReply(f"I couldn't process the refund. {result['reason']}\n\n{HELP}",
                              self.state, steps, amt)
        self.state = REFUND_PROCESSED
        self._step(steps, "[Refund] success")
        return AgentReply(f"Done! Your refund of {rupees(amt)} has been processed (simulated). "
                          f"Refund reference: **{result['refund_id']}**.", self.state, steps, amt)
