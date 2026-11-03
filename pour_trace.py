"""Inspector body for one Pour. Catalog search does not import this."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_TRUTHY_QUERY = frozenset({"1", "true", "yes", "on"})

TOOL_ORDER: dict[str, list[str]] = {
    "v1": ["text_search", "get_by_keys", "find_nodes", "return_result"],
    "v2": [
        "describe",
        "explain",
        "get",
        "find",
        "set",
        "order",
        "enrich",
        "project",
        "traverse",
        "search",
        "analyze",
        "return",
    ],
}


def debug_query_enabled(value: object | None) -> bool:
    """True when query debug is 1, true, yes, or on."""
    if value is True:
        return True
    if value is False or value is None:
        return False
    return str(value).strip().lower() in _TRUTHY_QUERY


def trace_payload(result: Any) -> dict[str, Any]:
    """Widget trace from public_trace. Hops copy only when that trace has none."""
    debug = result.debug
    raw = debug.public_trace if isinstance(debug.public_trace, Mapping) else {}
    trace: dict[str, Any] = dict(raw)
    if debug.notes:
        existing = list(trace.get("notes") or [])
        for note in debug.notes:
            if note not in existing:
                existing.append(note)
        trace["notes"] = existing
    if isinstance(debug.detective, Mapping):
        trace["detective"] = dict(debug.detective)
    if debug.preferred_req_id:
        raw_sess = trace.get("session")
        sess = dict(raw_sess) if isinstance(raw_sess, Mapping) else {}
        sess["preferred_req_id"] = debug.preferred_req_id
        trace["session"] = sess
    if debug.hops and not trace.get("hops"):
        trace["hops"] = [dict(hop) for hop in debug.hops if isinstance(hop, Mapping)]
    return trace


def inspector_envelope(
    result: Any,
    *,
    rewind: bool,
    chat_id: str,
    target: Any,
    mode: str,
    model: str,
    provider: str,
) -> dict[str, Any]:
    """Fields the chat-trace widget reads off a Pour response."""
    return {
        "rewind": bool(rewind),
        "chat_id": chat_id,
        "target": f"{target.bucket}/{target.scope}/{target.collection}",
        "mode": mode,
        "model": model,
        "provider": provider,
        "tool_order": {
            "v1": list(TOOL_ORDER["v1"]),
            "v2": list(TOOL_ORDER["v2"]),
        },
        "trace": trace_payload(result),
    }
