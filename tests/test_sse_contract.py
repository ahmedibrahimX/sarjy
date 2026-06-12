"""Contract tests for the SSE event protocol emitted by llm.run_turn.

The event stream (delta / tool_ack / tool / done) now has three consumers —
the browser client, the bench harness, and the dashboard's stored turns —
so its sequence and shapes are pinned here against a stubbed provider.
"""

import asyncio
from collections import deque
from types import SimpleNamespace

import pytest

from app import db, llm


def chunk(content=None, tool_calls=None, finish=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish)])


def tool_call_delta(index=0, call_id=None, name=None, arguments=None):
    return SimpleNamespace(
        index=index,
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def stub_provider(monkeypatch, rounds):
    state = {"round": 0}

    async def fake_stream(oai, *, model, messages, tools):
        data = rounds[state["round"]]
        state["round"] += 1
        for c in data:
            yield c

    monkeypatch.setattr(llm.provider, "stream_chat", fake_stream)


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    yield c
    c.close()


def run(conn, message="hello"):
    async def collect():
        events = []
        turn = llm.run_turn(
            oai=None,
            http=None,
            conn=conn,
            model="stub-model",
            user_id="contract-test",
            history=deque(),
            message=message,
            timings={"t_request_received": 0},
        )
        async for event in turn:
            events.append(event)
        return events

    return asyncio.run(collect())


def test_plain_turn_emits_deltas_then_done(monkeypatch, conn):
    stub_provider(
        monkeypatch,
        [[chunk(content="Hi"), chunk(content=" there."), chunk(finish="stop")]],
    )
    events = run(conn)
    assert [e["type"] for e in events] == ["delta", "delta", "done"]
    assert events[0]["text"] == "Hi"
    done = events[-1]
    assert done["reply"] == "Hi there."
    assert done["server"]["t_llm_first_token"] is not None
    assert done["server"]["tools"] == []


def test_tool_turn_with_ack_event_sequence(monkeypatch, conn):
    monkeypatch.setenv("OPT_TOOL_ACK", "true")

    async def fake_weather(http, city, conn=None):
        return {"city": city, "temperature_c": 20}

    monkeypatch.setattr(llm.tools, "get_weather", fake_weather)
    stub_provider(
        monkeypatch,
        [
            [
                chunk(tool_calls=[tool_call_delta(0, "call_1", "get_weather", '{"city"')]),
                chunk(tool_calls=[tool_call_delta(0, None, None, ': "Cairo"}')]),
                chunk(finish="tool_calls"),
            ],
            [chunk(content="It is "), chunk(content="sunny."), chunk(finish="stop")],
        ],
    )
    events = run(conn, "weather in Cairo?")
    assert [e["type"] for e in events] == [
        "tool_ack",
        "tool",
        "tool",
        "delta",
        "delta",
        "done",
    ]
    assert events[0]["text"] == "Checking the weather in Cairo."
    assert events[1] == {"type": "tool", "name": "get_weather", "status": "start"}
    assert events[2]["status"] == "end"
    assert events[2]["duration_ms"] >= 0
    done = events[-1]
    assert done["reply"] == "It is sunny."
    assert [t["name"] for t in done["server"]["tools"]] == ["get_weather"]


def test_tool_turn_without_ack_flag(monkeypatch, conn):
    monkeypatch.delenv("OPT_TOOL_ACK", raising=False)

    async def fake_weather(http, city, conn=None):
        return {"city": city}

    monkeypatch.setattr(llm.tools, "get_weather", fake_weather)
    stub_provider(
        monkeypatch,
        [
            [
                chunk(tool_calls=[tool_call_delta(0, "call_1", "get_weather", '{"city": "Cairo"}')]),
                chunk(finish="tool_calls"),
            ],
            [chunk(content="Sunny."), chunk(finish="stop")],
        ],
    )
    events = run(conn, "weather?")
    assert [e["type"] for e in events] == ["tool", "tool", "delta", "done"]
