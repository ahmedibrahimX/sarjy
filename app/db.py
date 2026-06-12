import json
import os
import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    fact TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_facts_user ON facts(user_id);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    turn_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bench_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    config_snapshot TEXT NOT NULL,
    results_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(path: str | None = None) -> sqlite3.Connection:
    """Open and initialize the single SQLite database."""
    path = path or os.environ.get("SARJY_DB", "sarjy.db")
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive migrations for databases created by earlier versions."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(metrics)")}
    if "config_snapshot" not in cols:
        conn.execute("ALTER TABLE metrics ADD COLUMN config_snapshot TEXT")
    # Backfill pre-Phase-2 rows so baseline data stays comparable.
    conn.execute(
        "UPDATE metrics SET config_snapshot = ? WHERE config_snapshot IS NULL",
        (json.dumps(config.PHASE1_SNAPSHOT),),
    )
    conn.commit()
