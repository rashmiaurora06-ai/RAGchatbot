"""App database (SQLite, standard library only): users, their billing accounts, and chat history.

The file lives at data/app.db (set APP_DB to use another file, e.g. for tests) and is not in git.
Passwords are stored only as salted scrypt hashes.
"""
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager

import config
from refund import DEMO_USER_ID, USERS, AccountStore

MIN_PASSWORD_LENGTH = 8
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT UNIQUE NOT NULL,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS billing_accounts (
    user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    data       TEXT NOT NULL,          -- plan, recharges and bill credit balance (JSON)
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS support_requests (
    request_id       TEXT PRIMARY KEY,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount           REAL NOT NULL,
    recharge_id      TEXT NOT NULL,
    preferred_method TEXT NOT NULL,
    status           TEXT NOT NULL,
    created_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_key     TEXT,               -- the id used for feedback in the UI and the interaction log
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    intent          TEXT,
    sources         TEXT,               -- JSON list
    steps           TEXT,               -- JSON list
    rating          TEXT CHECK (rating IN ('up', 'down')),
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);
"""


def db_path() -> str:
    return os.environ.get("APP_DB") or str(config.DATA_DIR / "app.db")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


@contextmanager
def connect():
    con = sqlite3.connect(db_path())
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    with connect() as con:
        con.executescript(SCHEMA)


# ---------------------------------------------------------------- passwords

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(digest.hex(), digest_hex)


# ---------------------------------------------------------------- users

class AuthError(ValueError):
    """A message that is safe to show to the person signing up or in."""


def _user(row) -> dict:
    return {"id": row["id"], "email": row["email"], "name": row["name"]}


def create_user(email: str, name: str, password: str) -> dict:
    email, name = email.strip().lower(), name.strip()
    if not _EMAIL.match(email):
        raise AuthError("Enter a valid email address.")
    if not name:
        raise AuthError("Enter your name.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Use a password of at least {MIN_PASSWORD_LENGTH} characters.")
    with connect() as con:
        if con.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise AuthError("An account with this email already exists. Sign in instead.")
        cur = con.execute("INSERT INTO users (email, name, password_hash, created_at) VALUES (?, ?, ?, ?)",
                          (email, name, hash_password(password), _now()))
        user_id = cur.lastrowid
        # Every new customer gets a simulated billing account shaped like the PRD's demo user.
        account = copy.deepcopy(USERS[DEMO_USER_ID])
        account["name"] = name
        con.execute("INSERT INTO billing_accounts (user_id, data, updated_at) VALUES (?, ?, ?)",
                    (user_id, json.dumps(account), _now()))
        row = con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _user(row)


def authenticate(email: str, password: str) -> dict:
    with connect() as con:
        row = con.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            raise AuthError("Email or password is incorrect.")  # same message either way
        con.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (_now(), row["id"]))
    return _user(row)


def change_password(user_id: int, current: str, new: str) -> None:
    if len(new) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Use a password of at least {MIN_PASSWORD_LENGTH} characters.")
    with connect() as con:
        row = con.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None or not verify_password(current, row["password_hash"]):
            raise AuthError("Your current password is incorrect.")
        con.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new), user_id))


# ---------------------------------------------------------------- billing accounts

def load_account(user_id: int) -> dict:
    with connect() as con:
        row = con.execute("SELECT data FROM billing_accounts WHERE user_id = ?", (user_id,)).fetchone()
    return json.loads(row["data"])


def save_account(user_id: int, data: dict) -> None:
    with connect() as con:
        con.execute("UPDATE billing_accounts SET data = ?, updated_at = ? WHERE user_id = ?",
                    (json.dumps(data), _now(), user_id))


def add_support_request(user_id: int, req: dict) -> None:
    with connect() as con:
        con.execute("INSERT INTO support_requests (request_id, user_id, amount, recharge_id, preferred_method, "
                    "status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (req["request_id"], user_id, req["amount"], req["recharge_id"], req["preferred_method"],
                     req["status"], _now()))


def load_support_requests(user_id: int) -> list[dict]:
    with connect() as con:
        rows = con.execute("SELECT * FROM support_requests WHERE user_id = ? ORDER BY created_at",
                           (user_id,)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- chat history

def create_conversation(user_id: int, first_message: str) -> int:
    title = first_message.strip().replace("\n", " ")
    title = title if len(title) <= 50 else title[:47] + "…"
    with connect() as con:
        cur = con.execute("INSERT INTO conversations (user_id, title, created_at, updated_at) "
                          "VALUES (?, ?, ?, ?)", (user_id, title, _now(), _now()))
        return cur.lastrowid


def list_conversations(user_id: int, limit: int = 30) -> list[dict]:
    with connect() as con:
        rows = con.execute("SELECT id, title, updated_at FROM conversations WHERE user_id = ? "
                           "ORDER BY updated_at DESC, id DESC LIMIT ?", (user_id, limit)).fetchall()
    return [dict(r) for r in rows]


def add_message(conversation_id: int, user_id: int, role: str, content: str, *, message_key: str | None = None,
                intent: str | None = None, sources: list | None = None, steps: list | None = None) -> None:
    with connect() as con:
        owner = con.execute("SELECT user_id FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        if owner is None or owner["user_id"] != user_id:
            raise PermissionError("Conversation not found for this user.")
        con.execute("INSERT INTO messages (conversation_id, message_key, role, content, intent, sources, steps, "
                    "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (conversation_id, message_key, role, content, intent, json.dumps(sources or []),
                     json.dumps(steps or []), _now()))
        con.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (_now(), conversation_id))


def get_messages(conversation_id: int, user_id: int) -> list[dict]:
    """Messages of one conversation, only if it belongs to this user."""
    with connect() as con:
        rows = con.execute("SELECT m.* FROM messages m JOIN conversations c ON c.id = m.conversation_id "
                           "WHERE m.conversation_id = ? AND c.user_id = ? ORDER BY m.id",
                           (conversation_id, user_id)).fetchall()
    return [{"role": r["role"], "content": r["content"], "id": r["message_key"], "intent": r["intent"],
             "sources": json.loads(r["sources"] or "[]"), "steps": json.loads(r["steps"] or "[]"),
             "rating": r["rating"]} for r in rows]


def set_rating(user_id: int, message_key: str, rating: str | None) -> None:
    with connect() as con:
        con.execute("UPDATE messages SET rating = ? WHERE message_key = ? AND conversation_id IN "
                    "(SELECT id FROM conversations WHERE user_id = ?)", (rating, message_key, user_id))


def delete_conversation(conversation_id: int, user_id: int) -> None:
    with connect() as con:
        con.execute("DELETE FROM conversations WHERE id = ? AND user_id = ?", (conversation_id, user_id))


class DbAccountStore(AccountStore):
    """The refund tools' account store for one signed-in user, loaded from and saved to the database.

    The refund code addresses accounts by a string key; here it is "user-<id>".
    """

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.key = f"user-{user_id}"
        self.users = {self.key: load_account(user_id)}
        self.support_requests = load_support_requests(user_id)

    def saved(self, user_key: str) -> None:
        save_account(self.user_id, self.users[self.key])

    def record_support_request(self, user_key: str, request: dict) -> None:
        add_support_request(self.user_id, request)
        self.support_requests.append(request)
