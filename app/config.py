import os

# Optimization flags, all default off. The server environment is the single
# source of truth; GET /config exposes them so the client applies the
# client-side ones at page load. Every metrics row and bench run stores a
# snapshot of these values so improvements are attributable.
FLAG_NAMES = [
    "OPT_SENTENCE_PIPELINING",
    "OPT_TOOL_ACK",
    "OPT_GEOCODE_CACHE",
    "OPT_VAD_ENDPOINT",
    "OPT_KEEPALIVE",
    "OPT_PREWARM",
]

DEFAULT_ENDPOINT_THRESHOLD_MS = 400

# What Phase 1 effectively ran with: no optimizations, Chrome's native
# endpointer (threshold None = not ours). Used to backfill old metrics rows.
PHASE1_SNAPSHOT = {
    **{name: False for name in FLAG_NAMES},
    "model": "gpt-4.1-mini",
    "endpoint_threshold_ms": None,
}


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def flags() -> dict:
    return {name: _truthy(os.environ.get(name)) for name in FLAG_NAMES}


def endpoint_threshold_ms() -> int:
    try:
        return int(os.environ.get("ENDPOINT_THRESHOLD_MS", ""))
    except ValueError:
        return DEFAULT_ENDPOINT_THRESHOLD_MS


def snapshot(model: str, effective_threshold_ms: float | None = None) -> dict:
    """The config fingerprint stored with every metrics row and bench run.

    `effective_threshold_ms` is what the client actually used this turn
    (the debug-console slider can override the env default).
    """
    return {
        **flags(),
        "model": model,
        "endpoint_threshold_ms": effective_threshold_ms
        if effective_threshold_ms is not None
        else endpoint_threshold_ms(),
    }
