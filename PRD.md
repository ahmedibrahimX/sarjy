# Sarjy — PRD

2026-06-12. Written per the task rubric's recommendation of a short planning
doc. The original plan-before-code is commit `55a1f15` (PLAN.md, the
project's first commit); this is the consolidated version including what we
learned. This document is a snapshot: it states intent and targets only —
results live in LATENCY.md and are not duplicated here.

## 1. Problem & goal

Build, deploy, and present a voice assistant ("Sarjy") for the Sarj.ai
take-home: voice in/out, memory across sessions, one genuinely useful
external API, publicly accessible. Ship the minimum bar fast and spend the
remaining budget on one deep dive done well. Chosen deep dive: latency
(time-to-first-audio).

## 2. Scope (minimum bar, as shipped)

- Voice I/O in the browser (Web Speech API; no server-side audio).
  Hybrid push-to-talk: tap auto-endpoints, holding mic/space keeps
  recognition open through pauses.
- Cross-session memory: an explicit remember_fact tool writing to SQLite,
  visible and deletable in a memories sidebar. Conversation history is
  session-scoped; only stored facts cross sessions.
- External API: current weather via Open-Meteo (keyless, so any evaluator
  can use the deployed demo with zero setup).
- Deployed on Railway (Docker, persistent volume), single FastAPI app,
  single static frontend, no build step.

## 3. Non-goals

No vector DB or RAG (memory is a key-value problem here). No auth beyond a
per-browser id and a token gate on admin endpoints. No external/streaming
TTS provider (browser TTS measured at ~10 ms; the pipeline shape was the
problem). No WebRTC/telephony, no wake word, no barge-in beyond
cancel-on-interrupt, no Postgres (snapshot export covers inspection), no
observability stack (SQLite plus one dashboard page is the right size
here). Parking lot for all of these: IDEAS.md.

## 4. Deep dive: latency

Why this one: time-to-first-audio is the product metric for a voice-agents
company — the difference between feeling alive and feeling like an IVR —
and it is a systems problem (streaming pipelines, connection lifecycle,
tails, instrumentation), which is where my background gives the most depth.

Metric definitions (fixed vocabulary):

- TTFA (actual): speech end to first audio of substantive content.
- TTFA (perceived): speech end to first audio of any speech, including
  acknowledgments. Never conflated with actual.
- Speech end is defined per input mode: hold = the mic/space release
  (explicit signal); tap = VAD-detected silence. The two modes are never
  mixed in one distribution.
- Every turn is labeled warm/cold and tool/no-tool; claims are p50/p95
  over N runs, never single-turn anecdotes.

Success targets (p50, on the deployed instance):

- Warm no-tool turn: under 1.5 s TTFA (actual).
- Tool turn: under 2 s TTFA (perceived).

## 5. Approach

Measure first, then attack: instrument every stage on both clocks (client
and server, never mixed), freeze a baseline, then one attack at a time,
each behind an OPT_* env toggle so every improvement is attributable to
the flag that caused it and reverts are free. Two instruments with
disjoint blind spots: a headless bench harness (fixed prompts, N
repetitions, server/network stages, stored and diffable runs) and a human
protocol in the browser (endpointing, TTS, perceived latency). Every
metrics row stores a config snapshot. This is measurement-driven
development with deliberately scoped unit tests: pure logic (memory,
schema migration, sentence splitting, the SSE event contract) is tested;
verification effort otherwise goes to instrumentation and live probing of
the deployed system. Failed experiments are deliverables: a measured null
result is recorded with its toggle kept off, not deleted.

## 6. Architecture summary

One FastAPI app, one SQLite file (facts, metrics, bench runs, geocode
cache, on a persistent volume), one vanilla-JS page, plus a public
read-only latency dashboard over the same data. LLM behind a thin provider
seam (OpenAI today; the seam exists so a model/provider A/B is a module
swap). Diagram: README.md. Key tradeoffs: SQLite over a database server
(right-sized, snapshot-exportable), browser TTS kept on evidence (~10 ms
measured), boring technology everywhere the deep dive is not.

## 7. What changed vs the original plan

- The mic-energy VAD was built as an instrument (Chrome's speech events
  hide the endpointing delay; the first waterfalls read "0 ms" — the
  instrument was lying) and only later became an actuator (Attack 3's
  threshold endpointing).
- input_mode labeling (tap/hold/typed) was added mid-phase when
  hold-to-talk turned out to change the endpointing story entirely: an
  explicit release is a free, exact speech-end signal, so hold turns are
  the control group and Attack 3 is scoped to tap mode.
- The dashboard's stacked bar was redefined to TTFA composition after
  pipelining made stages overlap (audio now starts while the stream is
  still arriving).

## 8. Open questions / next week

- Per-user adaptive endpointing (learn a speaker's pause profile instead
  of one global threshold).
- Cross-provider TTFT comparison through the provider seam (Groq's TTFT
  is the obvious candidate); within-provider model comparison is the
  stretch attack's scope.
- First-token stalls (observed: a 6.8 s OpenAI TTFT outlier) — timeout
  and retry, or speculative filler past a threshold.
- Production observability: ship the same per-turn events to a real
  pipeline instead of SQLite.
- Recognition start-up clipping in hold mode (a ready cue when capture
  actually opens).
