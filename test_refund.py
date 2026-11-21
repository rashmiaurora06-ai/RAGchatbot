"""Deterministic checks for the refund rules and confirmation state machine (no LLM calls).

Run:  .venv/bin/python test_refund.py
"""
from refund import AccountStore, RefundTools, select_recharge
from refund_agent import AWAITING_CONFIRMATION, RefundAgent, parse_confirmation

U = "user_123"


def fresh():
    return RefundTools(AccountStore())


def test_validation_scenarios():
    t = fresh()
    ok = t.validate_refund(U, 100)                       # Scenario 1
    assert ok["eligible"] and ok["recharge_id"] == "rch_457", ok
    big = t.validate_refund(U, 2000)                     # Scenario 2
    assert not big["eligible"] and "exceeds" in big["reason"], big
    old = t.validate_refund("user_234", 50)             # Scenario 3
    assert not old["eligible"] and "7-day" in old["reason"], old
    assert not t.validate_refund(U, 0)["eligible"]
    assert not t.validate_refund(U, -5)["eligible"]
    six = t.validate_refund(U, 150)                      # Scenario 6 (eligible; limit applied elsewhere)
    assert six["eligible"] and six["recharge_id"] == "rch_456"


def test_process_and_already_refunded():
    t = fresh()
    r = t.process_refund(U, 100)
    assert r["success"] and r["refund_id"].startswith("ref_") and r["status"] == "refunded"
    again = t.validate_refund(U, 100)                    # Scenario 4: exact match, already refunded
    assert not again["eligible"] and "already been refunded" in again["reason"], again
    assert t.validate_refund(U, 150)["eligible"]         # the other recharge is still refundable


def test_limits_in_code():
    t = fresh()
    assert not t.process_refund(U, 150)["success"]       # GR-08: above limit never processed
    sub = t.submit_to_support(U, 150)
    assert sub["submitted"]
    assert t.get_user_account(U)["recharges"][0]["refund_status"] == "not_refunded"  # unchanged
    assert not t.process_refund(U, 2000)["success"]      # GR-01: invalid never processed


def test_recharge_selection():
    recs = fresh().get_user_account(U)["recharges"]
    assert select_recharge(recs, 80)["recharge_id"] == "rch_457"   # most recent that covers it
    assert select_recharge(recs, 120)["recharge_id"] == "rch_456"
    assert select_recharge(recs, 5000)["recharge_amount"] == 150


def test_confirmation_parser():
    for s in ["Yes, proceed", "yes", "Confirm", "go ahead!"]:
        assert parse_confirmation(s) == "yes", s
    for s in ["Cancel", "no", "No thanks", "don't"]:
        assert parse_confirmation(s) == "no", s
    for s in ["maybe", "yes but not now", "I guess", "sure, why not?", "what?"]:
        assert parse_confirmation(s) is None, s


def test_state_machine_needs_confirmation():
    t = fresh()
    a = RefundAgent(t, U)
    assert a.resolve("yes").text.startswith("There's no refund")          # nothing pending
    a._after_validation(100, [])
    assert a.state == AWAITING_CONFIRMATION
    assert t.get_user_account(U)["recharges"][1]["refund_status"] == "not_refunded"
    assert a.resolve("maybe").state == AWAITING_CONFIRMATION                # ambiguous: re-ask
    assert a.resolve("Cancel").state == "refund_cancelled"
    assert t.get_user_account(U)["recharges"][1]["refund_status"] == "not_refunded"
    a._after_validation(100, [])
    assert a.resolve("Yes, proceed").state == "refund_processed"
    assert t.get_user_account(U)["recharges"][1]["refund_status"] == "refunded"


def test_offered_amount_above_limit_needs_a_yes():
    t = fresh()
    a = RefundAgent(t, U)
    a.episode_messages = ["I want a refund."]
    reply = a._offer_amount(150, [])
    assert reply.state == "awaiting_amount" and not t.store.support_requests  # nothing submitted yet
    assert a.handle("Cancel").state == "refund_cancelled" and not t.store.support_requests
    a.state, a.offered_amount = "awaiting_amount", 150
    assert a.handle("Yes, proceed").state == "refund_submitted_for_review"
    assert len(t.store.support_requests) == 1


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(tests)} passed")
