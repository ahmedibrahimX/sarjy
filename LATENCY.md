# Sarjy — Latency Deep Dive (Time-to-First-Audio)

The working document for Phase 2. Populated as each attack lands; nothing
here is claimed without a stored bench run or labeled dashboard data behind
it.

## Metric definitions

- **TTFA (actual):** speech end → first audio of substantive content.
- **TTFA (perceived):** speech end → first audio of any speech, including
  tool acknowledgments. Never conflated with actual.
- **Speech end is defined per input mode** — `hold`: the mic/space release
  (explicit signal, endpointing ~0); `tap`: VAD-detected silence; `typed`:
  submission time. Distributions are never mixed across modes.
- Every turn labeled `warm`/`cold` (server-side: cold = first LLM call in
  60s) and `tool`/`no-tool`. p50/p95 over N runs; no single-turn anecdotes.
- Every metrics row and bench run stores a `config_snapshot` (all OPT_*
  flags, model, endpointing threshold, input mode), so each improvement is
  attributable to the flag that caused it.

## Input modes: explicit signal beats VAD

Hold-to-talk releases give an exact, free speech-end signal — endpointing
cost is ~0 by construction, which makes hold turns the control group.
Tap mode pays the endpointing wait (first anecdote ~865 ms; the manual
protocol below measured p50 ~1.4 s on Chrome's native endpointer), and
Attack 3's threshold curve is the price of going hands-free: phone calls
and smart speakers have no spacebar.

Note on old data: all metrics collected before the input-mode label (and
before the VAD, in the earliest rows) were discarded — they were measured
with three different rulers and could not be relabeled honestly.

## Baseline (Phase 1 pipeline, all OPT_* flags off)

Anecdotal reference: the recorded demo's warm weather turn showed ~4.1 s
TTFA (tap mode, Chrome endpointer), decomposed as ~865 ms endpointing,
~0.5 s warm TTFT, ~1.25 s weather tool, ~2.1 s stream tail, ~10 ms TTS.

Canonical baseline bench runs (synthetic hold mode, server+network stages):

### Local (iteration reference only)

`baseline-local`, bench_run id=1 (local DB), N=10, synthetic hold mode, ms:

| stage | short p50 | short p95 | long p50 | long p95 | weather p50 | weather p95 |
| --- | --- | --- | --- | --- | --- | --- |
| send to first byte | 648 | 1546 | 508 | 582 | 662 | 2096 |
| server TTFT | 647 | 1545 | 507 | 581 | 595 | 1990 |
| server tools | 0 | 0 | 0 | 0 | 147 | 681 |
| server total | 734 | 1757 | 1000 | 1130 | 1688 | 3055 |
| first sentence ready | 725 | 1705 | 672 | 748 | 1563 | 2919 |
| full stream done | 735 | 1758 | 1001 | 1131 | 1690 | 3056 |

Early reads (local only, do not headline): pipelining's gap (first sentence
vs full stream) is ~330 ms p50 on long answers and ~10 ms on one-sentence
answers — the win scales with reply length. The weather tool cost only
~150 ms p50 from this machine vs ~1250 ms measured from Railway — network
path dominates tool cost, which is exactly why headline numbers only come
from the deployed instance.

### Deployed (the headline baseline)

`baseline-prod`, bench_run id=1 (prod DB), N=10, synthetic hold mode, all
flags off, ms:

| stage | short p50 | short p95 | long p50 | long p95 | weather p50 | weather p95 |
| --- | --- | --- | --- | --- | --- | --- |
| send to first byte | 705 | 2205 | 630 | 1312 | 759 | 919 |
| server TTFT | 453 | 1405 | 380 | 1038 | 454 | 614 |
| server tools | 0 | 0 | 0 | 0 | 309 | 2140 |
| server total | 647 | 1510 | 936 | 1435 | 1714 | 3376 |
| first sentence ready | 756 | 2409 | 835 | 1442 | 1711 | 3456 |
| full stream done | 922 | 2409 | 1183 | 1688 | 1978 | 3664 |

