"""FastAPI app for Eranos. Serves verified nonprofit/NGO agent kits, dynamic catalog lenses, zero-storage
practice verification, public-good build tracks, open volunteer requests, live Tessera queue counts, and
AI-agent discovery endpoints (/favicon.svg, /healthz, /robots.txt, /llms.txt, /llms-full.txt,
/.well-known/agent-card.json, and stateless JSON-RPC 2.0 /mcp)."""

from __future__ import annotations

import hmac
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware

from eranos import __version__, config
from eranos.adapter import get_adapter
from eranos.api.public_feed import public_feed_payload
from eranos.pipeline import (
    SeedPackError,
    ensure_queues,
    filter_published_kits,
    get_published_kit,
    list_published_kits,
    load_example_bundles,
    practice_verify_kit,
)
from eranos.pipeline.examples import examples_payload, load_example_runs
from eranos.queues import QUEUE_LABELS, STAGES
from eranos.schemas import KIT_ID, OPEN_SPDX_ALLOWLIST, TaskBrief
from eranos.tracks import load_tracks

KIT_ID_RE = re.compile(KIT_ID)
EDGE_SECRET_ENV = "ERANOS_EDGE_SECRET"  # noqa: S105 - variable name, not a secret
EDGE_EXEMPT = frozenset(
    {
        ("GET", "/connect"),
        ("HEAD", "/connect"),
        ("GET", "/connect.json"),
        ("HEAD", "/connect.json"),
        ("GET", "/api/health"),
        ("HEAD", "/api/health"),
        ("GET", "/favicon.svg"),
        ("HEAD", "/favicon.svg"),
        ("GET", "/healthz"),
        ("HEAD", "/healthz"),
        ("GET", "/robots.txt"),
        ("HEAD", "/robots.txt"),
        ("GET", "/llms.txt"),
        ("HEAD", "/llms.txt"),
        ("GET", "/llms-full.txt"),
        ("HEAD", "/llms-full.txt"),
        ("GET", "/.well-known/agent-card.json"),
        ("HEAD", "/.well-known/agent-card.json"),
        ("POST", "/mcp"),
    }
)
REPO_ROOT = Path(__file__).resolve().parents[2]

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Eranos civic wreath token">
  <rect width="64" height="64" rx="14" fill="#155e49"/>
  <circle cx="32" cy="32" r="21" fill="none" stroke="#e3f2ed" stroke-width="2.5" stroke-dasharray="6 4"/>
  <path d="M20 38c0-9 5.5-16 12-18 6.5 2 12 9 12 18" fill="none" stroke="#6ee0be" stroke-width="3" stroke-linecap="round"/>
  <polygon points="32,23 39,32 32,41 25,32" fill="#ffffff"/>
