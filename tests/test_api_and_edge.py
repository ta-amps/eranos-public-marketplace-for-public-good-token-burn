"""Tests for Eranos FastAPI endpoints, Surface Handshake v1.0, delta feed, edge Worker, and lockdown."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from tessera import QueueCounts

from eranos import __version__
from eranos.api import app as api_module
from eranos.api.app import app
from eranos.cli import main as cli_main

SECRET = "edge-secret-for-tests-only"  # check-public: allow
REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db = tmp_path / "eranos.db"
    monkeypatch.setenv("ERANOS_LOCAL_DB", str(db))
    monkeypatch.setenv("ERANOS_TRACE", str(tmp_path / "trace.jsonl"))
    monkeypatch.delenv("ERANOS_EDGE_SECRET", raising=False)
    monkeypatch.delenv("TESSERA_URL", raising=False)
    monkeypatch.delenv("TESSERA_TOKEN", raising=False)
    monkeypatch.delenv("TESSERA_KEY", raising=False)
    assert cli_main(["verify-examples"]) == 0
    return TestClient(app)


def test_api_serves_tracks_catalog_requests_and_fabric(client: TestClient) -> None:
    assert client.get("/api/health").json()["surface"] == "eranos"
    tracks = client.get("/api/tracks").json()
    assert len(tracks["tracks"]) == 6

    cat = client.get("/api/catalog").json()
    assert cat["two_step_verified"] is True
    assert len(cat["kits"]) == 5

    detail = client.get("/api/catalog/KIT-RECRUIT-01")
    assert detail.status_code == 200
    assert detail.json()["kit"]["kit_id"] == "KIT-RECRUIT-01"

    sop_detail = client.get("/api/catalog/KIT-SHIFT-05")
    assert sop_detail.status_code == 200
    assert sop_detail.json()["kit"]["deliverable_kind"] == "sop_playbook"

    reqs = client.get("/api/requests").json()
    assert len(reqs["stages"]) == 3
    assert len(reqs["requests"]) >= 4

    fab = client.get("/api/fabric").json()
    assert [(q["name"], q["label"]) for q in fab["queues"]] == [
        ("eq01", "Scope"),
        ("eq02", "Draft + verify"),
        ("eq03", "Independent review"),
    ]


def test_fabric_queues_have_deterministic_order_and_labels(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class OutOfOrderAdapter:
        def define_queue(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def counts(self) -> dict[str, QueueCounts]:
            return {
                "sq01": QueueCounts(ready=9, leased=0, waiting=0, done=1, dead=0, cancelled=0),
                "eq03": QueueCounts(ready=1, leased=2, waiting=3, done=4, dead=0, cancelled=0),
                "eq01": QueueCounts(ready=5, leased=0, waiting=0, done=6, dead=0, cancelled=0),
                "eq02": QueueCounts(ready=7, leased=1, waiting=0, done=8, dead=0, cancelled=0),
            }

        def close(self) -> None:
            return None

    monkeypatch.setattr(api_module, "get_adapter", lambda: OutOfOrderAdapter())
    resp = client.get("/api/fabric")
    assert resp.status_code == 200
    queues = resp.json()["queues"]
    assert [(q["name"], q["label"], q["ready"], q["done"]) for q in queues] == [
        ("eq01", "Scope", 5, 6),
        ("eq02", "Draft + verify", 7, 8),
        ("eq03", "Independent review", 1, 4),
    ]


def test_handshake_fallback_and_tessera_upstream(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    local_hs = client.get("/api/handshake")
    assert local_hs.status_code == 200
    assert local_hs.json() == {
        "synthetic": True,
        "surface_id": "eranos",
        "protocol_version": "1.0",
        "backend": "local",
        "isolated_store_prefix": "eranos.",
        "transactional_db_exempt_from_middleware": True,
    }

    captured: dict[str, Any] = {}

    def fake_post(
        url: str, *, json: Any, headers: dict[str, str], timeout: float
    ) -> httpx.Response:
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return httpx.Response(
            200,
            json={
                "protocol_version": "1.0",
                "surface_id": "eranos",
                "clamped_max_chars": 4000,
                "granted_queues": ["eq01", "eq02", "eq03"],
                "granted_stores": ["eranos.catalog", "eranos.index", "eranos.meta"],
            },
        )

    monkeypatch.setenv("TESSERA_URL", "https://tessera.ta-amps.workers.dev/")
    monkeypatch.setenv("TESSERA_TOKEN", "surf-key-01")
    monkeypatch.setattr(api_module.httpx, "post", fake_post)

    live_hs = client.get("/api/handshake")
    assert live_hs.status_code == 200
    assert captured["url"] == "https://tessera.ta-amps.workers.dev/v1/handshake"
    assert captured["headers"] == {
        "Authorization": "Bearer surf-key-01",
        "X-Surface-Id": "eranos",
    }
    assert captured["json"] == {
        "protocol_version": "1.0",
        "surface_id": "eranos",
        "surface_version": __version__,
        "requested_max_chars": 4000,
        "requested_queues": ["eq01", "eq02", "eq03"],
        "requested_stores": ["eranos.catalog", "eranos.index", "eranos.meta"],
    }
    body = live_hs.json()
    assert body["synthetic"] is True
    assert body["granted_queues"] == ["eq01", "eq02", "eq03"]

    def failing_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(api_module.httpx, "post", failing_post)
    degraded = client.get("/api/handshake")
    assert degraded.status_code == 200
    assert degraded.json()["degraded"] is True
    assert degraded.json()["isolated_store_prefix"] == "eranos."


def test_feed_fallback_and_tessera_upstream(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = client.get("/api/feed?after=7&limit=10")
    assert empty.status_code == 200
    assert empty.json() == {
        "synthetic": True,
        "feed": "noun.promotions",
        "entries": [],
        "next_cursor": 7,
    }

    captured: dict[str, Any] = {}

    def fake_get(url: str, *, headers: dict[str, str], timeout: float) -> httpx.Response:
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return httpx.Response(
            200,
            json={
                "feed": "noun.promotions",
                "entries": [{"seq": 8, "store": "eranos.catalog", "key": "KIT-RECRUIT-01"}],
                "next_cursor": 8,
            },
        )

    monkeypatch.setenv("TESSERA_URL", "https://tessera.ta-amps.workers.dev")
    monkeypatch.setenv("TESSERA_TOKEN", "surf-key-01")
    monkeypatch.setattr(api_module.httpx, "get", fake_get)

    live_feed = client.get("/api/feed?after=7&limit=5")
    assert live_feed.status_code == 200
    assert (
        captured["url"]
        == "https://tessera.ta-amps.workers.dev/v1/feeds/noun.promotions?after=7&limit=5"
    )
    assert captured["headers"] == {
        "X-Surface-Id": "eranos",
        "Authorization": "Bearer surf-key-01",
    }
    data = live_feed.json()
    assert data["synthetic"] is True
    assert data["next_cursor"] == 8
    assert len(data["entries"]) == 1


def test_cloudflare_worker_handshake_feed_and_fabric() -> None:
    wrangler_text = (REPO_ROOT / "deploy" / "cloudflare" / "wrangler.jsonc").read_text(
        encoding="utf-8"
    )
    assert '"binding": "TESSERA"' in wrangler_text
    assert '"binding": "HERMA"' in wrangler_text

    worker_path = (REPO_ROOT / "deploy" / "cloudflare" / "worker.js").as_posix()
    script = f"""
