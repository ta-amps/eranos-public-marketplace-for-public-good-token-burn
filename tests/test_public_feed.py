"""Public clients never inherit the service reader's feed authority."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from tessera import Store

from eranos.api import app as api_module
from eranos.api.public_feed import public_feed_payload
from eranos.visible import visible

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def service_payload(tmp_path: Path) -> dict[str, Any]:
    store = Store(str(tmp_path / "fabric.db"))
    try:
        with store.scope_context(
            surface="surface:eranos", key_id="synthetic-service", is_admin=False
        ):
            for visibility in ("surface_only", "allowlist_surfaces", "private", "public_commons"):
                store.publish_feed(
                    "noun.promotions",
                    {"marker": "SYNTHETIC " + visibility},
                    kind="promotion",
                    summary="SYNTHETIC fixture",
                    visibility_scope=visibility,
                    allowed_surfaces=["surface:home"],
                    tags=["status:verified"],
                )
            entries = [
                entry.model_dump(mode="json") for entry in store.poll_feed("noun.promotions")
            ]
        with store.scope_context(surface="", is_admin=False):
            public = store.poll_feed("noun.promotions")
        assert len(entries) == 4 and len(public) == 1
        return {"feed": "noun.promotions", "entries": entries, "next_cursor": 4}
    finally:
        store.close()


def test_public_python_route_projects_actual_service_read(
    service_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TESSERA_URL", "https://fabric.example.com")
    monkeypatch.setenv("TESSERA_TOKEN", "synthetic-service-marker")
    monkeypatch.delenv("ERANOS_EDGE_SECRET", raising=False)
    monkeypatch.setattr(
        api_module.httpx, "get", lambda *args, **kwargs: httpx.Response(200, json=service_payload)
    )
    response = TestClient(api_module.app).get(
        "/api/feed", headers={"Origin": "https://assistant.example.com"}
    )
    assert response.status_code == 200
    result = response.json()
    assert result == public_feed_payload(service_payload, after=0)
    assert [e["payload"]["marker"] for e in result["entries"]] == ["SYNTHETIC public_commons"]
    assert result["next_cursor"] == 4
    assert "owner_key_id" not in result["entries"][0]
    assert "synthetic-service" not in response.text


def test_public_worker_route_projects_actual_service_read(service_payload: dict[str, Any]) -> None:
    script = """
import worker from WORKER;
const payload = PAYLOAD;
const calls = [];
const env = {STORAGE_MODE:"cloud", TESSERA_SURFACE_KEY:"synthetic-binding-marker", TESSERA:{
 async fetch(url, init) {
  calls.push({surface:new Headers(init.headers).get("x-surface-id"), keyed:new Headers(init.headers).has("authorization")});
  return Response.json(payload);
 }
}};
const request = new Request("https://surface.example/api/feed",{headers:{Origin:"https://assistant.example.com"}});
const response = await worker.fetch(request,env);
console.log(JSON.stringify({status:response.status,body:await response.json(),calls,callerKeyed:request.headers.has("authorization")}));
""".replace("WORKER", json.dumps((ROOT / "deploy/cloudflare/worker.js").as_uri())).replace(
        "PAYLOAD", json.dumps(service_payload)
    )
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script], check=True, capture_output=True, text=True
    )
    result = json.loads(run.stdout)
    assert result["status"] == 200 and result["callerKeyed"] is False
    assert result["calls"] == [{"surface": "eranos", "keyed": True}]
    # The Worker answers in visitors' words (eranos/visible.py and visibleWords in the Worker).
    assert result["body"] == visible(public_feed_payload(service_payload, after=0))
    assert [e["payload"]["marker"] for e in result["body"]["entries"]] == [
        "practice-case public_commons"
    ]


def test_projection_denies_incomplete_restricted_or_unverified_rows_and_preserves_cursor(
    service_payload: dict[str, Any],
) -> None:
    public = service_payload["entries"][-1]
    variants = [
        {"namespace": "sandbox"},
        {"tags": []},
        {"tags": ["status:verified", " STATUS:QUARANTINED "]},
        {"tags": "status:verified"},
        {"target_cohorts": ["cohort:restricted"]},
        {"target_cohorts": "all"},
        {"allowed_surfaces": None},
        {"producer_surface": ""},
        {"visibility_scope": "private", "payload": {"visibility_scope": "public_commons"}},
    ]
    rows = [{**public, **delta, "seq": i + 1} for i, delta in enumerate(variants)]
    payload = {
        "feed": "noun.promotions",
        "entries": rows,
        "next_cursor": len(rows),
        "owner_key_id": "synthetic-private",
    }
    projected = public_feed_payload(payload, after=0)
    assert projected["entries"] == [] and projected["next_cursor"] == len(rows)
    assert "owner_key_id" not in projected
    assert public_feed_payload(service_payload, after=4)["entries"] == []
    script = """
import {publicFeedPayload} from ACCESS;
const payloads = PAYLOADS;
console.log(JSON.stringify(payloads.map(p=>publicFeedPayload(p,0))));
""".replace("ACCESS", json.dumps((ROOT / "deploy/cloudflare/access.js").as_uri())).replace(
        "PAYLOADS", json.dumps([payload, {}, {"feed": "noun.promotions", "entries": None}])
    )
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script], check=True, capture_output=True, text=True
    )
    worker_results = json.loads(run.stdout)
    assert worker_results[0] == projected
    assert all(item["entries"] == [] and item["degraded"] for item in worker_results[1:])
