import json
import sqlite3
from pathlib import Path
from .common import REASONS, now


class Store:
    def __init__(self, path):
        self.path = Path(path)

    def initialize(self):
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS executions (
                id TEXT PRIMARY KEY, source TEXT NOT NULL, started_at TEXT NOT NULL,
                finished_at TEXT, result TEXT NOT NULL, reason_code TEXT NOT NULL,
                quota TEXT)""")

    def start(self, ident, source):
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("INSERT INTO executions VALUES (?, ?, ?, NULL, 'running', 'running', NULL)",
                       (ident, source, now()))

    def finish(self, ident, result, reason_code, quota=None):
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("UPDATE executions SET finished_at=?, result=?, reason_code=?, quota=? WHERE id=?",
                       (now(), result, reason_code, json.dumps(quota) if quota else None, ident))
            db.execute("""DELETE FROM executions WHERE result != 'running' AND id NOT IN
                (SELECT id FROM executions ORDER BY started_at DESC LIMIT 500)""")

    def recover_interrupted(self):
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("""UPDATE executions SET result='failed', reason_code='interrupted'
                WHERE result='running'""")

    def logs(self, limit=50):
        if not self.path.is_file():
            return []
        # The privileged helper opens the runner-owned database read-only.
        with sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM executions ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        records = []
        for row in rows:
            item = dict(row)
            if item["reason_code"] not in REASONS or item["source"] not in ("automatic", "manual"):
                continue
            item["reason"] = REASONS[item["reason_code"]]
            item["quota"] = json.loads(item["quota"]) if item["quota"] else None
            records.append(item)
        return records

    def get(self, ident):
        return next((x for x in self.logs(500) if x["id"] == ident), None)
