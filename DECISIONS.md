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

## Typed-input fallback lives inside the latency console

The Web Speech API only ships in Chromium browsers. A small text input in the
latency console keeps the demo usable for evaluators on Firefox/Safari and
gives a quick way to exercise the pipeline without a mic (it stamps
`t_speech_end = t_transcript_final = now`, so waterfalls stay comparable).
It deliberately lives in the debug console, not the main UI — Sarjy is
voice-first, and the minimum bar is voice.

## Remote DB access: snapshot export, not a database server

JDBC tools need a server process speaking a wire protocol; SQLite is an
embedded library — there is no port to expose, and the bridges that fake one
(postlite, sqld) are experimental or unsupported by standard tools. The
token-gated `GET /admin/db` endpoint returns a consistent snapshot (SQLite
backup API), which DBeaver opens natively as a local file. Managed Postgres
is parked in IDEAS.md for when live inspection becomes a real requirement.
A Railway volume keeps the data across deploys.

## Memories sidebar: make the memory system legible

Cross-session memory is a minimum-bar requirement, but invisible state is
hard to demo and hard to trust. The sidebar shows exactly what Sarjy stored,
refreshes live when remember_fact fires mid-conversation, and lets the user
delete any fact (visibility + control). Prioritized over a Postgres
migration because it's evaluator-visible; internal tooling isn't.

## Push-to-talk: tap = auto-endpoint, hold = manual endpoint

Chrome's recognizer finalizes after a fixed silence window, which cuts off
anyone who pauses to think mid-sentence. Tap keeps the quick flow (auto-send
at the first final result, as before); holding the mic button or the space
bar keeps recognition open through pauses and sends on release, walkie-talkie
style. Recognition runs `continuous = true` in both cases — the only
difference is who decides the turn is over, Chrome's endpointer or the user.

## True speech end via a parallel mic-energy VAD

Chrome's `speechend` fires when the recognizer finalizes, not when the user
stops talking, so the endpointing delay (the silence window before the final
transcript) is invisible to the Web Speech API — the first waterfalls showed
"stt finalize: 0 ms", which was the instrument lying. A ~40-line analyser on
the raw mic stream records the last moment the signal exceeded the noise
floor; that stamp is the basis for perceived time-to-first-audio. Fallback
chain when the second mic capture fails: last interim-transcript update,
then Chrome's stamp — and every metrics row records which basis was used
(`ttfa_basis`), so baselines are never silently mixed. The same VAD is the
natural foundation for barge-in later.

## Conversation history is session-scoped (per page load)

History originally lived in RAM keyed by user id alone, so a page refresh
kept the old transcript: deleting a fact looked broken (the model re-read
the deleted info from the conversation), and "fresh session" demos weren't
actually fresh. The client now sends a session_id generated per page load,
and the server keeps only the latest session's messages per user. Refresh =
clean conversation; the facts table is the only cross-session channel.

## Guardrail: never guess personal facts

Asked "what's my name?" with no name on file (but "Lives in Cairo" in
context), the model confabulated a plausible name — and happened to be
right, which made it look exactly like a memory leak until the database
proved otherwise. One system-prompt line fixes it: only state personal
facts present in memory or the conversation, otherwise say you don't know.
Empty memory must produce "I don't know", not a guess.

## Companion latency dashboard, public, deliberately small

A working analysis tool beats markdown tables: the dashboard reads the
metrics and bench tables we already collect and renders the live turn feed,
bench-run deltas, and sliceable TTFA distributions — every improvement
attributable to a config_snapshot. It is public because the data is timings
and labels only (no transcripts, no user ids displayed) and a shareable
URL demos better than a screenshot; writes (bench storage, metrics purge)
stay behind the admin token. Production would ship these same per-turn
events to a real observability pipeline; for this project's scale, SQLite
plus one polling page is the right size — no websockets, no Grafana, one
CDN chart library. The waterfall renderer is shared with the debug console
(static/waterfall.js): one stage model, two presentations.

## Attack 1: sentence chunking into browser TTS, not a streaming TTS provider

