"""Simulated accounts and refund tools (agent_PRD 6.3-6.7).

Everything here is deterministic application code. The LLM never decides eligibility
(FR-29, FR-30) and no real billing or payment system is called (FR-35, GR-07).
"""
import copy
import uuid

APPROVAL_LIMIT = 499       # FR-36: refunds at or below this need user confirmation; above go to support
REFUND_WINDOW_DAYS = 7     # FR-25

# The hard-coded user stands in for the signed-in session user (FR-15, FR-16).
DEMO_USER_ID = "user_123"

# FR-14, FR-18, FR-18a. user_234 exists only to demo the 7-day window (Scenario 3).
USERS = {
    "user_123": {
        "name": "Rahul",
        "plan": "Pro",
        "plan_amount": 999,
        "recharges": [
            {"recharge_id": "rch_456", "recharge_amount": 999, "recharge_status": "completed",
             "recharge_age_days": 2, "refund_status": "not_refunded"},
            {"recharge_id": "rch_457", "recharge_amount": 499, "recharge_status": "completed",
             "recharge_age_days": 1, "refund_status": "not_refunded"},
        ],
    },
    "user_234": {
        "name": "Priya",
        "plan": "Basic",
        "plan_amount": 299,
        "recharges": [
            {"recharge_id": "rch_610", "recharge_amount": 299, "recharge_status": "completed",
             "recharge_age_days": 15, "refund_status": "not_refunded"},
        ],
    },
}


def _num(amount):
    """Show 499.0 as 499."""
    return int(amount) if float(amount).is_integer() else round(float(amount), 2)


def rupees(amount) -> str:
    return f"₹{_num(amount):,}"


def is_refundable(r: dict) -> bool:
    return (r["recharge_status"] == "completed" and r["recharge_age_days"] <= REFUND_WINDOW_DAYS
            and r["refund_status"] != "refunded")


def select_recharge(recharges: list[dict], amount: float) -> dict | None:
    """FR-27a: pick the recharge a refund applies to, deterministically.

    An exact amount match wins, even if that recharge is already refunded. Otherwise use the
    recharges large enough to cover the amount, preferring refundable then most recent. If the
    amount is larger than every recharge, use the largest so the rejection names it.
    """
    if not recharges:
        return None
    pool = [r for r in recharges if r["recharge_amount"] == amount]
    pool = pool or [r for r in recharges if r["recharge_amount"] >= amount]
    if not pool:
        return max(recharges, key=lambda r: (r["recharge_amount"], -r["recharge_age_days"]))
    return min(pool, key=lambda r: (not is_refundable(r), r["recharge_age_days"], r["recharge_id"]))


class AccountStore:
    """A per-session copy of the simulated data, so refunds in one session don't leak into another."""

    def __init__(self):
        self.users = copy.deepcopy(USERS)
        self.support_requests: list[dict] = []


class RefundTools:
    """The four refund tools (FR-19 to FR-21a). Each returns a plain dict (FR-22).

    Only get_user_account and validate_refund are offered to the LLM. process_refund and
    submit_to_support are called by application code alone (FR-23a).
    """

    def __init__(self, store: AccountStore | None = None):
        self.store = store or AccountStore()

    def _account(self, user_id: str) -> dict:
        if user_id not in self.store.users:
            raise KeyError(f"Unknown user {user_id}")
        return self.store.users[user_id]

    def get_user_account(self, user_id: str) -> dict:
        a = self._account(user_id)
        return {
            "user_id": user_id, "name": a["name"], "plan": a["plan"], "plan_amount": a["plan_amount"],
            "recharges": [{**r, "refundable_now": is_refundable(r)} for r in a["recharges"]],
        }

    def validate_refund(self, user_id: str, amount) -> dict:
        """FR-24 to FR-28. Decides eligibility only; the approval limit is applied separately."""
        result = {"eligible": False, "reason": "", "requested_amount": amount,
                  "recharge_amount": None, "recharge_id": None}
        try:
            amount = _num(amount)
        except (TypeError, ValueError):
            return {**result, "reason": "The refund amount must be a number."}
        result["requested_amount"] = amount
        if amount <= 0:
            return {**result, "reason": "The refund amount must be greater than zero."}

        r = select_recharge(self._account(user_id)["recharges"], amount)
        if r is None:
            return {**result, "reason": "There are no recharges on this account."}
        result.update(recharge_amount=r["recharge_amount"], recharge_id=r["recharge_id"])

        if amount > r["recharge_amount"]:
            reason = (f"The requested amount ({rupees(amount)}) exceeds the recharge amount "
                      f"({rupees(r['recharge_amount'])}).")
        elif r["refund_status"] == "refunded":
            reason = f"The {rupees(r['recharge_amount'])} recharge has already been refunded."
        elif r["recharge_status"] != "completed":
            reason = f"The {rupees(r['recharge_amount'])} recharge is not completed, so it can't be refunded."
        elif r["recharge_age_days"] > REFUND_WINDOW_DAYS:
            reason = (f"The {rupees(r['recharge_amount'])} recharge was made {r['recharge_age_days']} days "
                      f"ago, outside the {REFUND_WINDOW_DAYS}-day refund window.")
        else:
            return {**result, "eligible": True, "reason": "Refund is eligible."}
        return {**result, "reason": reason}

    def process_refund(self, user_id: str, amount) -> dict:
        """Simulated refund (FR-23). Re-validates so it can never run on an invalid request (GR-01)."""
        check = self.validate_refund(user_id, amount)
        if not check["eligible"]:
            return {"success": False, "reason": check["reason"]}
        if check["requested_amount"] > APPROVAL_LIMIT:  # GR-08
            return {"success": False, "reason": "Refunds above the approval limit can't be processed here."}
        for r in self._account(user_id)["recharges"]:
            if r["recharge_id"] == check["recharge_id"]:
                r["refund_status"] = "refunded"  # FR-28a: the refund consumes the whole recharge
        return {"success": True, "refund_id": f"ref_{uuid.uuid4().hex[:6]}",
                "amount": check["requested_amount"], "recharge_id": check["recharge_id"],
                "status": "refunded"}

    def submit_to_support(self, user_id: str, amount) -> dict:
        """FR-38: hand a refund above the limit to the Support Team. Refund status is left unchanged."""
        check = self.validate_refund(user_id, amount)
        if not check["eligible"]:
            return {"submitted": False, "reason": check["reason"]}
        request = {"request_id": f"sup_{uuid.uuid4().hex[:6]}", "user_id": user_id,
                   "amount": check["requested_amount"], "recharge_id": check["recharge_id"],
                   "status": "submitted_for_review"}
        self.store.support_requests.append(request)
        return {"submitted": True, **request}
