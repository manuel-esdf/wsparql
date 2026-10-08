"""Tag cache: Ollaya tag probabilities per question, in SQLite (stdlib). Created on first use.

Filled by `make tags-cache` (one run_id per invocation), read by `make candidates`.
"""
import json
import sqlite3
from datetime import datetime

from wsparql import ollaya

SCHEMA = """CREATE TABLE IF NOT EXISTS tag_cache (
    profile  TEXT NOT NULL,
    q_id     INTEGER NOT NULL,
    question TEXT NOT NULL,
    tags     TEXT NOT NULL,
    model    TEXT NOT NULL,
    version  TEXT NOT NULL,
    date     TEXT NOT NULL,
    run_id   INTEGER NOT NULL)"""  # tags = JSON {tag: probability}; run_id = 1, 2, ... per `make tags-cache`


class TagCache:
    def __init__(self, path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.execute(SCHEMA)

    def next_run_id(self):
        """run_id for a new fill: 1 on an empty table, then max + 1."""
        return self.conn.execute("SELECT COALESCE(MAX(run_id), 0) + 1 FROM tag_cache").fetchone()[0]

    def put(self, profile, q_id, question, probs, model, version, date, run_id):
        with self.conn:
            self.conn.execute(
                "INSERT INTO tag_cache (profile, q_id, question, tags, model, version, date, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (profile, q_id, question, json.dumps(probs), model, version, date, run_id))

    def get(self, profile, question, model, version):
        """(probs, run_id) from the last run for this exact question, or None. Model/version are part of the key: a
        VERSION bump or model switch is a miss, never a stale hit."""
        row = self.conn.execute(
            "SELECT tags, run_id FROM tag_cache WHERE profile = ? AND question = ? AND model = ? AND version = ? "
            "ORDER BY run_id DESC, rowid DESC LIMIT 1", (profile, question, model, version)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def count(self):
        return self.conn.execute("SELECT COUNT(*) FROM tag_cache").fetchone()[0]


def fill(profile, cache, model, log=print):
    """Detect tags for every tests/test-questions.yaml question and cache them; one row per question. Returns the run_id."""
    run_id = cache.next_run_id()  # same value on every row of this fill
    date = datetime.now().isoformat(timespec="seconds")
    n = len(profile.test_questions)
    for q_id, question in ((q["q_id"], q["question"]) for q in profile.test_questions):
        probs = ollaya.detect_tags(question, profile.tags)
        cache.put(profile.name, q_id, question, probs, model, profile.version, date, run_id)
        top = "  ".join(f"{p:.2f} {t}" for t, p in list(probs.items())[:3])
        log(f"[{q_id:>2}/{n}] {top} | {question}")
    return run_id