</svg>
"""

ROBOTS_TXT = """User-agent: *
Allow: /
Allow: /api/catalog
Allow: /api/tracks
Allow: /llms.txt
Allow: /llms-full.txt
Allow: /.well-known/agent-card.json
"""

SUPPORTED_MCP_PROTOCOLS = frozenset({"2024-11-05", "2025-03-26", "2025-06-18"})

MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_tracks",
        "description": "List all public-good NGO and nonprofit build tracks and required human_only boundaries.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "search_catalog",
        "description": "Search and filter two-step verified NGO kits by domain, track, tag, cohort, open SPDX license, or free-text query.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "track": {"type": "string"},
                "tag": {"type": "string"},
                "cohort": {"type": "string"},
                "spdx": {"type": "string"},
                "q": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_kit",
        "description": "Fetch a single verified PublishedKit bundle including skills, read-only MCP tool schemas, checklists, fixtures, and receipts.",
        "inputSchema": {
            "type": "object",
            "required": ["kit_id"],
            "properties": {
                "kit_id": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "practice_verify_kit",
        "description": "Zero-storage deterministic verifier (persisted: false) for boundaries, copy, SPDX and SYNTHETIC fixtures. Receipt scope is validation_outcome; it does not bind draft content or publish a kit.",
        "inputSchema": {
            "type": "object",
            "required": ["draft"],
            "properties": {
                "draft": {"type": "object"},
                "track_id": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "annotations": {"readOnlyHint": True},
    },
]

app = FastAPI(title="Eranos", version=__version__)


@app.middleware("http")
async def edge_lockdown(request: Request, call_next: RequestResponseEndpoint) -> Response:
    secret = os.environ.get(EDGE_SECRET_ENV)
    if secret and (request.method, request.url.path) not in EDGE_EXEMPT:
        supplied = request.headers.get("x-edge-auth", "")
        if not hmac.compare_digest(supplied.encode(), secret.encode()):
            return JSONResponse(
                status_code=403,
                media_type="application/problem+json",
                content={
                    "type": "about:blank",
                    "title": "Forbidden",
                    "status": 403,
                    "detail": "Requests reach the Eranos API only through its edge.",
                    "code": "forbidden",
                },
            )
    resp = await call_next(request)
    if "cache-control" not in resp.headers:
        resp.headers["cache-control"] = "no-store"
    return resp


@app.get("/favicon.svg")
def favicon() -> Response:
    return Response(content=FAVICON_SVG, media_type="image/svg+xml")


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "ok": True,
        "status": "ok",
        "synthetic": True,
        "surface": "eranos",
        "version": __version__,
        "backend": config.backend_name(),
    }


@app.get("/robots.txt")
def robots_txt() -> Response:
    return Response(content=ROBOTS_TXT, media_type="text/plain; charset=utf-8")


@app.get("/llms.txt")
def llms_txt() -> Response:
    path = REPO_ROOT / "llms.txt"
    text = (
        path.read_text(encoding="utf-8")
        if path.is_file()
        else "# Eranos\n\n> Public-good NGO volunteer agent tooling foundry.\n"
    )
    return Response(content=text, media_type="text/plain; charset=utf-8")


@app.get("/llms-full.txt")
def llms_full_txt() -> Response:
    path = REPO_ROOT / "llms-full.txt"
    text = (
        path.read_text(encoding="utf-8")
        if path.is_file()
        else "# Eranos: full text\n\n> Public-good NGO volunteer agent tooling foundry.\n"
    )
    return Response(content=text, media_type="text/plain; charset=utf-8")


@app.get("/.well-known/agent-card.json")
def agent_card(request: Request) -> dict[str, Any]:
    origin = (
        f"{request.url.scheme}://{request.url.netloc}"
        if request.url.netloc
        else config.surface_public_url()
    )
    return {
        "schema_version": "1.0",
        "name": config.surface_display_name(),
        "surface_id": "surface:eranos",
        "description": (
            "Public-good NGO tooling foundry where contributors donate unused AI tokens to build, "
            "deterministically verify, and independently review (drafter != reviewer) off-the-shelf "
            "agent skills, read-only MCP tools, SOPs, and workflows."
        ),
        "version": __version__,
        "url": origin,
        "synthetic_only": True,
        "spdx_allowlist": sorted(OPEN_SPDX_ALLOWLIST),
        "headers": {"surface": "X-Surface-Id"},
        "endpoints": {
            "mcp": "/mcp",
            "catalog": "/api/catalog",
            "tracks": "/api/tracks",
            "practice": "/api/practice",
            "handshake": "/api/handshake",
            "feed": "/api/feed",
            "health": "/healthz",
            "llms": "/llms.txt",
            "llms_full": "/llms-full.txt",
        },
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "statelessMcp": True,
            "zeroStoragePracticeGate": True,
        },
        "skills": [
            {"id": tool["name"], "name": tool["name"], "description": tool["description"]}
            for tool in MCP_TOOLS
        ],
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "synthetic": True,
        "surface": "eranos",
        "version": __version__,
        "backend": config.backend_name(),
    }


@app.get("/api/handshake")
def handshake() -> dict[str, Any]:
    fallback: dict[str, Any] = {
        "synthetic": True,
        "surface_id": "eranos",
        "protocol_version": "1.0",
        "backend": config.backend_name(),
        "isolated_store_prefix": "eranos.",
        "transactional_db_exempt_from_middleware": True,
    }
    tessera_url = os.environ.get("TESSERA_URL", "").strip().rstrip("/")
    tessera_token = os.environ.get("TESSERA_TOKEN", "").strip()
    if not (tessera_url and tessera_token):
        return fallback
    payload: dict[str, Any] = {
        "protocol_version": "1.0",
        "surface_id": "eranos",
        "surface_version": __version__,
        "requested_max_chars": 4000,
        "requested_queues": ["eq01", "eq02", "eq03"],
        "requested_stores": ["eranos.catalog", "eranos.index", "eranos.meta"],
    }
    headers = {
        "Authorization": f"Bearer {tessera_token}",
        "X-Surface-Id": "eranos",
    }
    try:
        resp = httpx.post(
            f"{tessera_url}/v1/handshake",
            json=payload,
            headers=headers,
            timeout=5.0,
        )
        if resp.is_success:
            upstream = resp.json()
            if isinstance(upstream, dict):
                return {"synthetic": True, **upstream}
    except httpx.HTTPError:
        pass
    return {**fallback, "degraded": True}


@app.get("/api/tracks")
def tracks() -> dict[str, Any]:
    packs = load_tracks()
    return {
        "synthetic": True,
        "tracks": [pack.model_dump(mode="json") for pack in packs.values()],
    }


@app.get("/api/catalog")
def catalog(
    domain: str | None = Query(default=None),
    track: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    cohort: str | None = Query(default=None),
    spdx: str | None = Query(default=None),
    q: str | None = Query(default=None),
) -> dict[str, Any]:
    backend = get_adapter()
    try:
        kits = list_published_kits(backend)
    finally:
        backend.close()
    filtered = filter_published_kits(
        kits,
        domain=domain,
        track=track,
        tag=tag,
        cohort=cohort,
        spdx=spdx,
        q=q,
    )
    return {
        "synthetic": True,
        "two_step_verified": True,
        "kits": [kit.model_dump(mode="json") for kit in filtered],
    }


@app.get("/api/catalog/{kit_id}")
def catalog_item(kit_id: str, cohort: str | None = Query(default=None)) -> dict[str, Any]:
    if not KIT_ID_RE.match(kit_id):
        raise HTTPException(status_code=400, detail="invalid kit id")
    backend = get_adapter()
    try:
        found = get_published_kit(backend, kit_id, public=True, cohort=cohort)
    finally:
        backend.close()
    if found is None:
        raise HTTPException(status_code=404, detail=f"kit {kit_id} is not in the catalog")
    return {"synthetic": True, **found.model_dump(mode="json")}


@app.post("/api/practice")
async def practice_endpoint(
    request: Request,
    track_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON payload: {exc}") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="practice payload must be a JSON object")
    explicit_track = track_id or (
        str(body["track_id"]).strip()
        if "draft" in body and isinstance(body.get("track_id"), str) and body["track_id"].strip()
        else None
    )
    return practice_verify_kit(body, track_id=explicit_track)


@app.get("/api/examples")
def examples() -> dict[str, Any]:
    """Example needs in organizations' own words and the recorded example runs, read from nouns."""
    try:
        bundles = load_example_bundles()
    except SeedPackError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return examples_payload(bundles, load_example_runs())


