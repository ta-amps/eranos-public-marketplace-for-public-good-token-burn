"""FastAPI app for Eranos. Serves verified nonprofit/NGO agent kits, public-good build tracks, open
volunteer requests, and live Tessera queue counts. Locked to the Cloudflare edge when ERANOS_EDGE_SECRET
is set; every kit_id is strictly pattern-checked."""

from __future__ import annotations

import hmac
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint

from eranos import __version__, config
from eranos.adapter import get_adapter
from eranos.pipeline import ensure_queues, get_published_kit, list_published_kits
from eranos.queues import QUEUE_LABELS, STAGES
from eranos.schemas import KIT_ID, TaskBrief
from eranos.tracks import load_tracks

KIT_ID_RE = re.compile(KIT_ID)
EDGE_SECRET_ENV = "ERANOS_EDGE_SECRET"  # noqa: S105 - variable name, not a secret
EDGE_EXEMPT = frozenset({("GET", "/api/health")})
REPO_ROOT = Path(__file__).resolve().parents[2]

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
    return await call_next(request)


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
def catalog() -> dict[str, Any]:
    backend = get_adapter()
    try:
        kits = list_published_kits(backend)
    finally:
        backend.close()
    return {
        "synthetic": True,
        "two_step_verified": True,
        "kits": [kit.model_dump(mode="json") for kit in kits],
    }


@app.get("/api/catalog/{kit_id}")
def catalog_item(kit_id: str) -> dict[str, Any]:
    if not KIT_ID_RE.match(kit_id):
        raise HTTPException(status_code=400, detail="invalid kit id")
    backend = get_adapter()
    try:
        found = get_published_kit(backend, kit_id)
    finally:
        backend.close()
    if found is None:
        raise HTTPException(status_code=404, detail=f"kit {kit_id} is not in the catalog")
    return {"synthetic": True, **found.model_dump(mode="json")}


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
                return {"synthetic": True, **upstream}
    except httpx.HTTPError:
        pass
    return {**fallback, "degraded": True}
