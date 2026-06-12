import json
import sqlite3
import time
from collections import deque
from collections.abc import AsyncIterator

import httpx
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from . import config, memory, provider, tools


def now_ms() -> float:
    return round(time.time() * 1000, 1)


SYSTEM_PROMPT = """You are Sarjy, a friendly voice assistant. Your replies are spoken aloud by a TTS engine, so:
- Keep answers to one to three short sentences, conversational and warm.
- Never use markdown, lists, emoji, or anything that sounds wrong read aloud.
- Round numbers naturally: say "about 24 degrees", not "23.7 degrees Celsius".
When the user shares a lasting personal fact (name, preferences, where they live), call remember_fact with a short third-person statement like "Favorite color is blue". Use get_weather when asked about weather or what to wear outside. Only state personal facts about the user that appear in your memory list or the current conversation — if you don't know something, like their name, say so plainly instead of guessing. If a tool returns an error, say so honestly — never invent data."""


def build_system_prompt(facts: list[str]) -> str:
    if not facts:
        return SYSTEM_PROMPT
    lines = "\n".join(f"- {fact}" for fact in facts)
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Things you remember about this user from earlier sessions:\n{lines}"
    )


async def run_turn(  # noqa: C901, PLR0913 — deliberately one linear orchestration function
    *,
    oai: AsyncOpenAI,
    http: httpx.AsyncClient,
    conn: sqlite3.Connection,
    model: str,
    user_id: str,
    history: deque[ChatCompletionMessageParam],
    message: str,
    timings: dict,
) -> AsyncIterator[dict]:
    """
    One voice turn: stream deltas, run tool calls, record server timings.

    Yields SSE event dicts (delta / tool / done). Appends the exchange to
    `history` (the caller's per-session deque) once the turn completes, so a
    failed turn never poisons the session transcript.
    """
    facts = memory.get_facts(conn, user_id)
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": build_system_prompt(facts)},
        *history,
        {"role": "user", "content": message},
    ]
    tool_events: list[dict] = []
    reply_parts: list[str] = []

    while True:
        stream = provider.stream_chat(
            oai, model=model, messages=messages, tools=tools.TOOL_SCHEMAS
        )
        calls: dict[int, dict] = {}
        text_parts: list[str] = []
        finish = None
        async for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            # First token = first content or tool-call delta, not the
            # role-only preamble chunk; only the first round counts.
            if (delta.content or delta.tool_calls) and "t_llm_first_token" not in timings:
                timings["t_llm_first_token"] = now_ms()
            if delta.content:
                text_parts.append(delta.content)
                reply_parts.append(delta.content)
                yield {"type": "delta", "text": delta.content}
            for tc in delta.tool_calls or []:
                slot = calls.setdefault(
                    tc.index,
                    {"id": None, "name": "", "arguments": ""},
                )
                if tc.id:
                    slot["id"] = tc.id
                if tc.function and tc.function.name:
                    slot["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    slot["arguments"] += tc.function.arguments
            if choice.finish_reason:
                finish = choice.finish_reason

        if finish != "tool_calls":
            break

        ordered = [calls[i] for i in sorted(calls)]
        messages.append(
            {
                "role": "assistant",
                "content": "".join(text_parts) or None,
                "tool_calls": [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": call["arguments"],
                        },
                    }
                    for call in ordered
                ],
            },
        )
        # Spoken acknowledgment so the tool round-trip runs under audio.
        # Templated, no extra LLM call; only worth it for slow tools —
        # remember_fact finishes in ~15 ms, an ack would outlast it.
        if config.flags()["OPT_TOOL_ACK"]:
            ack = _tool_ack_text(ordered[0])
            if ack:
                yield {"type": "tool_ack", "text": ack}

        for call in ordered:
            yield {"type": "tool", "name": call["name"], "status": "start"}
            t_start = now_ms()
            result = await _execute_tool(call, http=http, conn=conn, user_id=user_id)
            t_end = now_ms()
            tool_events.append(
                {
                    "name": call["name"],
                    "t_tool_start": t_start,
                    "t_tool_end": t_end,
                    "duration_ms": round(t_end - t_start, 1),
                },
            )
            yield {
                "type": "tool",
                "name": call["name"],
                "status": "end",
                "duration_ms": round(t_end - t_start, 1),
            }
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result),
                },
            )

    reply = "".join(reply_parts)
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": reply})
    timings["t_response_complete"] = now_ms()
    timings["tools"] = tool_events
    yield {"type": "done", "reply": reply, "server": timings}


def _tool_ack_text(call: dict) -> str | None:
    if call["name"] != "get_weather":
        return None
    try:
        city = json.loads(call["arguments"] or "{}").get("city", "")
    except json.JSONDecodeError:
        city = ""
    return f"Checking the weather in {city}." if city else "Checking the weather."


async def _execute_tool(
    call: dict,
    *,
    http: httpx.AsyncClient,
    conn: sqlite3.Connection,
    user_id: str,
) -> dict:
    try:
        args = json.loads(call["arguments"] or "{}")
    except json.JSONDecodeError:
        return {"error": "malformed tool arguments"}
    try:
        if call["name"] == "get_weather":
            return await tools.get_weather(http, args.get("city", ""), conn=conn)
        if call["name"] == "remember_fact":
            saved = memory.save_fact(conn, user_id, args.get("fact", ""))
            return {"saved": saved}
        return {"error": f"unknown tool: {call['name']}"}
    except Exception as exc:  # noqa: BLE001 — a tool failure must not kill the stream
        return {"error": str(exc)}
