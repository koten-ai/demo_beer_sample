
#!/usr/bin/env python3
'''Beer-sample catalog UI — FastAPI BFF.

Search follows demo_travel_sample: call rt.agent.run_turn and omit
chat_request so AgentAPI.run_turn calls catalog.load_for_turn
(SCOPE BRIEF + MINI-SCHEMA merge). Do not pass a frozen catalog body.
This BFF does not build a pipeline request.
Scaffolded by zeus_dev_helper_mcp use_sample(sample=beer).
'''
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from zeus_client import TurnStatus, ZeusRuntime, user_facing_answer
from zeus_client.adapters.catalog_fs.store import FsCatalogStore
from zeus_client.adapters.llm_openai_compatible import OpenAICompatibleLlmClient
from zeus_client.adapters.zeus_http import HttpxZeusPort
from zeus_client.adapters.zeus_http.catalog_remote import HttpxCatalogRemote
from zeus_client.domain.catalog import chat_request_filename, scope_chat_requests_subdir
from zeus_client.domain.errors import ZeusClientError

logger = logging.getLogger("demo_beer_sample")

_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env")

PAGE_CAP = 50
PORT = int(os.environ.get("PORT") or "8090")

_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_list_checked = False
_offset_honored = False
_LIST_CACHE_CAP = 30.0
_runtime_obj: ZeusRuntime | None = None


def _overlay_client_env() -> None:
    '''Map beer .env names onto the client loader's ZEUS_CLIENT_* keys.'''
    pairs = (
        ("ZEUS_URL", "ZEUS_CLIENT_URL"),
        ("ZEUS_AUTH_MODE", "ZEUS_CLIENT_AUTH_MODE"),
        ("ZEUS_USERNAME", "ZEUS_CLIENT_USERNAME"),
        ("ZEUS_USER", "ZEUS_CLIENT_USERNAME"),
        ("ZEUS_BUCKET", "ZEUS_CLIENT_BUCKET"),
        ("ZEUS_SCOPE", "ZEUS_CLIENT_SCOPE"),
        ("ZEUS_COLLECTION", "ZEUS_CLIENT_COLLECTION"),
        ("ZEUS_MODE", "ZEUS_CLIENT_MODE"),
        ("LLM_BASE_URL", "ZEUS_CLIENT_LLM_BASE_URL"),
        ("LLM_MODEL", "ZEUS_CLIENT_LLM_MODEL"),
    )
    for src, dst in pairs:
        val = (os.environ.get(src) or "").strip()
        if val and not (os.environ.get(dst) or "").strip():
            os.environ[dst] = val
    chat = ""
    for key in (
        "ZEUS_CHAT_REQUESTS_DIR",
        "ZEUS_CLIENT_CHAT_REQUESTS_DIR",
        "ZEUS_CHAT_REQUEST_DIR",
    ):
        chat = (os.environ.get(key) or "").strip()
        if chat:
            break
    if not chat:
        chat = str(_ROOT / "data" / "chat_requests")
    os.environ["ZEUS_CLIENT_CHAT_REQUESTS_DIR"] = chat


def _build_runtime() -> ZeusRuntime:
    '''Wire Zeus, LLM, catalog store, and catalog remote the way travel does.'''
    _overlay_client_env()
    rt = ZeusRuntime.from_config(_ROOT / "config.json", profile="development")
    secrets = rt.services.secrets
    rt.services.zeus = HttpxZeusPort(
        endpoint=rt.config.zeus, secrets=secrets, journal=rt.journal
    )
    rt.services.llm = OpenAICompatibleLlmClient(
        config=rt.config.llm, secrets=secrets, journal=rt.journal
    )
    chat_dir = rt.config.chat_requests_dir or str(_ROOT / "data" / "chat_requests")
    rt.services.catalog = FsCatalogStore(root=chat_dir)
    rt.services.catalog_remote = HttpxCatalogRemote(
        endpoint=rt.config.zeus, secrets=secrets
    )
    return rt


