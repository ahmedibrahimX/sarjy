import json
import sqlite3


def clear_turns(conn: sqlite3.Connection) -> int:
    """Delete all turn metrics (facts and bench runs untouched)."""
    cur = conn.execute("DELETE FROM metrics")
    conn.commit()
    return cur.rowcount


def save_bench_run(
    conn: sqlite3.Connection,
    name: str,
    config_snapshot: dict,
    results: dict,
) -> int:
    cur = conn.execute(
        "INSERT INTO bench_run (name, config_snapshot, results_json) VALUES (?, ?, ?)",
        (name, json.dumps(config_snapshot), json.dumps(results)),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


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
