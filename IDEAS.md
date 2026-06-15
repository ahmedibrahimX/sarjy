# Ideas parking lot

Things that came up during Phase 1 and were deliberately NOT built. Phase 2
candidates or presentation "what I'd do next" material.

- Sentence-chunked streaming TTS (speak first sentence while the rest streams) — the Phase 2 headline.
- Server-side streaming TTS provider instead of browser `speechSynthesis`.
- Barge-in: interrupt Sarjy mid-reply by starting to talk.
- Speculative TTS on the first clause before the LLM finishes the sentence.
- Conversation summarization for long-term memory instead of discrete facts.
- Arabic / bilingual support (Web Speech API `lang` switching).
- Wake word ("Hey Sarjy") instead of push-to-talk.
- Voice picker UI for `speechSynthesis` voices.
- Per-user metrics dashboard aggregating waterfalls across turns (p50/p95).
- Managed Postgres (Railway add-on) if live DB inspection over JDBC becomes a
  real requirement — today the token-gated snapshot export covers it (DBeaver
  opens SQLite files natively).
- Ready cue for hold mode: a short beep/visual tick when SpeechRecognition
  actually starts capturing — holders start talking instantly and 3/10
  protocol turns lost their first syllables to recognition start-up.
- Production-grade VAD (WebRTC VAD or Silero) to replace the energy-threshold
  detector. Ours flags voice as louder-than-adaptive-noise-floor, so loud
  non-speech (a door, a keyboard) can re-stamp last-voice and compress the
  endpoint measurement — the documented artifact class. WebRTC's GMM and
  Silero's neural classifier model what speech *is* and reject non-speech
  noise. The energy detector was the right tool to expose the endpointing
  cost with zero dependencies; a classifier is the swap if VAD-driven
  endpointing ships for real.
- Multi-day weather forecast: Open-Meteo already supports it (`daily=...`,
  up to 16 days); add an optional `when` arg to the get_weather tool and
  branch the request. Out of scope now — the tool exists to demonstrate a
  real tool-call round-trip, not to be a weather product (PRD non-goal).
- Cross-platform voice input: mobile (single-owner mic, divergent
  continuous-mode behavior) and Firefox/Safari (no SpeechRecognition)
  currently fall back to typed input. A server-side streaming-STT provider
  is the swap if cross-platform voice ever becomes a requirement — a
  speech-engineering project, not a latency one (PRD non-goal).
