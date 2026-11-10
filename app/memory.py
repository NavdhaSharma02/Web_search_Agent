"""Local memory is application state, never an agent-callable tool."""
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def terms(text):
    return set(re.findall(r"[^\W_]{3,}", text.lower())) - {
        "the", "and", "for", "that", "what", "was", "with", "this", "you", "about"}


class Memory:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}');
                CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id, id);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self):
        cid, timestamp = str(uuid4()), now()
        with self.connect() as db:
            db.execute("INSERT INTO conversations VALUES (?, ?, ?, ?)",
                       (cid, "New conversation", timestamp, timestamp))
        return self.get(cid)

    def get(self, cid):
        with self.connect() as db:
            row = db.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
        return dict(row) if row else None

    def conversations(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT 100")]

    def delete(self, cid):
        with self.connect() as db:
            return db.execute("DELETE FROM conversations WHERE id=?", (cid,)).rowcount > 0

    @staticmethod
    def unpack(row):
        item = dict(row)
        item["metadata"] = json.loads(item["metadata"])
        return item

    def messages(self, cid, limit=200):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
                              (cid, limit)).fetchall()
        return [self.unpack(r) for r in reversed(rows)]

    def append(self, cid, role, content, metadata=None):
        timestamp = now()
        with self.connect() as db:
            cur = db.execute("INSERT INTO messages(conversation_id,role,content,created_at,metadata) "
                             "VALUES(?,?,?,?,?)", (cid, role, content, timestamp, json.dumps(metadata or {})))
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (timestamp, cid))
            if role == "user":
                db.execute("UPDATE conversations SET title=? WHERE id=? AND title='New conversation'",
                           (content[:60], cid))
            row = db.execute("SELECT * FROM messages WHERE id=?", (cur.lastrowid,)).fetchone()
        return self.unpack(row)

    def retrieve(self, cid, query):
        # Bounded scan avoids embeddings, external retrieval and extra model calls.
        rows = self.messages(cid, 500)
        recent = rows[-6:]
        tokens = terms(query)
        older = rows[:-6]
        ranked = sorted(older, key=lambda m: (len(tokens & terms(m["content"])), m["id"]), reverse=True)
        relevant = [r for r in ranked if tokens & terms(r["content"])][:4]
        return sorted(relevant + recent, key=lambda m: m["id"])
