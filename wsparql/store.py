"""SQLite persistence for evaluation runs (stdlib sqlite3). Created on first use."""
import json
import sqlite3

SCHEMA = """CREATE TABLE IF NOT EXISTS tag_results (
    q_id     INTEGER NOT NULL,
    question TEXT NOT NULL,
    tags     TEXT NOT NULL,
    model    TEXT NOT NULL,
    version  TEXT NOT NULL,
    date     TEXT NOT NULL,
    tags_test INTEGER NOT NULL)"""  # tags = JSON {tag: probability}; tags_test = run number, 1, 2, ...


class Store:
    def __init__(self, path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.execute(SCHEMA)

    def next_tags_test(self):
        """Run number for a new tags-test: 1 on an empty table, then max + 1."""
        return self.conn.execute("SELECT COALESCE(MAX(tags_test), 0) + 1 FROM tag_results").fetchone()[0]

    def save_tags(self, q_id, question, probs, model, version, date, tags_test):
        with self.conn:
            self.conn.execute(
                "INSERT INTO tag_results (q_id, question, tags, model, version, date, tags_test) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (q_id, question, json.dumps(probs), model, version, date, tags_test))

    def count(self):
        return self.conn.execute("SELECT COUNT(*) FROM tag_results").fetchone()[0]