def _copy_live_pin(chat_dir: Path, bucket: str, scope: str, mode: str) -> Path | None:
    '''Copy the synced scope file to the live pin filename.

    The client loads ``<bucket>__<scope>/chat_request_<mode>_v2.json`` when
    ``base_id`` is unset. The pin name (``chat_request_analytics_base-6.1.json``
    today) is the same bytes, for the operator. The loader does not open that
    name unless ``base_id`` is set.
    '''
    if not bucket or not scope or not mode:
        return None
    scope_file = (
        chat_dir
        / scope_chat_requests_subdir(bucket, scope)
        / chat_request_filename(mode)
    )
    if not scope_file.is_file():
        return None
    try:
        body = json.loads(scope_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    lineage = body.get("_lineage") if isinstance(body, dict) else None
    base_id = ""
    if isinstance(lineage, dict):
        base_id = str(lineage.get("base_id") or "").strip()
    if not base_id or "/" in base_id or "\\" in base_id or ".." in base_id:
        return None
    dest = chat_dir / chat_request_filename(mode, base_id)
    data = scope_file.read_bytes()
    if dest.is_file():
        try:
            if dest.read_bytes() == data:
                return dest
        except OSError:
            return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


async def _sync_catalog(rt: ZeusRuntime) -> None:
    '''Fetch the live pin into the scope path. A failed sync stays a later 502.'''
    try:
        await rt.catalog.sync()
    except Exception:
        logger.warning("beer catalog sync failed", exc_info=True)
    chat = Path(rt.config.chat_requests_dir or (_ROOT / "data" / "chat_requests"))
    _copy_live_pin(
        chat,
        rt.config.target.bucket,
        rt.config.target.scope,
        rt.config.settings.mode or "analytics",
    )


def _runtime() -> ZeusRuntime:
    global _runtime_obj
    if _runtime_obj is None:
        _runtime_obj = _build_runtime()
    return _runtime_obj


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    rt = _runtime()
    await _sync_catalog(rt)
    try:
        yield
    finally:
        global _runtime_obj
        rt = _runtime_obj
        _runtime_obj = None
        if rt is not None:
            await rt.aclose()


app = FastAPI(title="Beer catalog UI", version="0.1.0", lifespan=_lifespan)
_static = _ROOT / "static"
if _static.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")


def _cache_ttl() -> float:
    raw = (os.environ.get("CELLAR_CACHE_TTL") or "600").strip()
    try:
        return float(raw)
    except ValueError:
        return 600.0


def _list_cache_ttl() -> float:
    '''List cache stays off until one offset probe has finished, then at most 30s.'''
    if not _list_checked:
        return 0.0
    raw = _cache_ttl()
    if raw <= 0:
        return 0.0
    return min(raw, _LIST_CACHE_CAP)


def _force_closed(text: str) -> bool:
    return "session_force_closed" in (text or "").lower()

_CARD_DISPLAY_KEYS = ('style', 'category', 'abv', 'ibu', 'srm', 'brewery', 'description')

_CARD_SKIP_KEYS = frozenset({'job_fingerprint', 'provenance', 'entity_refs', 'step_costs', 'query_decomposition', 'meta', 'wish_i_knew', 'decomposition', 'node_refs'})

_CARD_LIST_KEYS = ('rows', 'items', 'results', 'entities', 'matches', 'nodes', 'data', 'result', 'body', 'result_json', 'snippet')

_CARD_FILTER_KEYS = frozenset({'offset', 'query_text', 'entity_type', 'where', 'query', 'return', 'limit', 'predicates'})

_HOP_TITLES = frozenset({'order', 'pipeline', 'get', 'traverse', 'return', 'search', 'find', 'project', 'describe', 'enrich'})

def _parse_blob(payload: Any) -> Any:
    if isinstance(payload, str):
        text = payload.strip()
        if not text or text[0] not in "{[":
            return None
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            return None
    return payload

def _is_hop_title(name: str) -> bool:
    return name.strip().casefold() in _HOP_TITLES

def _card_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Beer card from a find/get row. A where-bag is not a product row."""
    body = row.get("body")
    merged = dict(row)
    if isinstance(body, dict):
        merged = dict(body)
        for key in ("id", "node_id", "doc_key"):
            if row.get(key) and not merged.get(key):
                merged[key] = row[key]
    name = merged.get("name") or merged.get("title")
    if not isinstance(name, str) or not name.strip() or _is_hop_title(name):
        return None
    if set(merged) <= _CARD_FILTER_KEYS:
        return None
    if not any(k in merged and merged.get(k) not in (None, "") for k in _CARD_DISPLAY_KEYS):
        return None
    description = merged.get("description") or merged.get("snippet") or ""
    if not isinstance(description, str):
        description = ""
    return {
        "id": str(merged.get("id") or merged.get("node_id") or ""),
        "name": name.strip(),
        "style": merged.get("style") or "",
        "category": merged.get("category") or "",
        "abv": merged.get("abv"),
        "ibu": merged.get("ibu"),
        "brewery": merged.get("brewery") or "",
        "description": description,
    }

def _card_score(card: dict[str, Any]) -> int:
    return sum(
        1
        for key in ("style", "category", "abv", "ibu", "brewery", "description")
        if card.get(key) not in (None, "")
    )

def _matching_card_index(found: list[dict[str, Any]], card: dict[str, Any]) -> int | None:
    name = card["name"].casefold()
    for index, prev in enumerate(found):
        if card["id"] and prev["id"] and card["id"] == prev["id"]:
            return index
        if prev["name"].casefold() == name:
            return index
    return None

def collect_beer_cards(blobs: list[Any], *, limit: int = 50) -> list[dict[str, Any]]:
    """Pull beer cards out of agent-turn hops / public_trace payloads."""
    found: list[dict[str, Any]] = []

    def walk(payload: Any, depth: int = 0) -> None:
        if depth > 8:
            return
        payload = _parse_blob(payload)
        if payload is None:
            return
        if isinstance(payload, list):
            for item in payload:
                walk(item, depth + 1)
            return
        if not isinstance(payload, dict):
            return
        card = _card_from_row(payload)
        if card is not None:
            score = _card_score(card)
            prev_at = _matching_card_index(found, card)
            if prev_at is None:
                found.append(card)
            elif score > _card_score(found[prev_at]):
                found[prev_at] = card
        for key, val in payload.items():
            if key in _CARD_SKIP_KEYS:
                continue
            if (
                key in _CARD_LIST_KEYS
                or isinstance(val, (dict, list))
                or (isinstance(val, str) and val.lstrip()[:1] in "{[")
            ):
                walk(val, depth + 1)

    for blob in blobs:
        walk(blob)
        if len(found) >= limit:
            break
    return found[: max(0, limit)]

def _pretty_label(value: Any) -> str:
    """Turn a doc-key token (``central_waters_brewing_company``) into words."""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if text and " " not in text and "_" in text:
        return text.replace("_", " ")
    return text

def _catalog_card(item: dict[str, Any]) -> dict[str, Any] | None:
    """Card from one Direct get/find item. Metadata and snippet fill the fields."""
    if not isinstance(item, dict):
        return None
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    snippet = _parse_blob(item.get("snippet"))
    extra = snippet if isinstance(snippet, dict) else {}

    def pick(*keys: str) -> Any:
        for source in (item, meta, extra):
            for key in keys:
                val = source.get(key)
                if val not in (None, ""):
                    return val
        return None

    name = pick("name", "title")
    if not isinstance(name, str) or not name.strip() or _is_hop_title(name):
        return None
    description = pick("description") or ""
    if not isinstance(description, str):
        description = ""
    brewery = pick("brewery") or _pretty_label(str(pick("brewery_id") or ""))
    return {
        "id": str(pick("id", "node_id") or ""),
        "name": name.strip(),
        "style": pick("style") or "",
        "category": pick("category") or "",
        "abv": pick("abv"),
        "ibu": pick("ibu"),
        "brewery": brewery or "",
        "description": description,
        "city": pick("city") or "",
        "state": pick("state") or "",
        "country": pick("country") or "",
    }

def list_total(raw: Any) -> int | None:
    """A missing total stays missing. JSON null is not zero."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return max(0, int(raw))

def list_range_label(*, count: int, total: int | None, offset: int = 0) -> str:
    """Page label. A missing total is ``1–N shown`` and never ``of 0``."""
    if count <= 0:
        return "0 shown"
    start = max(0, int(offset)) + 1
    end = max(0, int(offset)) + int(count)
    if total is None:
        return f"{start}–{end} shown"
    return f"{start}–{end} of {total}"

def row_identities(items: list[Any]) -> list[str]:
    found: list[str] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        ident = ""
        for key in ("id", "node_id", "doc_key"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                ident = value.strip()
                break
        if not ident:
            node = row.get("node")
            if isinstance(node, dict):
                for key in ("id", "doc_key"):
                    value = node.get(key)
                    if isinstance(value, str) and value.strip():
                        ident = value.strip()
                        break
        if ident and ident not in found:
            found.append(ident)
    return found

def offset_page_differs(page1_ids: list[str], page2_ids: list[str]) -> bool:
    """True only when a live page 2 has different ids from page 1."""
    if not page1_ids or not page2_ids:
        return False
    return list(page1_ids) != list(page2_ids)

def catalog_find_body(entity: str, limit: int, *, offset: int | None = None) -> dict[str, Any]:
    """Direct find for one catalog page. Offset is omitted unless the caller passes it."""
    body: dict[str, Any] = {
        "entity_type": entity,
        "return": "rows",
        "limit": max(1, int(limit)),
        "order_by": "id",
        "asc": True,
    }
    if offset is not None:
        body["offset"] = max(0, int(offset))
    return body

def _doc_key_only_payload(payload: Any, depth: int = 0) -> bool:
    if depth > 8:
        return False
    payload = _parse_blob(payload)
    if isinstance(payload, list):
        return any(_doc_key_only_payload(item, depth + 1) for item in payload)
    if not isinstance(payload, dict):
        return False
    node = payload.get("node") if isinstance(payload.get("node"), dict) else payload
    key = node.get("doc_key") if isinstance(node, dict) else None
    name = node.get("name") or node.get("title") if isinstance(node, dict) else None
    named = isinstance(name, str) and bool(name.strip()) and not _is_hop_title(name)
    if isinstance(key, str) and key.strip() and not named:
        return True
    for value in payload.values():
        if isinstance(value, (dict, list, str)) and _doc_key_only_payload(value, depth + 1):
            return True
    return False

def search_hit_state(blobs: list[Any], *, limit: int = 50) -> dict[str, Any]:
    """Cards from live fields. A doc_key-only hit is an empty state, not a title."""
    cards = collect_beer_cards(blobs, limit=limit)
    if cards:
        return {"items": cards, "empty_state": None, "empty_message": ""}
    if any(_doc_key_only_payload(blob) for blob in blobs):
        return {
            "items": [],
            "empty_state": "fts_doc_key_only",
            "empty_message": (
                "Search returned doc_key hits only. No named card on the live item."
            ),
        }
    return {"items": [], "empty_state": None, "empty_message": ""}


def collect_node_ids(blobs: list[Any]) -> list[str]:
    """n_* ids from a turn. A doc_key is not an id."""
    found: list[str] = []

    def walk(payload: Any, depth: int = 0) -> None:
        if depth > 8:
            return
        payload = _parse_blob(payload)
        if isinstance(payload, list):
            for item in payload:
                walk(item, depth + 1)
            return
        if not isinstance(payload, dict):
            return
        for key in ("id", "node_id"):
            value = payload.get(key)
            if isinstance(value, str) and value.startswith("n_") and value not in found:
                found.append(value)
        raw_ids = payload.get("node_ids")
        if isinstance(raw_ids, list):
            for value in raw_ids:
                if isinstance(value, str) and value.startswith("n_") and value not in found:
                    found.append(value)
        for key, value in payload.items():
            if key in _CARD_SKIP_KEYS:
                continue
            if isinstance(value, (dict, list, str)):
                walk(value, depth + 1)

    for blob in blobs:
        walk(blob)
    return found


async def _hydrate_node_ids(
    rt: ZeusRuntime, ids: list[str], cap: int
) -> tuple[list[dict[str, Any]], list[str]]:
    """Named cards from Direct get. Doc keys are not passed as ids."""
    chosen = [ident for ident in ids if ident.startswith("n_")][: max(0, cap)]
    if not chosen:
        return [], []
    try:
        got = await rt.data.get({"ids": chosen, "include": ["body"]})
    except ZeusClientError:
        return [], []
    if not getattr(got, "ok", False):
        return [], []
    by_id = {
        str(row.get("id")): row
        for row in (_verb_result(got).get("items") or [])
        if isinstance(row, dict) and row.get("id")
    }
    cards: list[dict[str, Any]] = []
    for ident in chosen:
        row = by_id.get(ident)
        card = _catalog_card(row) if isinstance(row, dict) else None
        if card is not None:
            cards.append(card)
    return cards, _verb_req_ids(got)


def _turn_blobs(result: Any) -> list[Any]:
    debug = getattr(result, "debug", None)
    blobs: list[Any] = []
    hops = getattr(debug, "hops", None) or ()
    if isinstance(hops, (list, tuple)):
        blobs.extend(hops)
    trace = getattr(debug, "public_trace", None)
    if trace:
        blobs.append(trace)
    return blobs


def _req_ids(result: Any) -> list[str]:
    debug = getattr(result, "debug", None)
    raw = getattr(debug, "req_ids", None) or ()
    ids = [str(item) for item in raw if item]
    if ids:
        return ids
    for hop in getattr(debug, "hops", None) or ():
        if isinstance(hop, dict) and hop.get("req_id"):
            ids.append(str(hop["req_id"]))
    return ids


def _hop_path(result: Any) -> list[str]:
    path = ["run_turn", "catalog.load_for_turn"]
    debug = getattr(result, "debug", None)
    for hop in getattr(debug, "hops", None) or ():
        if isinstance(hop, dict) and hop.get("name"):
            path.append(str(hop["name"]))
    return path


def _verb_result(result: Any) -> dict[str, Any]:
    body = result.body if isinstance(getattr(result, "body", None), dict) else {}
    inner = body.get("result") if isinstance(body.get("result"), dict) else {}
    return inner


def _verb_req_ids(result: Any) -> list[str]:
    found: list[str] = []
    for item in getattr(result, "req_ids", ()) or ():
        text = str(item or "").strip()
        if text and text not in found:
            found.append(text)
    one = str(getattr(result, "req_id", "") or "").strip()
    if one and one not in found:
        found.append(one)
    return found


def _exact_total(result: dict[str, Any]) -> int | None:
    '''Live count only. An approximate entity total is not a page count.'''
    if result.get("approximate") is True:
        return None
    return list_total(result.get("total_count"))


def _blank_list_page(entity: str, cap: int, offset: int) -> dict[str, Any]:
    '''Later page when find ignores offset. Do not repeat page 1 ids.'''
    noun = "breweries" if entity == "Brewery" else "beers"
    lede = "No " + noun + " on this page."
    return {
        "ok": True,
        "paged": True,
        "items": [],
        "cards": [],
        "limit": cap,
        "offset": offset,
        "total": None,
        "pages": None,
        "paging": False,
        "truncated": False,
        "range_label": "0 shown",
        "entity": entity,
        "lede": lede,
        "answer": lede,
        "path": ["find"],
        "req_ids": [],
    }


async def _run_list(entity: str, *, limit: int, offset: int) -> dict[str, Any]:
    '''One catalog page via Direct find, then get.

    The displayed find omits offset. A second find sends offset only to
    probe whether page 2 ids differ. Next stays hidden when they match.
    '''
    global _list_checked, _offset_honored
    cap = max(1, min(int(limit or 24), PAGE_CAP))
    requested = max(0, int(offset or 0))
    now = time.time()
    if _list_checked and not _offset_honored and requested > 0:
        return _blank_list_page(entity, cap, requested)
    if _list_checked:
        skip_guess = requested if _offset_honored else 0
        ttl = _list_cache_ttl()
        key = json.dumps({"list": entity, "limit": cap, "offset": skip_guess}, sort_keys=True)
        if ttl > 0:
            hit = _cache.get(key)
            if hit is not None and now - hit[0] <= ttl:
                return hit[1]
            if hit is not None:
                _cache.pop(key, None)

    rt = _runtime()
    try:
        counted = await rt.data.find({
            "entity_type": entity,
            "return": "count",
            "exact": True,
        })
        page1 = await rt.data.find(catalog_find_body(entity, cap))
    except ZeusClientError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": exc.public_message or str(exc)},
        ) from exc
    if not getattr(page1, "ok", False):
        raise HTTPException(
            status_code=502,
            detail={"error": getattr(page1, "error", None) or "find failed", "req_ids": _verb_req_ids(page1)},
        )
    probe = None
    try:
        probe = await rt.data.find(catalog_find_body(entity, cap, offset=cap))
    except ZeusClientError:
        probe = None
    page1_body = _verb_result(page1)
    page1_items = page1_body.get("items") if isinstance(page1_body.get("items"), list) else []
    probe_items: list[Any] = []
    if probe is not None and getattr(probe, "ok", False):
        probe_body = _verb_result(probe)
        if isinstance(probe_body.get("items"), list):
            probe_items = probe_body["items"]
    paging = offset_page_differs(row_identities(page1_items), row_identities(probe_items))
    if not paging and requested > 0:
        _list_checked = True
        _offset_honored = False
        return _blank_list_page(entity, cap, requested)
    skip = requested if paging else 0
    found = page1
    if paging and skip:
        try:
            found = await rt.data.find(catalog_find_body(entity, cap, offset=skip))
        except ZeusClientError as exc:
            raise HTTPException(
                status_code=502,
                detail={"error": exc.public_message or str(exc)},
            ) from exc
        if not getattr(found, "ok", False):
            raise HTTPException(
                status_code=502,
                detail={"error": getattr(found, "error", None) or "find failed", "req_ids": _verb_req_ids(found)},
            )

    found_body = _verb_result(found)
    total = _exact_total(_verb_result(counted)) if getattr(counted, "ok", False) else None
    raw_items = found_body.get("items") if isinstance(found_body.get("items"), list) else []
    ids: list[str] = []
    thin: list[dict[str, Any]] = []
    for row in raw_items:
        if not isinstance(row, dict):
            continue
        ident = str(row.get("id") or "")
        if ident.startswith("n_") and ident not in ids:
            ids.append(ident)
        card = _catalog_card(row)
        if card is not None:
            thin.append(card)

    items: list[dict[str, Any]] = []
    got_ok = False
    if ids:
        try:
            got = await rt.data.get({"ids": ids[:PAGE_CAP], "include": ["body"]})
        except ZeusClientError:
            got = None
        if got is not None and getattr(got, "ok", False):
            got_ok = True
            by_id = {
                str(row.get("id")): row
                for row in (_verb_result(got).get("items") or [])
                if isinstance(row, dict) and row.get("id")
            }
            for ident in ids:
                row = by_id.get(ident)
                card = _catalog_card(row) if isinstance(row, dict) else None
                if card is not None:
                    items.append(card)
    if not items:
        items = thin

    returned = len(items)
    if not paging or returned == 0:
        truncated = False
    elif total is not None:
        truncated = skip + returned < total
    else:
        truncated = returned >= cap
    pages = (max(1, (total + cap - 1) // cap) if total else (1 if returned == 0 else None))
    noun = "breweries" if entity == "Brewery" else "beers"
    label = list_range_label(count=returned, total=total, offset=skip)
    start = skip + 1
    end = skip + returned
    if returned and total is None:
        lede = f"Showing {noun} {start}–{end}."
    elif returned:
        lede = f"Showing {noun} {start}–{end} of {total}."
    else:
        lede = "No " + noun + " on this page."
    req_ids = _verb_req_ids(found)
    if got_ok:
        req_ids.extend(item for item in _verb_req_ids(got) if item not in req_ids)
    payload = {
        "ok": True,
        "paged": True,
        "items": items,
        "cards": items,
        "limit": cap,
        "offset": skip,
        "total": total,
        "pages": pages,
        "paging": paging,
        "truncated": truncated,
        "range_label": label,
        "entity": entity,
        "lede": lede,
        "answer": lede,
        "path": ["find", "get"] if got_ok else ["find"],
        "req_ids": req_ids,
    }
    first_check = not _list_checked
    _list_checked = True
    _offset_honored = paging
    if not first_check:
        store_ttl = _list_cache_ttl()
        store_key = json.dumps({"list": entity, "limit": cap, "offset": skip}, sort_keys=True)
        if store_ttl > 0:
            _cache[store_key] = (now, payload)
    return payload


def _hops_force_closed(result: Any) -> bool:
    '''True when a hop was refused for the shared session round cap.'''
    debug = getattr(result, "debug", None)
    for hop in getattr(debug, "hops", None) or ():
        if not isinstance(hop, dict):
            continue
        if _force_closed(str(hop.get("error") or "")):
            return True
        if _force_closed(str(hop.get("result_json") or "")):
            return True
    return False


def _pour_enabled() -> bool:
    '''True when this app process has an LLM key after load_dotenv.'''
    for name in ("LLM_API_KEY", "XAI_API_KEY", "OPENAI_API_KEY"):
        if (os.environ.get(name) or "").strip():
            return True
    return False


def _pour_reason() -> str:
    if _pour_enabled():
        return ""
    return "Pour is off until LLM_API_KEY, XAI_API_KEY, or OPENAI_API_KEY is set in .env."


async def _run_search(query: str, *, limit: int) -> dict[str, Any]:
    '''One catalog search via rt.agent.run_turn.

    chat_request is omitted on purpose. AgentAPI.run_turn then calls
    catalog.load_for_turn, which loads the analytics catalog and merges the
    live SCOPE BRIEF + MINI-SCHEMA into the system message sent to the model.
    '''
    if not _pour_enabled():
        reason = _pour_reason()
        return {
            "ok": False,
            "items": [],
            "cards": [],
            "pour_enabled": False,
            "lede": reason,
            "answer": reason,
            "path": [],
            "req_ids": [],
        }
    message = (query or "").strip()
    if not message:
        return {
            "ok": True,
            "items": [],
            "cards": [],
            "lede": "",
            "answer": "",
            "path": [],
            "req_ids": [],
        }
    cap = max(1, min(int(limit or PAGE_CAP), PAGE_CAP))
    ttl = _cache_ttl()
    key = json.dumps({"q": message, "limit": cap}, sort_keys=True)
    now = time.time()
    if ttl > 0:
        hit = _cache.get(key)
        if hit is not None and now - hit[0] <= ttl:
            return hit[1]
        if hit is not None:
            _cache.pop(key, None)

    rt = _runtime()
    cfg = rt.config
    chat_id = "beer_" + uuid.uuid4().hex[:12]
    # Omit chat_request so AgentAPI.run_turn calls catalog.load_for_turn
    # (SCOPE BRIEF + MINI-SCHEMA merge). Do not pass a frozen body or base_id.
    # Load first so a missing catalog is HTTP 502 on the current client, which
    # otherwise swallows CATALOG_NOT_FOUND and answers with empty req_ids.
    try:
        await rt.catalog.load_for_turn(cfg.settings.mode, target=cfg.target)
        result = await rt.agent.run_turn(
            message,
            target=cfg.target,
            settings=cfg.settings,
            chat_id=chat_id,
            model=cfg.llm.model,
            enable_sessions=bool(cfg.settings.durable_sessions),
        )
    except ZeusClientError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": exc.public_message or str(exc)},
        ) from exc

    answer = user_facing_answer(result.answer or "")
    err = result.error
    err_text = (getattr(err, "message", None) or "") if err is not None else ""
    if result.status == TurnStatus.ERROR:
        raise HTTPException(
            status_code=502,
            detail={
                "error": err_text or "agent turn failed",
                "req_ids": _req_ids(result),
            },
        )

    blobs = _turn_blobs(result)
    shaped = search_hit_state(blobs, limit=cap)
    items = list(shaped.get("items") or [])
    empty_state = shaped.get("empty_state")
    empty_message = shaped.get("empty_message") or ""
    path = _hop_path(result)
    req_ids = _req_ids(result)
    hydrated, get_ids = await _hydrate_node_ids(rt, collect_node_ids(blobs), cap)
    if hydrated:
        items = hydrated
        empty_state = None
        empty_message = ""
        if "get" not in path:
            path.append("get")
        for req_id in get_ids:
            if req_id not in req_ids:
                req_ids.append(req_id)
    if not items and (
        _force_closed(answer) or _force_closed(err_text) or _hops_force_closed(result)
    ):
        raise HTTPException(
            status_code=503,
            detail={"error": "session_force_closed", "req_ids": req_ids},
        )
    payload = {
        "ok": True,
        "items": items,
        "cards": items,
        "lede": answer,
        "answer": answer,
        "path": path,
        "req_ids": req_ids,
        "empty_state": empty_state,
        "empty_message": empty_message,
        "status": result.status.value if hasattr(result.status, "value") else str(result.status),
    }
    if ttl > 0:
        _cache[key] = (now, payload)
    return payload


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "sample": "beer"}


def _zeus_version(url: str) -> str:
    '''Public Zeus /version. Empty when the endpoint does not answer.'''
    if not url:
        return ""
    try:
        import httpx

        resp = httpx.get(url.rstrip("/") + "/version", timeout=2.0)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("version") or "").strip()


