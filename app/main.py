import json
import logging
import os
import secrets
import sqlite3
import tempfile
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from starlette.background import BackgroundTask

from . import config, db, llm, memory, metrics

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("sarjy")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.conn = db.connect()
    app.state.http = httpx.AsyncClient(timeout=10)
    app.state.oai = AsyncOpenAI()
    app.state.model = os.environ.get("SARJY_MODEL", "gpt-4.1-mini")
    # Per-user, per-page-load conversation history, RAM only.
    app.state.history = {}
    yield
    await app.state.http.aclose()
    app.state.conn.close()


app = FastAPI(title="Sarjy", lifespan=lifespan)


@app.post("/chat")
async def chat(request: Request):
    body = await request.json()
    user_id = (body.get("user_id") or "anonymous").strip()
    session_id = (body.get("session_id") or "").strip()
    message = (body.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "empty message"}, status_code=400)

    state = request.app.state
    now = llm.now_ms()
    # Warmth heuristic: cold if the previous LLM call was >60s ago (or never).
    last = getattr(state, "last_llm_at", None)
    timings = {
        "t_request_received": now,
        "warmth": "cold" if last is None or now - last > 60_000 else "warm",
    }
    state.last_llm_at = now
    # A new page load sends a new session_id: the conversation resets, and
    # the SQLite facts table is the only thing that crosses sessions.
    entry = state.history.get(user_id)
    if entry is None or entry["session"] != session_id:
        entry = {"session": session_id, "messages": deque(maxlen=20)}
        state.history[user_id] = entry

    async def gen():
        try:
            turn = llm.run_turn(
                oai=state.oai,
                http=state.http,
                conn=state.conn,
                model=state.model,
                user_id=user_id,
                history=entry["messages"],
                message=message,
                timings=timings,
            )
            async for event in turn:
                yield f"data: {json.dumps(event)}\n\n"
        except Exception:
            log.exception("turn failed")
            error = {"type": "error", "message": "Sarjy hit an internal error on this turn."}
            yield f"data: {json.dumps(error)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/config")
async def get_config(request: Request):
    return {
        "flags": config.flags(),
        "endpoint_threshold_ms": config.endpoint_threshold_ms(),
        "model": request.app.state.model,
    }


@app.post("/metrics")
async def post_metrics(request: Request):
    body = await request.json()
    user_id = (body.get("user_id") or "anonymous").strip()
    turn = body.get("turn") or {}
    # Turn payloads carry timings and labels only — never transcript text.
    # The dashboard reading these rows is public, so keep it that way.
    client = turn.get("client") or {}
    snap = config.snapshot(request.app.state.model, client.get("endpoint_threshold_ms"))
    # input_mode rides in the snapshot so the dashboard slices it like any
    # other dimension; hold and tap distributions must never be mixed.
    snap["input_mode"] = client.get("input_mode") or "unknown"
    # One structured JSON line per turn, plus a SQLite row for later analysis.
    log.info(json.dumps({"event": "turn_metrics", "user_id": user_id, "turn": turn, "config": snap}))
    metrics.save_turn(request.app.state.conn, user_id, turn, snap)
    return {"ok": True}


@app.get("/memories")
async def list_memories(request: Request, user_id: str = ""):
    facts = memory.list_facts(request.app.state.conn, user_id.strip())
    return {"facts": facts}


@app.delete("/memories/{fact_id}")
async def delete_memory(request: Request, fact_id: int, user_id: str = ""):
    deleted = memory.delete_fact(request.app.state.conn, user_id.strip(), fact_id)
    return {"deleted": deleted}


def _admin_guard(request: Request) -> JSONResponse | None:
    """None when authorized; an error response otherwise."""
    expected = os.environ.get("SARJY_ADMIN_TOKEN")
    if not expected:
        return JSONResponse({"error": "admin endpoints disabled"}, status_code=404)
    provided = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not secrets.compare_digest(provided, expected):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None


@app.post("/admin/metrics/clear")
async def clear_metrics(request: Request):
    """Purge turn metrics (facts and bench runs untouched). Used to discard
    rows collected under older measurement methodology or demo junk."""
    denied = _admin_guard(request)
    if denied:
        return denied
    deleted = metrics.clear_turns(request.app.state.conn)
    log.info(json.dumps({"event": "metrics_cleared", "rows": deleted}))
    return {"deleted": deleted}


@app.post("/bench_runs")
async def create_bench_run(request: Request):
    """Store a bench run (write path is admin-gated; dashboard reads are public)."""
    denied = _admin_guard(request)
    if denied:
        return denied
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name required"}, status_code=400)
    run_id = metrics.save_bench_run(
        request.app.state.conn,
        name,
        body.get("config_snapshot") or {},
        body.get("results") or {},
    )
    return {"id": run_id}


@app.get("/dashboard")
async def dashboard_page():
    """Public latency dashboard — timings and config only, never content."""
    return FileResponse(STATIC_DIR / "dashboard.html", media_type="text/html")


@app.get("/api/turns")
async def api_turns(request: Request, limit: int = 20):
    limit = max(1, min(limit, 500))
    return {"turns": metrics.recent_turns(request.app.state.conn, limit)}


@app.get("/api/bench_runs")
async def api_bench_runs(request: Request):
    return {"runs": metrics.list_bench_runs(request.app.state.conn)}


@app.get("/api/bench_runs/{run_id}")
async def api_bench_run(request: Request, run_id: int):
    run = metrics.get_bench_run(request.app.state.conn, run_id)
    if run is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return run


@app.get("/admin/db")
async def export_db(request: Request):
    """Token-gated snapshot of the SQLite file, for offline metrics analysis."""
    denied = _admin_guard(request)
    if denied:
        return denied
    # Backup API gives a consistent snapshot even mid-write.
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        snapshot_path = tmp.name
    dest = sqlite3.connect(snapshot_path)
    request.app.state.conn.backup(dest)
    dest.close()
    return FileResponse(
        snapshot_path,
        filename="sarjy-snapshot.db",
        media_type="application/octet-stream",
        background=BackgroundTask(os.unlink, snapshot_path),
    )


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
