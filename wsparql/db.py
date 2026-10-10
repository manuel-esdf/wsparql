"""profile/profile.db (SQLite, stdlib, git-ignored, shared by all profiles). Created on first use.

ontology_tags: the tag dictionary derived from the ontology by `make ontology-tags-gen`, plus the eight fixed intents from tags.py
             (source = intent): deterministic, so no run_id, the rows of the profile/version are replaced on each run;
             read by every command.
cq_tag_assessment:  Ollaya tag probabilities per catalog query competency question (column `description`), filled by `make cq-tag-assessment` (one run_id per invocation);
             a query's tags = those >= pipeline.TAG_THRESHOLD in the latest run (replaces hand-written catalog tags).
question_tag_assessment:   Ollaya tag probabilities per question, filled by `make question-tag-assessment` (one run_id per invocation),
             read by `make query-ranking` / `query-selection` / `answer` / `demo` (latest run) and `make eval` (one fixed run).
question_eval: one row per (profile, q_id, run_id), replaced by each `make eval`; run_id = the question_tag_assessment run the tags came from.
"""
import json
import sqlite3
from datetime import datetime

from wsparql import ollaya

SCHEMA = """
CREATE TABLE IF NOT EXISTS ontology_tags (
    profile     TEXT NOT NULL,
    tag         TEXT NOT NULL,
    description TEXT NOT NULL,
    source      TEXT NOT NULL,
    version     TEXT NOT NULL,
    date        TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cq_tag_assessment (
    profile     TEXT NOT NULL,
    q_id        INTEGER NOT NULL,
    q_label     TEXT NOT NULL,
    description TEXT NOT NULL,  -- the catalog competency question at that run
    tags        TEXT NOT NULL,
    model       TEXT NOT NULL,
    version     TEXT NOT NULL,
    date        TEXT NOT NULL,
    run_id      INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS question_tag_assessment (
    profile  TEXT NOT NULL,
    q_id     INTEGER NOT NULL,
    question TEXT NOT NULL,
    tags     TEXT NOT NULL,
    model    TEXT NOT NULL,
    version  TEXT NOT NULL,
    date     TEXT NOT NULL,
    run_id   INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS question_eval (
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
CREATE UNIQUE INDEX IF NOT EXISTS eval_key ON question_eval (profile, q_id, run_id);
"""
# ontology_tags: description = the noul instruction sent to Ollaya; source = "class ex:C06" / "individual ex:I02" / "property ex:P13" / "intent" (opaque IRIs, the tag name is the label)
# cq_tag_assessment:  q_id = 1-based catalog position, q_label = catalog id (q01-total-expenses-by-project), tags = JSON {tag: probability}
# question_tag_assessment:   tags = JSON {tag: probability}
# run_id:      one counter over the Ollaya tables (RUN_TABLES): 1, 2, ... per `make cq-tag-assessment` / `question-tag-assessment` invocation
# question_eval: selected = catalog id or "none"; params = JSON of the bound values; missing = "acronym, from" or "";
#              row_count NULL when no query ran; date = the `make eval` that wrote the row (one value per eval)

RUN_TABLES = ["cq_tag_assessment", "question_tag_assessment"]
EVAL_COLS = "profile, q_id, question, expected, selected, confidence, params, missing, row_count, ok, model, version, run_id, date"