@app.get("/api/config")
async def api_config() -> dict[str, Any]:
    cfg = _runtime().config
    url = cfg.zeus.url or ""
    return {
        "zeus_url": url,
        "zeus_version": _zeus_version(url),
        "bucket": cfg.target.bucket,
        "scope": cfg.target.scope,
        "collection": cfg.target.collection,
        "mode": cfg.settings.mode,
        "llm_required": True,
        "pour_enabled": _pour_enabled(),
        "pour_reason": _pour_reason(),
        "page_cap": PAGE_CAP,
        "chips": [
            "Fruit Beer",
            "Pumpkin Beer",
            "Belgian and French Ale",
            "ipa",
            "porter",
            "Duvel",
        ],
    }


@app.get("/api/search")
async def api_search(
    q: str = Query("", max_length=500),
    limit: int = Query(PAGE_CAP, ge=1, le=PAGE_CAP),
    entity: str = Query(""),
) -> dict[str, Any]:
    '''Catalog search. Raw question goes to run_turn; the catalog supplies MINI-SCHEMA.'''
    message = (q or "").strip()
    kind = (entity or "").strip()
    if message and kind and kind.lower() not in {"beer", "beers"}:
        message = message + "\nEntity type: " + kind
    return await _run_search(message, limit=limit)