import worker from {json.dumps(worker_path)};

const calls = [];
const env = {{
  TESSERA_SURFACE_KEY: "t-key",
  HERMA_SURFACE_KEY: "h-key",
  TESSERA: {{
    async fetch(url, init = {{}}) {{
      calls.push({{ target: "tessera", url: String(url), init }});
      const u = new URL(String(url));
      if (u.pathname === "/v1/health") {{
        return Response.json({{
          queues: [
            {{ name: "sq01", counts: {{ ready: 9, leased: 0, waiting: 0, done: 0, dead: 0, cancelled: 0 }} }},
            {{ name: "eq03", counts: {{ ready: 1, leased: 0, waiting: 0, done: 5, dead: 0, cancelled: 0 }} }},
            {{ name: "eq01", counts: {{ ready: 2, leased: 0, waiting: 0, done: 5, dead: 0, cancelled: 0 }} }},
            {{ name: "eq02", counts: {{ ready: 4, leased: 1, waiting: 0, done: 5, dead: 0, cancelled: 0 }} }},
          ],
        }});
      }}
      if (u.pathname === "/v1/handshake") {{
        return Response.json({{ protocol_version: "1.0", surface_id: "eranos", clamped_max_chars: 4000 }});
      }}
      if (u.pathname === "/v1/feeds/noun.promotions") {{
        return Response.json({{
          feed: "noun.promotions",
          entries: [{{ seq: 5, key: "KIT-RECRUIT-01" }}],
          next_cursor: 5,
        }});
      }}
      return new Response("not found", {{ status: 404 }});
    }},
  }},
  HERMA: {{
    async fetch(url, init = {{}}) {{
      calls.push({{ target: "herma", url: String(url), init }});
      return Response.json({{ protocol_version: "1.0", router: "herma", status: "ready" }});
    }},
  }},
}};

