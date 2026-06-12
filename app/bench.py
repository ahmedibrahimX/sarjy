"""Latency bench harness — PLAN.md Phase 2, Attack 0.

Hits the real /chat SSE endpoint of a running Sarjy (local or deployed)
with a fixed turn set, N times each, and aggregates per-stage p50/p95.

Synthetic speech end: each turn's t_speech_end is stamped the moment the
request is sent. That simulates HOLD mode (explicit end signal, zero
endpointing), and runs are labeled `input_mode: hold, synthetic: true`.
Tap-mode endpointing and TTS-start timing only exist in a browser and are
measured there, not here.

The two derived columns are the Attack 1 story:
- full_stream_done_ms:      when audio could start WITHOUT pipelining
- first_sentence_ready_ms:  when audio could start WITH pipelining

Usage:
    uv run python -m app.bench --base-url http://127.0.0.1:8000 --name baseline-local
    # storing the run requires SARJY_ADMIN_TOKEN (env or --token)
"""

import argparse
import asyncio
import json
import os
import time

import httpx

TURNS = {
    "short_no_tool": "Say a one-sentence greeting.",
    "long_no_tool": "In exactly three sentences, describe a good morning routine.",
    "weather_tool": "What is the weather in Cairo right now?",
}

SENTENCE_END = (".", "!", "?", "؟")
MIN_FIRST_SENTENCE_CHARS = 12

STAGES = [
    "send_to_first_byte_ms",
    "server_ttft_ms",
    "server_tools_ms",
    "ack_ready_ms",
    "server_total_ms",
    "first_sentence_ready_ms",
    "full_stream_done_ms",
]


def now_ms() -> float:
    return time.time() * 1000


async def run_turn(
    http: httpx.AsyncClient, base_url: str, user_id: str, prompt: str
) -> dict:
    t_speech_end = now_ms()  # synthetic, hold-mode semantics
    first_byte: float | None = None
    first_sentence: float | None = None
    first_ack: float | None = None
    text = ""
    server: dict = {}
    async with http.stream(
        "POST",
        f"{base_url}/chat",
        json={
            "user_id": user_id,
            "session_id": f"bench-{user_id}",
            "message": prompt,
            "client_timestamps": {"t_speech_end": t_speech_end},
        },
    ) as response:
        response.raise_for_status()
        buf = ""
        async for chunk in response.aiter_text():
            if first_byte is None:
                first_byte = now_ms()
            buf += chunk
            while "\n\n" in buf:
                frame, buf = buf.split("\n\n", 1)
                for line in frame.splitlines():
                    if not line.startswith("data: "):
                        continue
                    event = json.loads(line[6:])
                    if event["type"] == "delta":
                        text += event["text"]
                        if (
                            first_sentence is None
                            and len(text) >= MIN_FIRST_SENTENCE_CHARS
                            and text.rstrip().endswith(SENTENCE_END)
                        ):
                            first_sentence = now_ms()
                    elif event["type"] == "tool_ack":
                        # when audio could start under OPT_TOOL_ACK (perceived floor)
                        if first_ack is None:
                            first_ack = now_ms()
                    elif event["type"] == "done":
                        server = event.get("server") or {}
                    elif event["type"] == "error":
                        raise RuntimeError(event.get("message", "server error"))
    stream_done = now_ms()
    if first_sentence is None:
        first_sentence = stream_done
    received = server.get("t_request_received")
    ttft = server.get("t_llm_first_token")
    complete = server.get("t_response_complete")
    return {
        "send_to_first_byte_ms": round((first_byte or stream_done) - t_speech_end, 1),
        "server_ttft_ms": round(ttft - received, 1) if ttft and received else None,
        "server_tools_ms": round(
            sum(t.get("duration_ms", 0) for t in server.get("tools") or []), 1
        ),
        "ack_ready_ms": round(first_ack - t_speech_end, 1) if first_ack else None,
        "server_total_ms": round(complete - received, 1) if complete and received else None,
        "first_sentence_ready_ms": round(first_sentence - t_speech_end, 1),
        "full_stream_done_ms": round(stream_done - t_speech_end, 1),
        "warmth": server.get("warmth", "unknown"),
        "chars": len(text),
    }


def pctl(values: list, p: float) -> float | None:
    """Nearest-rank percentile; honest at small N."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    return vals[min(len(vals) - 1, round(p / 100 * (len(vals) - 1)))]


def aggregate(turns: list[dict]) -> dict:
    agg: dict = {}
    for stage in STAGES:
        values = [t[stage] for t in turns]
        agg[stage] = {"p50": pctl(values, 50), "p95": pctl(values, 95)}
    agg["warm_count"] = sum(1 for t in turns if t["warmth"] == "warm")
    agg["cold_count"] = sum(1 for t in turns if t["warmth"] == "cold")
    return agg


def print_table(name: str, results: dict) -> None:
    print(f"\nbench: {name}")
    for turn_type, data in results.items():
        agg = data["agg"]
        print(f"\n  {turn_type}  (warm {agg['warm_count']} / cold {agg['cold_count']})")
        print(f"    {'stage':<28}{'p50':>9}{'p95':>9}")
        for stage in STAGES:
            p50, p95 = agg[stage]["p50"], agg[stage]["p95"]
            fmt = lambda v: f"{v:>8.0f}" if v is not None else f"{'-':>8}"
            print(f"    {stage:<28}{fmt(p50)} {fmt(p95)}")


async def main_async(args: argparse.Namespace) -> None:
    async with httpx.AsyncClient(timeout=90) as http:
        cfg = (await http.get(f"{args.base_url}/config")).json()
        selected = {
            k: v
            for k, v in TURNS.items()
            if not args.turns or k in args.turns.split(",")
        }
        results: dict = {}
        for turn_type, prompt in selected.items():
            turns = []
            for i in range(args.n):
                if args.cold_wait:
                    await asyncio.sleep(args.cold_wait)
                if args.prewarm:
                    try:
                        await http.post(f"{args.base_url}/warmup")
                        await asyncio.sleep(1)
                    except httpx.HTTPError:
                        pass
                turns.append(
                    await run_turn(http, args.base_url, f"bench-{turn_type}-{i}", prompt)
                )
                if not args.cold_wait:
                    await asyncio.sleep(args.sleep)
            results[turn_type] = {"turns": turns, "agg": aggregate(turns)}

        snapshot = {
            **cfg.get("flags", {}),
            "model": cfg.get("model"),
            "endpoint_threshold_ms": cfg.get("endpoint_threshold_ms"),
            "input_mode": "hold",
            "synthetic": True,
            "cold_wait_s": args.cold_wait,
            "prewarm_each_turn": args.prewarm,
        }
        print_table(args.name, results)

        token = args.token or os.environ.get("SARJY_ADMIN_TOKEN", "")
        if token:
            stored = await http.post(
                f"{args.base_url}/bench_runs",
                json={
                    "name": args.name,
                    "config_snapshot": snapshot,
                    "results": {"base_url": args.base_url, "n": args.n, "turn_types": results},
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            stored.raise_for_status()
            print(f"\nstored as bench_run id={stored.json()['id']}")
        else:
            print("\nnot stored (no SARJY_ADMIN_TOKEN)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--name", required=True)
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--token", default="")
    parser.add_argument("--turns", default="", help="comma-separated subset of turn types")
    parser.add_argument(
        "--cold-wait", type=float, default=0,
        help="sleep this many seconds BEFORE each turn (cold sampling)",
    )
    parser.add_argument(
        "--prewarm", action="store_true",
        help="POST /warmup before each turn, after the cold wait",
    )
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