@app.get("/api/beers")
async def api_beers(
    limit: int = Query(24, ge=1, le=PAGE_CAP),
    offset: int = Query(0, ge=0, le=100000),
) -> dict[str, Any]:
    return await _run_list("Beer", limit=limit, offset=offset)


@app.get("/api/breweries")
async def api_breweries(
    limit: int = Query(24, ge=1, le=PAGE_CAP),
    offset: int = Query(0, ge=0, le=100000),
) -> dict[str, Any]:
    return await _run_list("Brewery", limit=limit, offset=offset)


@app.get("/api/beer/{item_id}")
async def api_beer(item_id: str) -> dict[str, Any]:
    out = await _run_search("Get the beer with id " + item_id, limit=1)
    if not out.get("items"):
        raise HTTPException(status_code=404, detail="not found")
    out["item"] = out["items"][0]
    return out


@app.get("/api/brewery/{item_id}")
async def api_brewery(item_id: str) -> dict[str, Any]:
    out = await _run_search("Get the brewery with id " + item_id, limit=1)
    if not out.get("items"):
        raise HTTPException(status_code=404, detail="not found")
    out["item"] = out["items"][0]
    return out


@app.get("/")
@app.get("/search")
async def index() -> FileResponse:
    index_path = _static / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=500, detail="static/index.html missing")
    return FileResponse(index_path)


def main() -> None:
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run("main:app", host=host, port=PORT, reload=False)


if __name__ == "__main__":
    main()
