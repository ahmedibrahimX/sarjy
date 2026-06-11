import json
import logging
import os
import secrets
import sqlite3
import tempfile
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from starlette.background import BackgroundTask

from . import db, llm, memory, metrics

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("sarjy")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.conn = db.connect()
    app.state.http = httpx.AsyncClient(timeout=10)
    app.state.oai = AsyncOpenAI()
    app.state.model = os.environ.get("SARJY_MODEL", "gpt-4.1-mini")
    # Per-user session history, RAM only — long-term memory lives in SQLite.
    app.state.history = defaultdict(lambda: deque(maxlen=20))
    yield
    await app.state.http.aclose()
    app.state.conn.close()


app = FastAPI(title="Sarjy", lifespan=lifespan)


@app.post("/chat")
async def chat(request: Request):
    body = await request.json()
    user_id = (body.get("user_id") or "anonymous").strip()
    message = (body.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "empty message"}, status_code=400)

    timings = {"t_request_received": llm.now_ms()}
    state = request.app.state

    async def gen():
        try:
            turn = llm.run_turn(
                oai=state.oai,
                http=state.http,
                conn=state.conn,
                model=state.model,
                user_id=user_id,
                history=state.history[user_id],
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


@app.post("/metrics")
async def post_metrics(request: Request):
    body = await request.json()
    user_id = (body.get("user_id") or "anonymous").strip()
    turn = body.get("turn") or {}
    # One structured JSON line per turn, plus a SQLite row for later analysis.
    log.info(json.dumps({"event": "turn_metrics", "user_id": user_id, "turn": turn}))
    metrics.save_turn(request.app.state.conn, user_id, turn)
    return {"ok": True}


@app.get("/memories")
async def list_memories(request: Request, user_id: str = ""):
    facts = memory.list_facts(request.app.state.conn, user_id.strip())
    return {"facts": facts}


@app.delete("/memories/{fact_id}")
async def delete_memory(request: Request, fact_id: int, user_id: str = ""):
    deleted = memory.delete_fact(request.app.state.conn, user_id.strip(), fact_id)
    return {"deleted": deleted}


@app.get("/admin/db")
async def export_db(request: Request):
    """Token-gated snapshot of the SQLite file, for offline metrics analysis."""
    expected = os.environ.get("SARJY_ADMIN_TOKEN")
    if not expected:
        return JSONResponse({"error": "export disabled"}, status_code=404)
    provided = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not secrets.compare_digest(provided, expected):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
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
