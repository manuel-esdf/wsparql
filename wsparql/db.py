"""SQLite history for direct query evaluations; legacy benchmark tables are left untouched."""
import sqlite3

EVAL_COLS = "profile, q_id, question, expected, selected, confidence, params, missing, row_count, ok, model, version, run_id, date"
SCHEMA = """
CREATE TABLE IF NOT EXISTS direct_eval (
    profile TEXT NOT NULL,
    q_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    expected TEXT NOT NULL,
    selected TEXT NOT NULL,
    confidence REAL NOT NULL,
    params TEXT NOT NULL,
    missing TEXT NOT NULL,
    row_count INTEGER,
    ok INTEGER NOT NULL,
    model TEXT NOT NULL,
    version TEXT NOT NULL,
    run_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    PRIMARY KEY (profile, q_id, run_id));
"""


class ProfileDb:
    def __init__(self, path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    def next_run_id(self):
        return self.conn.execute("SELECT COALESCE(MAX(run_id), 0) + 1 FROM direct_eval").fetchone()[0]

    def put_evals(self, rows):
        """Store a completed evaluation atomically; interrupted evaluations store nothing."""
        with self.conn:
            self.conn.executemany(f"INSERT INTO direct_eval ({EVAL_COLS}) VALUES ({', '.join('?' * 14)})", rows)

    def prev_eval(self, profile, model, version):
        """Latest evaluation date and {question id: (selected, confidence, row_count, ok)}."""
        key = (profile, model, version)
        run_id = self.conn.execute(
            "SELECT MAX(run_id) FROM direct_eval WHERE profile=? AND model=? AND version=?", key,
        ).fetchone()[0]
        if run_id is None:
            return None
        rows = self.conn.execute(
            "SELECT q_id, selected, ROUND(confidence, 2), row_count, ok, date FROM direct_eval "
            "WHERE profile=? AND model=? AND version=? AND run_id=?", (*key, run_id),
        ).fetchall()
        return rows[0][5], {r[0]: tuple(r[1:5]) for r in rows}