Reads:
- Audio-ready floor without pipelining (hold mode, plus ~10 ms TTS):
  ~0.9 s short / ~1.2 s long / ~2.0 s weather at p50. The warm no-tool
  target (<1.5 s actual) looks reachable; the tool-turn perceived target
  rides on Attack 2's acknowledgments.
- Pipelining gap (full stream vs first sentence): ~350 ms p50 on long
  answers, ~270 ms on weather turns.
- Weather tool: p50 309 ms but p95 2140 ms from Railway — heavy tail
  (likely connection setup to Open-Meteo); the geocode cache and a shared
  keep-alive pool should compress it.
- Warm TTFT from Railway (380-455 ms p50) beats local (~500-650 ms) —
  Railway sits closer to OpenAI than a Cairo ISP does.

### In-browser client stages (manual protocol)

Human baseline on the deployed instance, 2026-06-12, one speaker/mic/room,
fixed phrases, all flags off. Warm turns only (cold singletons noted), ms:

| condition | n | TTFA p50 | TTFA p95 | endpoint p50 | send to 1st byte p50 | stream p50 | tts p50 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tap, no-tool | 9 | 2909 | 3391 | 1427 | 824 | 494 | 4 |
| hold, no-tool | 9 | 1356 | 4325 | 139 | 747 | 531 | 4 |
| tap, weather | 4 | 4991 | 5113 | 1470 | 1158 | 2378 | 6 |
| hold, weather | 5 | 3265 | 4238 | 118 | 998 | 2150 | 4 |

(plus one cold turn each in tap/no-tool, hold/no-tool, tap/weather; the
hold/weather block ran immediately after tap, so it has no cold sample)

Findings:

- **Chrome's endpointer costs ~1.3 s, measured on a human.** Tap endpoint
  p50 is 1427-1470 ms vs 118-139 ms for an explicit hold release (which is
  just the forced-finalize cost). The early single-turn anecdote said
  ~865 ms; the distribution says it's worse. Same phrase, same network,
  same model: hold beats tap by ~1.55 s p50 — that is Attack 3's prize and
  its control group in one table.
- **Hold no-tool is already at 1356 ms p50 TTFA with zero optimizations** —
  under the 1.5 s target. The honest framing: explicit endpointing alone
  nearly clears the warm no-tool target; the optimizations have to win the
  tap path and the tool path.
- **TTS engine is 4-13 ms across all 30 human turns** — browser synthesis
  confirmed negligible at distribution level, not just anecdote.
- **Recognition start-up clips speech in hold mode.** 3 of 10 hold turns
  lost their first syllables ("me something interesting...") because
  SpeechRecognition takes a beat to open the stream after the press, and
  hold users start talking immediately. A ready cue (short beep when
  capture actually starts) is parked in IDEAS.md — a real UX cost of
  push-to-talk that tap mode hides.

## Attack log

One section per attack: what changed, the flag, before/after p50/p95 table
(stored bench run ids), verdict, and anything that failed and why.

### Attack 1 — sentence-level TTS pipelining (OPT_SENTENCE_PIPELINING)

(pending)

### Attack 2 — tool acknowledgments (OPT_TOOL_ACK) + geocode cache (OPT_GEOCODE_CACHE)

(pending)

### Attack 3 — endpointing threshold, tap mode only (OPT_VAD_ENDPOINT)

(pending — tradeoff curve at three thresholds, hold turns as control)

### Attack 4 — cold start: keep-alive (OPT_KEEPALIVE), pre-warm (OPT_PREWARM), prefix caching

(pending — prefix-cache experiment pre-registered as a likely null result:
prompt is ~300 tokens, OpenAI automatic caching starts at ~1k)

### Attack 5 (stretch) — model TTFT A/B through the provider seam

(pending)

## Failed experiments

(populated as they happen — a measured null result with a kept-but-off
toggle is a deliverable, not a waste)

## Targets

- Warm no-tool turn: < 1.5 s TTFA (actual), p50
- Tool turn: < 2 s TTFA (perceived), p50

If a target is missed, the honest analysis of why goes here.

## With another week

(running list: per-user adaptive endpointing, edge deployment close to
users, speculative first clause, streaming STT to control endpointing
server-side)
