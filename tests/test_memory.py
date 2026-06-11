import pytest

from app import db, memory


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    yield c
    c.close()


def test_fact_roundtrip(conn):
    memory.save_fact(conn, "u1", "Favorite color is blue")
    assert memory.get_facts(conn, "u1") == ["Favorite color is blue"]


def test_facts_are_per_user(conn):
    memory.save_fact(conn, "u1", "Favorite color is blue")
    assert memory.get_facts(conn, "u2") == []


def test_duplicate_and_blank_facts_are_ignored(conn):
    assert memory.save_fact(conn, "u1", "Lives in Cairo") is True
    assert memory.save_fact(conn, "u1", "Lives in Cairo") is False
    assert memory.save_fact(conn, "u1", "   ") is False
    assert memory.get_facts(conn, "u1") == ["Lives in Cairo"]
