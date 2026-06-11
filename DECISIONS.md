# Decision log

Every significant choice, with the tradeoff reasoning at the time it was made.
Newest entries at the bottom.

## LLM provider: OpenAI

Provider choice is deliberately low-stakes for this task: the deep dive is
latency instrumentation, not model quality, and the orchestration layer is
~100 lines of swappable code behind one seam (`llm.py`). For a decision that
cheap to reverse, the right move is the fastest path to a deployed skeleton —
I already have an OpenAI account with credits, so that's what Sarjy uses. If
Phase 2 measurements point at the model, swapping providers is an hour's
work, and `SARJY_MODEL` already covers A/B tests within OpenAI for free.

## Model: gpt-4.1-mini (configurable via `SARJY_MODEL`)

Chosen for fast time-to-first-token (no reasoning phase), low cost, and
reliable tool calling. For a voice assistant, TTFT dominates perceived
latency, so a reasoning model would be the wrong tradeoff — it sits silent
while "thinking", which is exactly what kills the feeling of liveness. The
env var makes Phase 2 model A/B comparisons free.

## External API: Open-Meteo (weather)

Weather is the canonical hands-free voice query — "do I need a jacket?" is
something people genuinely ask out loud. Open-Meteo requires no API key, so
any evaluator can hit the deployed demo without setup and there are no keys
to leak or rate limits to babysit during review. Two endpoints (geocoding +
forecast) also force a real tool-use round-trip, not a toy.

## Memory: explicit `remember_fact` tool + SQLite, no embeddings

The requirement is "what's my favorite color?" across sessions — that's a
key-value problem, not a retrieval problem. An explicit tool the LLM calls
makes memory writes observable (they show up in the transcript and debug
panel), and injecting all stored facts into the system prompt is fine at
this scale. A vector DB here would be résumé-driven engineering.

## Transport: SSE over WebSocket (Phase 1)

The data flow is strictly request → streamed response; there's no
server-initiated traffic. SSE works over plain HTTP, survives proxies, and
needs zero extra dependencies. WebSocket becomes worth it only if Phase 2
moves to bidirectional streaming audio — noted in IDEAS.md.

## Session history in RAM, facts in SQLite

Within a session, Sarjy keeps the last ~20 messages per user in an in-process
dict so multi-turn conversation works ("what about tomorrow?"). It is
deliberately not persisted: cross-session continuity is what the facts table
is for, and persisting transcripts adds privacy surface without serving the
minimum bar. A server restart costs only in-flight conversational context.

## Tooling: uv + pyproject.toml, pytest for tests

uv gives a lockfile (reproducible installs for anyone cloning the repo) and
one-command setup (`uv sync`); pyproject.toml is where Python packaging has
settled, so there's no requirements.txt to drift out of date. pytest stays a
dev-only dependency group — plain asserts keep the 2–3 memory-layer tests
readable, and it never ships in the runtime image.

## Clock discipline in the latency waterfall

Client and server timestamps come from different clocks, so no duration is
ever computed by subtracting across them. Client rows use client stamps,
server rows use server stamps, and the headline time-to-first-audio is pure
client-side (`t_first_audio − t_speech_end`), making it immune to skew. The
server's LLM/tool breakdown is displayed as an annotated sub-detail of the
client's "send → first byte" row, not stitched into one timeline.
