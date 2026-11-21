"""Checks for accounts, persisted refunds and chat history, on a temporary database (no LLM calls).

Run:  .venv/bin/python test_db.py
"""
import os
import tempfile

os.environ["APP_DB"] = os.path.join(tempfile.mkdtemp(), "test_app.db")

import db  # noqa: E402  (APP_DB must be set first)
from refund import RefundTools  # noqa: E402
from refund_agent import RefundAgent  # noqa: E402

db.init()
PW = "correct horse battery"


def test_signup_and_signin():
    u = db.create_user("Alex@Example.com ", "Alex", PW)
    assert u["email"] == "alex@example.com"
    assert db.authenticate("ALEX@example.com", PW)["id"] == u["id"]
    for bad in [("alex@example.com", "wrong password"), ("nobody@example.com", PW)]:
        try:
            db.authenticate(*bad)
            raise AssertionError("should fail")
        except db.AuthError as e:
            assert str(e) == "Email or password is incorrect."


def test_signup_validation():
    for args in [("not-an-email", "X", PW), ("x@example.com", "", PW), ("x@example.com", "X", "short"),
                 ("alex@example.com", "Alex again", PW)]:
        try:
            db.create_user(*args)
            raise AssertionError(f"should fail: {args}")
        except db.AuthError:
            pass


def test_password_is_hashed_and_changeable():
    u = db.authenticate("alex@example.com", PW)
    with db.connect() as con:
        stored = con.execute("SELECT password_hash FROM users WHERE id = ?", (u["id"],)).fetchone()[0]
    assert PW not in stored and stored.startswith("scrypt$")
    db.change_password(u["id"], PW, "a new long password")
    db.authenticate("alex@example.com", "a new long password")
    db.change_password(u["id"], "a new long password", PW)


def test_refunds_persist_per_user():
    alex = db.authenticate("alex@example.com", PW)
    sam = db.create_user("sam@example.com", "Sam", PW)
    store = db.DbAccountStore(alex["id"])
    agent = RefundAgent(RefundTools(store), store.key)
    agent._after_validation(100, [])
    assert agent.resolve("Credit to future bills").state == "refund_processed"
    agent._after_validation(150, [])
    assert agent.resolve("Refund to original payment").state == "refund_submitted_for_review"

    fresh = db.DbAccountStore(alex["id"])            # as after signing in again
    acct = RefundTools(fresh).get_user_account(fresh.key)
    assert acct["bill_credit_balance"] == 100 and acct["recharges"][1]["refund_status"] == "refunded"
    assert len(fresh.support_requests) == 1
    other = db.DbAccountStore(sam["id"])             # another user is untouched
    assert RefundTools(other).get_user_account(other.key)["bill_credit_balance"] == 0
    assert other.support_requests == []


def test_chat_history_is_private():
    alex = db.authenticate("alex@example.com", PW)
    sam = db.authenticate("sam@example.com", PW)
    cid = db.create_conversation(alex["id"], "How do I activate an eSIM?")
    db.add_message(cid, alex["id"], "user", "How do I activate an eSIM?")
    db.add_message(cid, alex["id"], "assistant", "Open the MyTelecom app…", message_key="m1",
                   intent="requirement_inquiry", sources=[{"source": "FAQ", "id": "FAQ-10"}])
    db.set_rating(alex["id"], "m1", "up")
    msgs = db.get_messages(cid, alex["id"])
    assert [m["role"] for m in msgs] == ["user", "assistant"] and msgs[1]["rating"] == "up"
    assert db.list_conversations(alex["id"])[0]["title"] == "How do I activate an eSIM?"
    assert db.get_messages(cid, sam["id"]) == [] and db.list_conversations(sam["id"]) == []
    try:
        db.add_message(cid, sam["id"], "user", "sneaky")
        raise AssertionError("should fail")
    except PermissionError:
        pass
    db.delete_conversation(cid, sam["id"])           # not Sam's: nothing happens
    assert db.get_messages(cid, alex["id"])
    db.delete_conversation(cid, alex["id"])
    assert db.list_conversations(alex["id"]) == []


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(tests)} passed")
