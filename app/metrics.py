import json
import sqlite3


def save_turn(
    conn: sqlite3.Connection,
    user_id: str,
    turn: dict,
    config_snapshot: dict | None = None,
) -> None:
    conn.execute(
        "INSERT INTO metrics (user_id, turn_json, config_snapshot) VALUES (?, ?, ?)",
        (user_id, json.dumps(turn), json.dumps(config_snapshot or {})),
    )
    conn.commit()