const fab = await (await worker.fetch(new Request("https://eranos.ta-amps.workers.dev/api/fabric"), env)).json();
const hs = await (await worker.fetch(new Request("https://eranos.ta-amps.workers.dev/api/handshake"), env)).json();
const feed = await (await worker.fetch(new Request("https://eranos.ta-amps.workers.dev/api/feed?after=4&limit=12"), env)).json();
const fallbackHs = await (await worker.fetch(new Request("https://eranos.ta-amps.workers.dev/api/handshake"), {{}})).json();
const fallbackFeed = await (await worker.fetch(new Request("https://eranos.ta-amps.workers.dev/api/feed?after=9"), {{}})).json();

console.log(JSON.stringify({{ fab, hs, feed, fallbackHs, fallbackFeed, calls }}));
"""
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=True,
    )
    out = json.loads(res.stdout)
    assert [(q["name"], q["label"], q["ready"]) for q in out["fab"]["queues"]] == [
        ("eq01", "Scope", 2),
        ("eq02", "Draft + verify", 4),
        ("eq03", "Independent review", 1),
    ]
    assert out["hs"]["surface_id"] == "eranos"
    assert out["hs"]["clamped_max_chars"] == 4000
    assert out["hs"]["herma"]["router"] == "herma"
    assert out["feed"]["next_cursor"] == 5
    assert len(out["feed"]["entries"]) == 1
    assert out["fallbackHs"]["isolated_store_prefix"] == "eranos."
    assert out["fallbackFeed"] == {
        "synthetic": True,
        "feed": "noun.promotions",
        "entries": [],
        "next_cursor": 9,
    }
    hs_calls = [c for c in out["calls"] if c["url"].endswith("/v1/handshake")]
    assert len(hs_calls) == 2
    for call in hs_calls:
        assert call["init"]["headers"]["X-Surface-Id"] == "eranos"


def test_web_config_resolver_and_contribute_snippets() -> None:
    config_ts = (REPO_ROOT / "web" / "src" / "config.ts").read_text(encoding="utf-8")
    contribute_tsx = (REPO_ROOT / "web" / "src" / "pages" / "Contribute.tsx").read_text(
        encoding="utf-8"
    )
    assert "<domain>" not in config_ts
    assert "<domain>" not in contribute_tsx
    assert "/v1/queues/" not in contribute_tsx
    assert "${FABRIC_PUBLIC_URL}/mcp" in contribute_tsx
    assert "${FABRIC_PUBLIC_URL}/v1/tasks/claim" in contribute_tsx
    assert '"X-Surface-Id": "eranos"' in contribute_tsx
    assert "X-Surface-Id: eranos" in contribute_tsx


def test_invalid_kit_id_is_rejected_with_400(client: TestClient) -> None:
    for bad in ("../etc", "kit-lowercase-01", "DROP_TABLE"):
        resp = client.get(f"/api/catalog/{bad}")
        assert resp.status_code in {400, 404}
    assert client.get("/api/catalog/bad..id").status_code == 400


def test_edge_lockdown_blocks_direct_origin_requests(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ERANOS_EDGE_SECRET", SECRET)
    assert client.get("/api/health").status_code == 200
    denied = client.get("/api/catalog")
    assert denied.status_code == 403
    assert SECRET not in denied.text
    allowed = client.get("/api/catalog", headers={"x-edge-auth": SECRET})
    assert allowed.status_code == 200
