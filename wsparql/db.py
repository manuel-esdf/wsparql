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
    min_confidence REAL NOT NULL DEFAULT 0.4,
    parameter_min_confidence REAL NOT NULL DEFAULT 0.4,
    PRIMARY KEY (profile, q_id, run_id));
"""


class ProfileDb:
    def __init__(self, path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        if "min_confidence" not in {r[1] for r in self.conn.execute("PRAGMA table_info(direct_eval)")}:
            self.conn.execute("ALTER TABLE direct_eval ADD COLUMN min_confidence REAL NOT NULL DEFAULT 0.4")
            self.conn.commit()

        if "parameter_min_confidence" not in {r[1] for r in self.conn.execute("PRAGMA table_info(direct_eval)")}:
            self.conn.execute("ALTER TABLE direct_eval ADD COLUMN parameter_min_confidence REAL NOT NULL DEFAULT 0.4")
            self.conn.execute("UPDATE direct_eval SET parameter_min_confidence = min_confidence")
            self.conn.commit()

    def next_run_id(self):
        return self.conn.execute("SELECT COALESCE(MAX(run_id), 0) + 1 FROM direct_eval").fetchone()[0]

    def put_evals(self, rows, min_confidence=0.4, parameter_min_confidence=None):
        """Store a completed evaluation atomically; interrupted evaluations store nothing."""
        parameter_min_confidence = min_confidence if parameter_min_confidence is None else parameter_min_confidence
        with self.conn:
            self.conn.executemany(f"INSERT INTO direct_eval ({EVAL_COLS}, min_confidence, parameter_min_confidence) VALUES ({', '.join('?' * 16)})",
                                  [(*row, min_confidence, parameter_min_confidence) for row in rows])

    def prev_eval(self, profile, model, version, min_confidence=0.4, parameter_min_confidence=None):
        """Latest evaluation date and {question id: (selected, confidence, row_count, ok)}."""
        parameter_min_confidence = min_confidence if parameter_min_confidence is None else parameter_min_confidence
        key = (profile, model, version, min_confidence, parameter_min_confidence)
        run_id = self.conn.execute(
            "SELECT MAX(run_id) FROM direct_eval WHERE profile=? AND model=? AND version=? AND min_confidence=? AND parameter_min_confidence=?", key,
        ).fetchone()[0]
        if run_id is None:
            return None
        rows = self.conn.execute(
            "SELECT q_id, selected, ROUND(confidence, 2), row_count, ok, date FROM direct_eval "
            "WHERE profile=? AND model=? AND version=? AND min_confidence=? AND parameter_min_confidence=? AND run_id=?", (*key, run_id),
        ).fetchall()
        return rows[0][5], {r[0]: tuple(r[1:5]) for r in rows}
