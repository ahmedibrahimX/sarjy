import json
import sqlite3


def recent_turns(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Turns for the public dashboard: timings, labels, config — no user ids."""
    rows = conn.execute(
        "SELECT id, turn_json, config_snapshot, created_at "
        "FROM metrics ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "turn": json.loads(row["turn_json"]),
            "config": json.loads(row["config_snapshot"] or "{}"),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def list_bench_runs(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, name, created_at FROM bench_run ORDER BY id DESC",
    ).fetchall()
    return [dict(row) for row in rows]


def get_bench_run(conn: sqlite3.Connection, run_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, name, config_snapshot, results_json, created_at "
        "FROM bench_run WHERE id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "config_snapshot": json.loads(row["config_snapshot"]),
        "results": json.loads(row["results_json"]),
    }


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
