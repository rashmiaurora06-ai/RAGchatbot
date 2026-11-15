"""Deterministic guardrails: PII masking, safety/escalation signals, and answer checks.

These run regardless of what the language model says, so the most important PRD
rules (no invented numbers, no promised credits, fraud always goes to a human,
never collect secrets) do not depend on model behaviour.
"""
from __future__ import annotations

import re

# ---- PII masking (FR-1.5, FR-5.4) ------------------------------------------
_PII_PATTERNS = [
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[card number removed]"),
    (re.compile(r"\b\d{15}\b"), "[IMEI/IMSI removed]"),
    (re.compile(r"\b89\d{17,20}\b"), "[SIM serial removed]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email removed]"),
    (re.compile(r"(?<!\w)\+?\d[\d ()-]{8,}\d"), "[phone number removed]"),
    (re.compile(r"\b(?:\d{1,2}[/.-]){2}\d{2,4}\b"), "[date removed]"),
    (re.compile(r"(?i)\b(password|passcode|pin|puk)\s*(is|:|=)\s*\S+"), r"\1 [removed]"),
]


def mask_pii(text: str) -> str:
    for pat, repl in _PII_PATTERNS:
        text = pat.sub(repl, text)
    return text


def contains_secret(text: str) -> bool:
    return mask_pii(text) != text


# ---- Escalation / intent signals (FR-6) -----------------------------------
_EMERGENCY = re.compile(r"(?i)\b(911|999|112|emergency services|ambulance|suicid|overdose|someone is hurt)\b")
_HUMAN = re.compile(r"(?i)\b(human|real person|live agent|an agent|talk to (?:a |an )?(?:person|someone|agent)|"
                    r"speak to (?:a |an )?(?:person|someone|agent|representative)|representative|operator)\b")
_FRAUD = re.compile(
    r"(?i)(unauthori[sz]ed|without my (?:permission|consent|authori[sz]ation)|didn'?t (?:make|authori[sz]e)|"
    r"hack(?:ed|er)?|account (?:was )?(?:compromised|taken over)|someone (?:else )?(?:logged|changed|ported|swapped)|"
    r"sim swap|identity theft|scam(?:med)?|fraud|stolen (?:phone|sim|device)|phone (?:was |got )?stolen|"
    r"lost my (?:phone|sim))"
)
_COMPLAINT = re.compile(r"(?i)\b(formal complaint|file a complaint|ombudsman|regulator|lawyer|legal action|"
                        r"cancel (?:my )?(?:contract|account|service)|terminate my contract)\b")
_FRUSTRATION = re.compile(r"(?i)(useless|ridiculous|this is not helping|not helpful|waste of time|"
                          r"terrible|worst|fed up|so frustrat|angry|!!!)")
_ACCOUNT = re.compile(
    r"(?i)\b(my (?:balance|bill|invoice|charges?|account|plan|usage|data (?:balance|left)|due date|payment|"
    r"contract|number|roaming (?:status)?)|(?:was|am|got) i (?:charged|billed)|charged me|"
    r"how much (?:data|credit) (?:do i have|is left)|is my \w+ (?:on|active|enabled))\b"
)
_TRANSACTION = re.compile(
    r"(?i)\b(refund|credit (?:me|my account)|reverse (?:the|this) charge|change my plan for me|"
    r"upgrade me|cancel (?:my|the) (?:add-?on|bundle|subscription)|unlock my phone for me|"
    r"(?:activate|turn on|enable) (?:it|roaming|this) for me|port my number for me|send me a new (?:sim|qr))\b"
)


def detect_signals(text: str) -> dict:
    return {
        "emergency": bool(_EMERGENCY.search(text)),
        "wants_human": bool(_HUMAN.search(text)),
        "fraud": bool(_FRAUD.search(text)),
        "complaint": bool(_COMPLAINT.search(text)),
        "frustrated": bool(_FRUSTRATION.search(text)),
        "account_specific": bool(_ACCOUNT.search(text)),
        "transactional": bool(_TRANSACTION.search(text)),
        "shared_secret": contains_secret(text),
    }


# ---- Answer checks (FR-3.2, FR-3.6) ---------------------------------------
_NUM = re.compile(r"\$?\d+(?:[.,]\d+)?")
_PROMISE = re.compile(
    r"(?i)\b(i(?:'ve| have)? (?:issued|applied|refunded|credited|processed|reversed|activated|changed)|"
    r"we(?:'ll| will) (?:refund|credit|waive|compensate|reimburse)|you(?:'ll| will) (?:get|receive) (?:a )?"
    r"(?:refund|credit|compensation|goodwill)|(?:refund|credit) (?:has been|is being) (?:issued|applied))\b"
)


def _norm_num(tok: str) -> str:
    return tok.replace("$", "").replace(",", "")


def unsupported_numbers(answer: str, source_text: str) -> list[str]:
    """Numbers in the answer that don't appear in the sources it relied on.

    Single digits are ignored (they're nearly always step numbers like "1)").
    """
    src = {_norm_num(t) for t in _NUM.findall(source_text)}
    bad = []
    for tok in _NUM.findall(answer):
        n = _norm_num(tok)
        if len(n.replace(".", "")) < 2 and not tok.startswith("$"):
            continue
        if n not in src:
            bad.append(tok)
    return sorted(set(bad))


def makes_promise(answer: str) -> bool:
    return bool(_PROMISE.search(answer))
