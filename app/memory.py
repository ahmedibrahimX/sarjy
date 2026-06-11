import sqlite3


def save_fact(conn: sqlite3.Connection, user_id: str, fact: str) -> bool:
    """Persist a fact for a user. Returns False for blanks and exact duplicates."""
    fact = fact.strip()
    if not fact:
        return False
    dup = conn.execute(
        "SELECT 1 FROM facts WHERE user_id = ? AND fact = ?", (user_id, fact)
    ).fetchone()
    if dup:
        return False
    conn.execute("INSERT INTO facts (user_id, fact) VALUES (?, ?)", (user_id, fact))
    conn.commit()
    return True


def get_facts(conn: sqlite3.Connection, user_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT fact FROM facts WHERE user_id = ? ORDER BY id", (user_id,)
    ).fetchall()
    return [row["fact"] for row in rows]


def list_facts(conn: sqlite3.Connection, user_id: str) -> list[dict]:
    """Facts with ids and timestamps, newest first — feeds the memories sidebar."""
    rows = conn.execute(
        "SELECT id, fact, created_at FROM facts WHERE user_id = ? ORDER BY id DESC",
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def delete_fact(conn: sqlite3.Connection, user_id: str, fact_id: int) -> bool:
    """Delete one fact, scoped to the owning user. Returns False if not found."""
    cur = conn.execute(
        "DELETE FROM facts WHERE user_id = ? AND id = ?", (user_id, fact_id)
    )
    conn.commit()
    return cur.rowcount > 0
