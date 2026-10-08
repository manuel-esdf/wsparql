"""SQLite persistence for evaluation runs (stdlib sqlite3). Created on first use."""
import json
import sqlite3

SCHEMA = """CREATE TABLE IF NOT EXISTS tag_results (
    question TEXT NOT NULL,
    tags     TEXT NOT NULL,
    model    TEXT NOT NULL,
    version  TEXT NOT NULL,
    date     TEXT NOT NULL)"""  # tags = JSON object {tag: probability}


class Store:
    def __init__(self, path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.execute(SCHEMA)

    def save_tags(self, date, version, model, question, probs):
        with self.conn:
            self.conn.execute("INSERT INTO tag_results (question, tags, model, version, date) VALUES (?, ?, ?, ?, ?)",
                              (question, json.dumps(probs), model, version, date))

    def count(self):
        return self.conn.execute("SELECT COUNT(*) FROM tag_results").fetchone()[0]