class ProfileDb:
    def __init__(self, path):
        self.path = path
        self.conn = sqlite3.connect(path)
        # ponytail: one-off renames for dbs created before 2026-10-10 (tables `tags`, `query_tags`, `tag_cache`, `eval_result`); delete after the next make clean
        names = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for old, new in {"tags": "ontology_tags", "query_tags": "cq_tag_assessment", "tag_cache": "question_tag_assessment", "eval_result": "question_eval"}.items():
            if old in names and new not in names:
                self.conn.execute(f"ALTER TABLE {old} RENAME TO {new}")
        self.conn.executescript(SCHEMA)

    def next_run_id(self):
        """run_id for a new run: 1 on an empty db, then max over RUN_TABLES + 1."""
        union = " UNION ALL ".join(f"SELECT run_id FROM {t}" for t in RUN_TABLES)
        return self.conn.execute(f"SELECT COALESCE(MAX(run_id), 0) + 1 FROM ({union})").fetchone()[0]

    # ontology_tags
    def put_ontology_tags(self, profile, version, date, rows):
        """Store one `make ontology-tags-gen`: rows = [(tag, description, source)] replace the profile/version rows; one transaction."""
        with self.conn:
            self.conn.execute("DELETE FROM ontology_tags WHERE profile = ? AND version = ?", (profile, version))
            self.conn.executemany("INSERT INTO ontology_tags (profile, tag, description, source, version, date) VALUES (?, ?, ?, ?, ?, ?)",
                                  [(profile, t, d, s, version, date) for t, d, s in rows])

    def ontology_tags(self, profile, version):
        """{tag: description} for this profile/version, or None before `make ontology-tags-gen`."""
        rows = self.conn.execute("SELECT tag, description FROM ontology_tags WHERE profile = ? AND version = ? ORDER BY rowid", (profile, version))
        return dict(rows) or None

    # cq_tag_assessment
    def put_cq_tag_assessment(self, profile, model, version, date, run_id, rows):
        """Store one `make cq-tag-assessment`: rows = [(q_id, q_label, description, probs)]; one transaction."""
        with self.conn:
            self.conn.executemany(
                "INSERT INTO cq_tag_assessment (profile, q_id, q_label, description, tags, model, version, date, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(profile, i, label, desc, json.dumps(probs), model, version, date, run_id) for i, label, desc, probs in rows])

    def cq_tag_assessment(self, profile, model, version):
        """({q_label: {tag: probability}} of the latest cq-tag-assessment run for this profile/model/version, run_id), or None."""
        run_id = self.conn.execute("SELECT MAX(run_id) FROM cq_tag_assessment WHERE profile = ? AND model = ? AND version = ?",
                                   (profile, model, version)).fetchone()[0]
        if not run_id:
            return None
        rows = self.conn.execute("SELECT q_label, tags FROM cq_tag_assessment WHERE profile = ? AND model = ? AND version = ? AND run_id = ? ORDER BY q_id",
                                 (profile, model, version, run_id))
        return {label: json.loads(t) for label, t in rows}, run_id

    # question_tag_assessment
    def last_run_id(self, profile, model, version):
        """Latest run_id holding tags for this profile/model/version, or None."""
        return self.conn.execute("SELECT MAX(run_id) FROM question_tag_assessment WHERE profile = ? AND model = ? AND version = ?",
                                 (profile, model, version)).fetchone()[0]

    def put(self, profile, q_id, question, probs, model, version, date, run_id):
        with self.conn:
            self.conn.execute(
                "INSERT INTO question_tag_assessment (profile, q_id, question, tags, model, version, date, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (profile, q_id, question, json.dumps(probs), model, version, date, run_id))

    def get(self, profile, question, model, version, run_id=None):
        """(probs, run_id) for this exact question from the given run_id, or from the last run when run_id is None; None on a
        miss. Model/version are part of the key: a VERSION bump or model switch is a miss, never a stale hit."""
        row = self.conn.execute(
            "SELECT tags, run_id FROM question_tag_assessment WHERE profile = ? AND question = ? AND model = ? AND version = ? "
            "AND (? IS NULL OR run_id = ?) ORDER BY run_id DESC, rowid DESC LIMIT 1",
            (profile, question, model, version, run_id, run_id)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def count(self):
        return self.conn.execute("SELECT COUNT(*) FROM question_tag_assessment").fetchone()[0]

    # question_eval
    def put_evals(self, rows):
        """Store one eval: rows in EVAL_COLS order, replacing the row of the same (profile, q_id, run_id);
        one transaction (an interrupted eval stores nothing)."""
        with self.conn:
            self.conn.executemany(f"INSERT OR REPLACE INTO question_eval ({EVAL_COLS}) VALUES ({', '.join('?' * 14)})", rows)

    def prev_eval(self, profile, model, version, run_id):
        """Last stored eval for this profile/model/version/run_id: (date, {q_id: (selected, confidence, row_count, ok)}),
        or None. confidence rounded to 2 decimals (what `make eval` prints)."""
        key = (profile, model, version, run_id)
        date = self.conn.execute("SELECT MAX(date) FROM question_eval WHERE profile = ? AND model = ? AND version = ? AND run_id = ?",
                                 key).fetchone()[0]
        if not date:
            return None
        rows = self.conn.execute("SELECT q_id, selected, ROUND(confidence, 2), row_count, ok FROM question_eval "
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