@app.get("/api/requests")
def open_requests() -> dict[str, Any]:
    briefs_dir = REPO_ROOT / "briefs"
    rows: list[dict[str, Any]] = []
    for path in sorted(briefs_dir.glob("*.json")):
        brief = TaskBrief.model_validate(json.loads(path.read_text(encoding="utf-8")))
        rows.append(brief.model_dump(mode="json"))
    return {
        "synthetic": True,
        "stages": [
            {
                "queue": s.queue,
                "node": s.node,
                "title": s.title,
                "effect_class": s.effect_class,
                "purpose": s.purpose,
            }
            for s in STAGES
        ],
        "requests": rows,
    }


@app.get("/api/fabric")
def fabric() -> dict[str, Any]:
    backend = get_adapter()
    try:
        ensure_queues(backend)
        counts = backend.counts()
    finally:
        backend.close()
    return {
        "display_name": config.fabric_display_name(),
        "plan": config.backend_name(),
        "synthetic": True,
        "queues": [
            {"name": name, "label": label, **counts[name].model_dump()}
            for name, label in QUEUE_LABELS
            if name in counts
        ],
    }


@app.get("/api/feed")
def feed(
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
) -> dict[str, Any]:
    fallback: dict[str, Any] = {
        "synthetic": True,
        "feed": "noun.promotions",
        "entries": [],
        "next_cursor": after,
    }
    tessera_url = os.environ.get("TESSERA_URL", "").strip().rstrip("/")
    if not tessera_url:
        backend = get_adapter()
        try:
            if hasattr(backend, "poll_feed"):
                local_entries = backend.poll_feed("noun.promotions", after=after, limit=limit)
                dumped = [
                    e.model_dump(mode="json") if hasattr(e, "model_dump") else dict(e)
                    for e in local_entries
                ]
                next_cur = int(dumped[-1]["seq"]) if dumped else after
                return public_feed_payload(
                    {"feed": "noun.promotions", "entries": dumped, "next_cursor": next_cur},
                    after=after,
                )
        except Exception:
            return fallback
        finally:
            backend.close()
        return fallback
    tessera_token = (os.environ.get("TESSERA_TOKEN") or os.environ.get("TESSERA_KEY") or "").strip()
    headers: dict[str, str] = {"X-Surface-Id": "eranos"}
    if tessera_token:
        headers["Authorization"] = f"Bearer {tessera_token}"
    try:
        resp = httpx.get(
            f"{tessera_url}/v1/feeds/noun.promotions?after={after}&limit={limit}",
            headers=headers,
            timeout=5.0,
        )
        if resp.is_success:
            upstream = resp.json()
            if isinstance(upstream, dict):
                return public_feed_payload(upstream, after=after)
    except httpx.HTTPError:
        pass
    return {**fallback, "degraded": True}


