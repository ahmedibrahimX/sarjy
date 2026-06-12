/* Shared waterfall rendering for the debug console (index.html) and the
   public dashboard (/dashboard). One stage model and color scheme, two
   presentations: per-stage rows and a single stacked bar. Pure functions:
   turn data in, HTML out. Exposes window.WF. */
"use strict";

window.WF = (() => {
  // Perceived-latency basis, per input mode: explicit release wins, then
  // VAD speech end, then last interim transcript, then Chrome's stamp.
  function speechEnd(c) {
    return c.release ?? c.speech_end_vad ?? c.last_interim ?? c.speech_end ?? null;
  }

  // Stage list from a turn {client:{...}, server:{...}}. Optional Phase 2
  // stamps (first_sentence_complete, tts_enqueue_first) add stages when
  // present, so this renderer needs no edits as attacks land.
  function stages(turn) {
    const c = turn.client || {};
    const t0 = speechEnd(c);
    const list = [
      { lbl: "stt endpoint+final", cls: "stt", from: t0, to: c.transcript_final },
      { lbl: "send → 1st byte", cls: "net", from: c.request_sent, to: c.first_byte },
      { lbl: "stream rest", cls: "stream", from: c.first_byte, to: c.stream_done },
    ];
    if (c.first_sentence_complete != null) {
      list.push({ lbl: "first sentence", cls: "sent", from: c.first_byte, to: c.first_sentence_complete });
    }
    if (c.tts_enqueue_first != null) {
      list.push({ lbl: "tts enqueue", cls: "tts", from: c.tts_enqueue_first, to: c.first_audio });
    } else {
      list.push({ lbl: "tts engine", cls: "tts", from: c.tts_start, to: c.first_audio });
    }
    return { t0, list };
  }

  // TTFA composition: non-overlapping segments that sum to first audio.
  // The single stacked bar must not paint overlapping spans or stages that
  // run past its own total — in pipelined turns the full stream continues
  // underneath the audio, and the rows view shows that overlap honestly.
  function ttfaStages(turn) {
    const c = turn.client || {};
    const t0 = speechEnd(c);
    const list = [
      { lbl: "endpoint+stt", cls: "stt", from: t0, to: c.transcript_final },
      { lbl: "send → 1st byte", cls: "net", from: c.request_sent, to: c.first_byte },
    ];
    if (c.first_sentence_complete != null) {
      list.push({ lbl: "first sentence", cls: "sent", from: c.first_byte, to: c.first_sentence_complete });
      list.push({ lbl: "tts", cls: "tts", from: c.tts_enqueue_first ?? c.first_sentence_complete, to: c.first_audio });
    } else {
      list.push({ lbl: "stream", cls: "stream", from: c.first_byte, to: c.stream_done });
      list.push({ lbl: "tts", cls: "tts", from: c.tts_start ?? c.stream_done, to: c.first_audio });
    }
    return { t0, list };
  }

  function segment(s, t0, totalMs) {
    if (s.from == null || s.to == null) return null;
    const ms = Math.max(0, s.to - s.from);
    const left = Math.min(100, ((s.from - t0) / totalMs) * 100);
    const width = Math.max(0.4, Math.min(100 - left, (ms / totalMs) * 100));
    return { ms, left, width };
  }

  // Per-stage rows (the debug-console presentation).
  function rowsHtml(turn, totalMs) {
    const { t0, list } = stages(turn);
    if (t0 == null || !totalMs) return "";
    return list.map((s) => {
      const seg = segment(s, t0, totalMs);
      if (!seg) return "";
      return `<div class="wf-row">
        <span class="lbl">${s.lbl}</span>
        <span class="wf-track"><span class="wf-bar ${s.cls}" style="left:${seg.left}%;width:${seg.width}%"></span></span>
        <span class="ms">${Math.round(seg.ms)} ms</span>
      </div>`;
    }).join("");
  }

  // Single stacked bar (the dashboard feed presentation) — TTFA composition.
  function barHtml(turn, totalMs) {
    const { t0, list } = ttfaStages(turn);
    if (t0 == null || !totalMs) return "";
    const segs = list.map((s) => {
      const seg = segment(s, t0, totalMs);
      if (!seg) return "";
      return `<span class="wf-bar ${s.cls}" title="${s.lbl}: ${Math.round(seg.ms)} ms" style="left:${seg.left}%;width:${seg.width}%"></span>`;
    }).join("");
    return `<span class="wf-track wf-stack">${segs}</span>`;
  }

  return { speechEnd, stages, ttfaStages, rowsHtml, barHtml };
})();
