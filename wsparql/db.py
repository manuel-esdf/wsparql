"""profile/profile.db (SQLite, stdlib, git-ignored, shared by all profiles). Created on first use.

tag_cache:   Ollaya tag probabilities per question, filled by `make tags-cache` (one run_id per invocation),
             read by `make candidates` / `select` / `ask` / `demo` (latest run) and `make eval` (one fixed run).
eval_result: one row per `make eval` question, with the tag_cache run_id the tags came from.
"""
import json
import sqlite3
from datetime import datetime

from wsparql import ollaya

SCHEMA = """
CREATE TABLE IF NOT EXISTS tag_cache (
    profile  TEXT NOT NULL,
    q_id     INTEGER NOT NULL,
    question TEXT NOT NULL,
    tags     TEXT NOT NULL,
    model    TEXT NOT NULL,
    version  TEXT NOT NULL,
    date     TEXT NOT NULL,
    run_id   INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS eval_result (
    profile    TEXT NOT NULL,
    q_id       INTEGER NOT NULL,
    question   TEXT NOT NULL,
    expected   TEXT NOT NULL,
    selected   TEXT NOT NULL,
    confidence REAL NOT NULL,
    params     TEXT NOT NULL,
    missing    TEXT NOT NULL,
    row_count  INTEGER,
    ok         INTEGER NOT NULL,
    model      TEXT NOT NULL,
    version    TEXT NOT NULL,
    run_id     INTEGER NOT NULL,
    date       TEXT NOT NULL);
"""
# tag_cache:   tags = JSON {tag: probability}; run_id = 1, 2, ... per `make tags-cache`
# eval_result: selected = catalog id or "none"; params = JSON of the bound values; missing = "acronym, from" or "";
#              row_count NULL when no query ran; run_id = the tag_cache run used; date = one value per `make eval`

EVAL_COLS = "profile, q_id, question, expected, selected, confidence, params, missing, row_count, ok, model, version, run_id, date"


class ProfileDb:
    def __init__(self, path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    # tag_cache
    def next_run_id(self):
        """run_id for a new fill: 1 on an empty table, then max + 1."""
        return self.conn.execute("SELECT COALESCE(MAX(run_id), 0) + 1 FROM tag_cache").fetchone()[0]

    def last_run_id(self, profile, model, version):
        """Latest run_id holding tags for this profile/model/version, or None."""
        return self.conn.execute("SELECT MAX(run_id) FROM tag_cache WHERE profile = ? AND model = ? AND version = ?",
                                 (profile, model, version)).fetchone()[0]

    def put(self, profile, q_id, question, probs, model, version, date, run_id):
        with self.conn:
            self.conn.execute(
                "INSERT INTO tag_cache (profile, q_id, question, tags, model, version, date, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (profile, q_id, question, json.dumps(probs), model, version, date, run_id))

    def get(self, profile, question, model, version, run_id=None):
        """(probs, run_id) for this exact question from the given run_id, or from the last run when run_id is None; None on a
        miss. Model/version are part of the key: a VERSION bump or model switch is a miss, never a stale hit."""
        row = self.conn.execute(
            "SELECT tags, run_id FROM tag_cache WHERE profile = ? AND question = ? AND model = ? AND version = ? "
            "AND (? IS NULL OR run_id = ?) ORDER BY run_id DESC, rowid DESC LIMIT 1",
            (profile, question, model, version, run_id, run_id)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def count(self):
        return self.conn.execute("SELECT COUNT(*) FROM tag_cache").fetchone()[0]

    # eval_result
    def put_evals(self, rows):
        """Store one eval: rows in EVAL_COLS order, one transaction (an interrupted eval stores nothing)."""
        with self.conn:
            self.conn.executemany(f"INSERT INTO eval_result ({EVAL_COLS}) VALUES ({', '.join('?' * 14)})", rows)

    def prev_eval(self, profile, model, version, run_id):
        """Most recent stored eval for this profile/model/version/run_id: (date, {q_id: (selected, confidence, row_count, ok)}),
        or None. confidence rounded to 2 decimals (what `make eval` prints)."""
        key = (profile, model, version, run_id)
        date = self.conn.execute("SELECT MAX(date) FROM eval_result WHERE profile = ? AND model = ? AND version = ? AND run_id = ?",
                                 key).fetchone()[0]
        if not date:
            return None
        rows = self.conn.execute("SELECT q_id, selected, ROUND(confidence, 2), row_count, ok FROM eval_result "
                                 "WHERE profile = ? AND model = ? AND version = ? AND run_id = ? AND date = ?", (*key, date))
        return date, {r[0]: tuple(r[1:]) for r in rows}


def fill(profile, db, model, log=print):
    """Detect tags for every tests/test-questions.yaml question and cache them; one row per question. Returns the run_id."""
    run_id = db.next_run_id()  # same value on every row of this fill
    date = datetime.now().isoformat(timespec="seconds")
    n = len(profile.test_questions)
    for q_id, question in ((q["q_id"], q["question"]) for q in profile.test_questions):
        probs = ollaya.detect_tags(question, profile.tags)
        db.put(profile.name, q_id, question, probs, model, profile.version, date, run_id)
        top = "  ".join(f"{p:.2f} {t}" for t, p in list(probs.items())[:3])
        log(f"[{q_id:>2}/{n}] {top} | {question}")
    return run_id
