"""
store.py — SQLite storage for Pocket Agent.
Handles: chat history, memories (long-term facts), reminders, and settings pairing.
A fresh connection is opened per call so it is safe to use from multiple threads.
"""

import os
import sqlite3
import datetime
import threading

APP_DIR = os.path.join(os.path.expanduser("~"), "PocketAgent")
DB_PATH = os.path.join(APP_DIR, "pocket_agent.db")

_lock = threading.Lock()


def now_iso() -> str:
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def _conn():
    os.makedirs(APP_DIR, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _lock, _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                due_at TEXT NOT NULL,
                repeat TEXT DEFAULT 'none',
                done INTEGER DEFAULT 0,
                notified INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )
    try:
        import memory_learn
        memory_learn.init_tables()
    except Exception:
        pass


# ---------------------------------------------------------------- chat

def add_chat(role: str, content: str):
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO chat(role, content, created_at) VALUES(?,?,?)",
            (role, content, now_iso()),
        )


def recent_chat(limit: int = 24):
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT role, content FROM chat ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def clear_chat():
    with _lock, _conn() as c:
        c.execute("DELETE FROM chat")


# ---------------------------------------------------------------- memories

def add_memory(content: str):
    content = content.strip()
    if not content:
        return None
    with _lock, _conn() as c:
        dupe = c.execute(
            "SELECT id FROM memories WHERE lower(content)=lower(?)", (content,)
        ).fetchone()
        if dupe:
            return dupe["id"]
        cur = c.execute(
            "INSERT INTO memories(content, created_at) VALUES(?,?)",
            (content, now_iso()),
        )
        return cur.lastrowid


def list_memories(limit: int = 500):
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM memories ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def search_memories(query: str, limit: int = 20):
    q = f"%{query.strip()}%"
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM memories WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
            (q, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_memory(mem_id: int):
    with _lock, _conn() as c:
        c.execute("DELETE FROM memories WHERE id=?", (mem_id,))


# ---------------------------------------------------------------- reminders

def add_reminder(text: str, due_at: str, repeat: str = "none"):
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO reminders(text, due_at, repeat, done, notified, created_at)"
            " VALUES(?,?,?,0,0,?)",
            (text.strip(), due_at, (repeat or "none").lower(), now_iso()),
        )
        return cur.lastrowid


def list_reminders(include_done: bool = False):
    sql = "SELECT * FROM reminders"
    if not include_done:
        sql += " WHERE done=0"
    sql += " ORDER BY due_at ASC"
    with _lock, _conn() as c:
        rows = c.execute(sql).fetchall()
    return [dict(r) for r in rows]


def due_reminders():
    """Reminders that are due and not yet notified."""
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM reminders WHERE done=0 AND notified=0 AND due_at<=? "
            "ORDER BY due_at ASC",
            (now_iso(),),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_notified(rem_id: int):
    with _lock, _conn() as c:
        c.execute("UPDATE reminders SET notified=1 WHERE id=?", (rem_id,))


def complete_reminder(rem_id: int):
    with _lock, _conn() as c:
        c.execute("UPDATE reminders SET done=1, notified=1 WHERE id=?", (rem_id,))


def find_reminder(text: str):
    like = f"%{text.strip()}%"
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT * FROM reminders WHERE done=0 AND text LIKE ? ORDER BY due_at ASC",
            (like,),
        ).fetchone()
    return dict(row) if row else None


def delete_reminder(rem_id: int):
    with _lock, _conn() as c:
        c.execute("DELETE FROM reminders WHERE id=?", (rem_id,))


def reschedule(rem_id: int, next_due: str):
    """After a repeating reminder fires, move it to its next occurrence."""
    with _lock, _conn() as c:
        c.execute(
            "UPDATE reminders SET due_at=?, notified=0 WHERE id=?", (next_due, rem_id)
        )


def next_occurrence(due_at: str, repeat: str) -> str:
    dt = datetime.datetime.fromisoformat(due_at)
    repeat = (repeat or "none").lower()
    if repeat == "daily":
        dt += datetime.timedelta(days=1)
    elif repeat == "weekly":
        dt += datetime.timedelta(weeks=1)
    elif repeat == "monthly":
        month = dt.month + 1
        year = dt.year + (1 if month > 12 else 0)
        month = 1 if month > 12 else month
        day = min(dt.day, 28)
        dt = dt.replace(year=year, month=month, day=day)
    elif repeat in ("weekdays", "weekday"):
        dt += datetime.timedelta(days=1)
        while dt.weekday() >= 5:
            dt += datetime.timedelta(days=1)
    else:
        return due_at
    return dt.replace(microsecond=0).isoformat()