def _jsonrpc_error(req_id: Any, code: int, message: str, status: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        },
    )


def _execute_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if tool_name == "list_tracks":
        data = tracks()
        return data, False
    if tool_name == "search_catalog":
        data = catalog(
            domain=arguments.get("domain"),
            track=arguments.get("track"),
            tag=arguments.get("tag"),
            cohort=arguments.get("cohort"),
            spdx=arguments.get("spdx"),
            q=arguments.get("q"),
        )
        return data, False
    if tool_name == "get_kit":
        kit_id = str(arguments.get("kit_id") or "").strip()
        if not KIT_ID_RE.match(kit_id):
            return {"error": "invalid kit id", "kit_id": kit_id}, True
        backend = get_adapter()
        try:
            found = get_published_kit(backend, kit_id, public=True, cohort=arguments.get("cohort"))
        finally:
            backend.close()
        if found is None:
            return {"error": f"kit {kit_id} is not in the catalog", "kit_id": kit_id}, True
        return {"synthetic": True, **found.model_dump(mode="json")}, False
    if tool_name == "practice_verify_kit":
        raw_draft = arguments.get("draft")
        draft_in: dict[str, Any] = raw_draft if isinstance(raw_draft, dict) else arguments
        raw_track = arguments.get("track_id")
        explicit_track = (
            raw_track.strip() if isinstance(raw_track, str) and raw_track.strip() else None
        )
        res = practice_verify_kit(draft_in, track_id=explicit_track)
        return res, False
    raise KeyError(tool_name)


@app.post("/mcp")
async def mcp_jsonrpc(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return _jsonrpc_error(None, -32700, "Parse error", status=400)

    if (
        not isinstance(body, dict)
        or body.get("jsonrpc") != "2.0"
        or not isinstance(body.get("method"), str)
    ):
        req_id = body.get("id") if isinstance(body, dict) else None
        return _jsonrpc_error(req_id, -32600, "Invalid Request", status=400)

    method = str(body["method"])
    has_id = "id" in body and body["id"] is not None
    req_id = body.get("id")
    raw_params = body.get("params")
    params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}

    if method == "initialize":
        requested_proto = str(params.get("protocolVersion") or "2024-11-05")
        proto = requested_proto if requested_proto in SUPPORTED_MCP_PROTOCOLS else "2024-11-05"
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": proto,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "eranos", "version": __version__},
                    "instructions": (
                        "Eranos public-good NGO catalog and zero-storage practice verifier "
                        "(persisted: false). Every fixture is SYNTHETIC; human_only boundaries "
                        "stay strictly with trained staff."
                    ),
                },
            }
        )

    if method == "notifications/initialized" or method.startswith("notifications/"):
        if not has_id:
            return JSONResponse(status_code=202, content={"jsonrpc": "2.0", "result": {}})
        return JSONResponse(content={"jsonrpc": "2.0", "id": req_id, "result": {}})

    if method == "ping":
        return JSONResponse(content={"jsonrpc": "2.0", "id": req_id, "result": {}})

    if method == "tools/list":
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": MCP_TOOLS},
            }
        )

    if method == "tools/call":
        tool_name = str(params.get("name") or "")
        raw_args = params.get("arguments")
        arguments: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
        if tool_name not in {t["name"] for t in MCP_TOOLS}:
            return _jsonrpc_error(req_id, -32602, f"Unknown tool: {tool_name}")
        payload, is_err = _execute_mcp_tool(tool_name, arguments)
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(payload)}],
                    "structuredContent": payload,
                    "isError": is_err,
                },
            }
        )

    return _jsonrpc_error(req_id, -32601, f"Method not found: {method}")


@app.get("/connect.json")
def connect_info() -> dict[str, Any]:
    return {
        "surface": "eranos",
        "fabric_connect_url": "https://tessera.ta-amps.workers.dev/connect",
        "surface_persistence": False,
        "authentication": "Public reads and practice are open. Tracked noun/verb work uses a Tessera anonymous session or API key.",
        "practice_persisted": False,
    }


@app.get("/connect", response_class=HTMLResponse)
def connect_page() -> str:
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Connect</title><h1>Connect to eranos</h1><p>Public tools require no key. Use Tessera for tracked work.</p><p><a href="https://tessera.ta-amps.workers.dev/connect">Get an anonymous demo session</a></p><p><a href="https://tessera.ta-amps.workers.dev/connect">Create or use an API key</a></p><a href="/connect.json">Machine-readable access modes</a></html>'


# CORS is outermost so preflight needs no origin authentication; actual requests retain it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "HEAD", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "If-Match", "X-Request-Id", "X-Agent-Label"],
    expose_headers=["ETag", "Retry-After", "X-Request-Id"],
)
