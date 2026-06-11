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
