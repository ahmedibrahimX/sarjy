import json
import sqlite3


def save_turn(conn: sqlite3.Connection, user_id: str, turn: dict) -> None:
    conn.execute(
        "INSERT INTO metrics (user_id, turn_json) VALUES (?, ?)",
        (user_id, json.dumps(turn)),
    )
    conn.commit()
