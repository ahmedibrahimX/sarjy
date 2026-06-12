import json
import sqlite3

from app import db


def test_migration_adds_and_backfills_config_snapshot(tmp_path):
    path = str(tmp_path / "legacy.db")
    legacy = sqlite3.connect(path)
    legacy.execute(
        "CREATE TABLE metrics ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, "
        "turn_json TEXT NOT NULL, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    legacy.execute("INSERT INTO metrics (user_id, turn_json) VALUES ('u1', '{}')")
    legacy.commit()
    legacy.close()

    conn = db.connect(path)
    snap = json.loads(
        conn.execute("SELECT config_snapshot FROM metrics").fetchone()["config_snapshot"]
    )
    conn.close()
    assert snap["OPT_SENTENCE_PIPELINING"] is False
    assert snap["model"] == "gpt-4.1-mini"
    assert snap["endpoint_threshold_ms"] is None