The pipeline's shape was the problem, not the synthesizer: browser TTS
starts in 4-13 ms (measured across all human turns), so an external
streaming-TTS provider would have added network latency to fix the wrong
stage. Sentence chunking keeps the zero-cost synthesizer and deletes the
actual wait (the stream tail after sentence one). The utterance queue is
`speechSynthesis`'s native queue — no scheduler invented. The splitter is
deliberately conservative (whitespace-lookahead punctuation, minimum first
flush) and its known failure mode (mid-sentence abbreviations) is accepted
and documented rather than engineered away for spoken-style replies that
rarely contain them. Forced consequence, kept: barge-in now aborts the
in-flight request, since canceling only audio would leave the open stream
refilling the queue. Measured result and the noise-vs-claim discipline
live in LATENCY.md.

## Attack 2: templated acknowledgments; cache the immutable half only

The acknowledgment exists to start audio at first byte — generating it
with an LLM call would re-add the latency it exists to hide, so it is a
template with the city interpolated from tool arguments we already parsed.
Only slow tools get one (remember_fact finishes faster than the ack would).
Perceived and actual TTFA stay separate metrics: the waterfall keeps
showing the real tool time, and the writeup reports both — an
acknowledgment changes how waiting feels, not how long the data takes.

The cache covers geocoding (city to coordinates — immutable) and
deliberately not the weather itself: a short-TTL forecast cache would have
been an easy extra win and a wrong one, since serving stale weather to
make a latency number look better is the hallucination failure mode with
extra steps. Measured: tool p50 halved; the p95 tail stayed, because it
belongs to the forecast call's connection setup (Attack 4's problem).

## Rigor budget: verification went where the risk was

This project was not built test-first, and that was a decision rather than
an omission. The dominant risks were unmeasured latency claims and
integration breakage on a deployed demo — not logic regressions in a
small single-developer codebase — so verification effort went to
instrumentation, live probing of every deploy (SSE error paths, auth
gates, container smoke tests, migration runs against copies of real
data), and the measurement protocol itself. Unit tests are deliberately
scoped to stable pure logic: the memory layer, the schema migration, the
sentence splitter's case table. The SSE contract tests exist because the
event protocol crossed a threshold — three independent consumers (browser
client, bench harness, dashboard) — where a silent shape change would
break things the type checker cannot see.

## Two instruments: headless bench plus human protocol

The bench harness (app/bench.py) drives the real /chat endpoint with fixed
prompts, N repetitions, and controlled cadence — and is blind to TTFA,
endpointing, and TTS (no microphone, no audio). The human protocol measures
exactly those, but every spoken sample carries mic, room, and phrasing
variance, and costs minutes per condition. They are complements with
disjoint blind spots: server-side attacks (geocode cache, keep-alive,
model A/B) take their primary evidence from the bench; client-side attacks
(pipelining, acknowledgments, endpointing) from human turns, with the bench
as the control proving the server didn't move. Results live in separate
tables (bench_run vs metrics) so neither contaminates the other, and
re-benching after every attack is the tripwire for unintended server-side
regressions, not just the scoreboard for intended wins.

Attack 1 is the worked example. The bench diff (run 1 vs run 2) shows
deltas of +10, -67, and +114 ms scattered in both directions across stages
the client-side flag cannot causally touch: run-to-run noise from
nondeterministic reply lengths, provider load, and Open-Meteo's tail. The
standard cuts both ways — the -67 ms TTFT "improvement" is dismissed along
with the +114 ms "regression". The only claim that survives is the one
with a mechanism (first audio stops waiting for the stream tail), measured
on human turns: -387 ms tap / -127 ms hold at p50, with endpointing
unchanged (1423 vs 1427 ms) as the attribution control.

## Clock discipline in the latency waterfall

Client and server timestamps come from different clocks, so no duration is
ever computed by subtracting across them. Client rows use client stamps,
server rows use server stamps, and the headline time-to-first-audio is pure
client-side (`t_first_audio − t_speech_end`), making it immune to skew. The
server's LLM/tool breakdown is displayed as an annotated sub-detail of the
client's "send → first byte" row, not stitched into one timeline.
