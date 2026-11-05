"""
memory_learn.py — everything that makes Zinger get sharper the more you use it.

Three things live here:
  * the user profile  (who you are — editable and teachable)
  * skills             (named procedures it learns from doing, and reuses)
  * route learning     (which app you actually want for "browser", "music"…)

Plain SQLite, no magic: you can read every row.
"""

import datetime
import re

import store


def _now():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def init_tables():
    with store._lock, store._conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS profile (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                trigger TEXT,
                steps TEXT NOT NULL,
                uses INTEGER DEFAULT 0,
                last_used TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS routes (
                intent TEXT NOT NULL,
                target TEXT NOT NULL,
                hits INTEGER DEFAULT 1,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (intent, target)
            );
            CREATE TABLE IF NOT EXISTS prefs (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )


# ------------------------------------------------------------------ profile
def set_profile(key: str, value: str):
    key = (key or "").strip().lower().replace(" ", "_")
    if not key:
        return
    with store._lock, store._conn() as c:
        c.execute(
            "INSERT INTO profile(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at",
            (key, (value or "").strip(), _now()),
        )


def get_profile():
    with store._lock, store._conn() as c:
        rows = c.execute("SELECT key, value FROM profile ORDER BY key").fetchall()
    return {r["key"]: r["value"] for r in rows}


def remember(line: str) -> str:
    """Turn a plain sentence into a profile fact. Returns the key used."""
    import re

    t = " ".join((line or "").split()).rstrip(".!")
    if not t:
        return ""
    low = t.lower()
    key = value = ""
    m = re.match(r"^(?:my|our)\s+(.+?)\s+(?:is|are|was)\s+(.+)$", t, re.I)
    if m:
        key, value = m.group(1), m.group(2)
    if not key:
        m = re.match(r"^(?:i\s+am|i'm)\s+(.+)$", t, re.I)
        if m:
            key, value = "name", m.group(1)
    if not key:
        m = re.match(r"^i\s+([a-z' ]+?)\s+(.+)$", t, re.I)
        if m:
            key, value = m.group(1), m.group(2)
    if not key:
        n = len([k for k in get_profile() if k.startswith("note")]) + 1
        key, value = "note%d" % n, t
    set_profile(key, value)
    return key


def delete_profile(key: str):
    with store._lock, store._conn() as c:
        c.execute("DELETE FROM profile WHERE key=?", (key,))


# ------------------------------------------------------------------ skills
def save_skill(name: str, steps, trigger: str = ""):
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not name:
        return None
    steps_text = steps if isinstance(steps, str) else " | ".join(steps)
    with store._lock, store._conn() as c:
        c.execute(
            "INSERT INTO skills(name, trigger, steps, created_at) VALUES(?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET steps=excluded.steps, "
            "trigger=excluded.trigger",
            (name, trigger, steps_text, _now()),
        )
    return name


def list_skills():
    with store._lock, store._conn() as c:
        rows = c.execute(
            "SELECT * FROM skills ORDER BY uses DESC, name ASC").fetchall()
    return [dict(r) for r in rows]


def find_skill(text: str):
    """Best-effort match: token overlap between the request and a skill name."""
    text = (text or "").lower()
    best, best_score = None, 0
    for s in list_skills():
        words = set(re.findall(r"[a-z]{3,}", (s["name"] + " " + (s["trigger"] or "")).lower()))
        if not words:
            continue
        score = sum(1 for w in words if w in text) / len(words)
        if score > best_score:
            best, best_score = s, score
    return best if best_score >= 0.6 else None


def use_skill(name: str):
    with store._lock, store._conn() as c:
        c.execute("UPDATE skills SET uses=uses+1, last_used=? WHERE name=?",
                  (_now(), name))


def delete_skill(name: str):
    with store._lock, store._conn() as c:
        c.execute("DELETE FROM skills WHERE name=?", (name,))


# ------------------------------------------------------------------ routes
def learn_route(intent: str, target: str):
    """Remember which app worked for an intent ('browser' -> 'chrome')."""
    intent = (intent or "").strip().lower()
    target = (target or "").strip()
    if not intent or not target:
        return
    with store._lock, store._conn() as c:
        c.execute(
            "INSERT INTO routes(intent, target, hits, updated_at) VALUES(?,?,1,?) "
            "ON CONFLICT(intent, target) DO UPDATE SET hits=hits+1, "
            "updated_at=excluded.updated_at",
            (intent, target, _now()),
        )


def best_route(intent: str):
    with store._lock, store._conn() as c:
        row = c.execute(
            "SELECT target FROM routes WHERE intent=? ORDER BY hits DESC, updated_at DESC "
            "LIMIT 1", ((intent or "").strip().lower(),)).fetchone()
    return row["target"] if row else None


def all_routes():
    with store._lock, store._conn() as c:
        rows = c.execute("SELECT * FROM routes ORDER BY intent, hits DESC").fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ prefs
def set_pref(key: str, value: str):
    with store._lock, store._conn() as c:
        c.execute(
            "INSERT INTO prefs(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at",
            ((key or "").strip().lower(), value, _now()),
        )


def get_pref(key: str, default=None):
    with store._lock, store._conn() as c:
        row = c.execute("SELECT value FROM prefs WHERE key=?",
                        ((key or "").strip().lower(),)).fetchone()
    return row["value"] if row else default


# ------------------------------------------------------------------ summary
def summary_for_prompt(limit_skills: int = 12):
    """A compact block the model reads each turn — this is the 'getting sharper'."""
    bits = []
    prof = get_profile()
    if prof:
        bits.append("LEARNED CONTEXT - what you know about the user "
                    "(teach yourself more as you go):")
        for k, v in list(prof.items())[:40]:
            bits.append("- %s: %s" % (k.replace("_", " "), v))

    skills = list_skills()[:limit_skills]
    if skills:
        bits.append("\nSKILLS YOU HAVE LEARNED (reuse these instead of re-deriving):")
        for s in skills:
            bits.append("- %s (used %dx): %s" % (s["name"], s["uses"], s["steps"]))

    routes = all_routes()
    if routes:
        seen = {}
        for r in routes:
            seen.setdefault(r["intent"], []).append("%s(%d)" % (r["target"], r["hits"]))
        bits.append("\nAPPS THE USER PREFERS:")
        for intent, targets in seen.items():
            bits.append("- %s: %s" % (intent, ", ".join(targets)))
    return "\n".join(bits)
