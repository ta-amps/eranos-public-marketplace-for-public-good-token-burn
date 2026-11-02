"""Tests for Eranos FastAPI endpoints, catalog filters, practice gate, MCP/discovery, edge Worker, and lockdown."""

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
from eranos.adapter import get_adapter
from eranos.api import app as api_module
from eranos.api.app import app
from eranos.cli import main as cli_main
from eranos.pipeline import (
    load_example_bundles,
    run_draft_step,
    run_review_step,
    run_spec_step,
    submit_kit_request,
)
from eranos.schemas import KitRequest, ReviewDecision
from eranos.tracks import get_track, load_tracks
from eranos.visible import visible

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
    assert len(tracks["tracks"]) == len(load_tracks())

    cat = client.get("/api/catalog").json()
    assert cat["two_step_verified"] is True
    assert len(cat["kits"]) == len(load_example_bundles())

    detail = client.get("/api/catalog/KIT-RECRUIT-01")
    assert detail.status_code == 200
    assert detail.json()["kit"]["kit_id"] == "KIT-RECRUIT-01"

    sop_detail = client.get("/api/catalog/KIT-SHIFT-05")
    assert sop_detail.status_code == 200
    assert sop_detail.json()["kit"]["deliverable_kind"] == "sop_playbook"

    examples = client.get("/api/examples").json()
    assert examples["synthetic"] is True
    assert len(examples["needs"]) == sum("seed_pack" in b for b in load_example_bundles())
    assert examples["runs"]["count"] == len(load_example_bundles())

    reqs = client.get("/api/requests").json()
    assert len(reqs["stages"]) == 3
    assert len(reqs["requests"]) >= 4

    fab = client.get("/api/fabric").json()
    assert [(q["name"], q["label"]) for q in fab["queues"]] == [
        ("eq01", "Scope"),
        ("eq02", "Draft + verify"),
        ("eq03", "Independent review"),
    ]


def test_catalog_filtering_cohorts_spdx_tags_and_quarantine(client: TestClient) -> None:
    # Combinable domain, track, tag, spdx, and free-text query filters
    nonprofit = client.get("/api/catalog?domain=nonprofit_ops").json()["kits"]
    expected = {
        b["request"]["kit_id"]
        for b in load_example_bundles()
        if get_track(b["request"]["track_id"]).domain == "nonprofit_ops"
    }
    assert {"KIT-INTAKE-03", "KIT-GRANT-04", "KIT-SHIFT-05"} <= expected
    assert {k["kit"]["kit_id"] for k in nonprofit} == expected

    hotline = client.get("/api/catalog?track=coerced-work-hotline-routing").json()["kits"]
    assert [k["kit"]["kit_id"] for k in hotline] == ["KIT-HOTLINE-02"]

    cc_by = client.get("/api/catalog?spdx=CC-BY-4.0").json()["kits"]
    assert [k["kit"]["kit_id"] for k in cc_by] == ["KIT-HOTLINE-02"]

    combo = client.get(
        "/api/catalog?domain=nonprofit_ops&spdx=CC0-1.0&tag=kind:sop_playbook"
    ).json()["kits"]
    assert [k["kit"]["kit_id"] for k in combo] == ["KIT-SHIFT-05"]

    searched = client.get("/api/catalog?q=ledger").json()["kits"]
    assert [k["kit"]["kit_id"] for k in searched] == ["KIT-GRANT-04"]

    empty = client.get("/api/catalog?domain=nonprofit_ops&spdx=CC-BY-4.0").json()["kits"]
    assert empty == []

    # Publish a verified cohort-restricted kit (target_cohorts WITHOUT "all")
    bundle = load_example_bundles()[0]
    restricted_req = KitRequest.model_validate(
        {
            **bundle["request"],
            "kit_id": "KIT-COHORT-88",
            "target_cohorts": ["ngo_closed_pilot"],
            "visibility_scope": "public_commons",
        }
    )
    restricted_draft = {
        **bundle["draft"],
        "kit_id": "KIT-COHORT-88",
        "target_cohorts": ["ngo_closed_pilot"],
        "visibility_scope": "public_commons",
    }
    backend = get_adapter()
    try:
        submit_kit_request(backend, restricted_req, run_id="run-cohort-88")
        run_spec_step(backend, worker="spec-cohort")
        run_draft_step(backend, restricted_draft, worker="drafter-c1", key_id="key_c1")
        run_review_step(
            backend,
            ReviewDecision(
                kit_id="KIT-COHORT-88",
                verdict="approved",
                reviewed_by="reviewer-c2",
                reviewed_by_key="key_c2",
                notes="Verified restricted cohort kit.",
            ),
            worker="reviewer-c2",
            key_id="key_c2",
        )
    finally:
        backend.close()

    # Omitted ?cohort= MUST return ONLY universal ("all") kits
    default_ids = {k["kit"]["kit_id"] for k in client.get("/api/catalog").json()["kits"]}
    universal = len(load_example_bundles())
    assert "KIT-COHORT-88" not in default_ids
    assert len(default_ids) == universal

    # Explicit ?cohort=ngo_closed_pilot returns universal ("all") OR "ngo_closed_pilot"
    pilot_ids = {
        k["kit"]["kit_id"]
        for k in client.get("/api/catalog?cohort=ngo_closed_pilot").json()["kits"]
    }
    assert "KIT-COHORT-88" in pilot_ids
    assert len(pilot_ids) == universal + 1

    # Unrelated cohort returns only universal ("all") kits
    other_ids = {
        k["kit"]["kit_id"] for k in client.get("/api/catalog?cohort=other_coalition").json()["kits"]
    }
    assert "KIT-COHORT-88" not in other_ids
    assert len(other_ids) == universal


def test_practice_api_zero_storage_gate(client: TestClient) -> None:
    bundle = load_example_bundles()[0]
    ok_resp = client.post("/api/practice", json={"draft": bundle["draft"]})
    assert ok_resp.status_code == 200
    ok_data = ok_resp.json()
    assert ok_data["passed"] is True
    assert ok_data["persisted"] is False
    assert len(ok_data["receipt_sha256"]) == 64

    bad_draft = {
        **bundle["draft"],
        "kit_id": "KIT-DRYRUN-99",
        "spdx_license": "Proprietary-Closed",
        "summary": "Accuse the scammer directly.",
    }
    bad_resp = client.post("/api/practice", json={"draft": bad_draft})
    assert bad_resp.status_code == 200
    bad_data = bad_resp.json()
    assert bad_data["passed"] is False
    assert bad_data["persisted"] is False
    assert len(bad_data["issues"]) >= 1

    # Catalog must remain completely untouched
    assert client.get("/api/catalog/KIT-DRYRUN-99").status_code == 404
    assert len(client.get("/api/catalog").json()["kits"]) == len(load_example_bundles())


def test_agent_discovery_and_stateless_mcp_even_under_edge_lockdown(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ERANOS_EDGE_SECRET", SECRET)

    fav = client.get("/favicon.svg")
    assert fav.status_code == 200
    assert "image/svg+xml" in fav.headers["content-type"]
    assert "<svg" in fav.text

    hz = client.get("/healthz")
    assert hz.status_code == 200
    assert "application/json" in hz.headers["content-type"]
    assert hz.json()["ok"] is True

    rob = client.get("/robots.txt")
    assert rob.status_code == 200
    assert "text/plain" in rob.headers["content-type"]
    assert "User-agent: *" in rob.text

    llms = client.get("/llms.txt")
    assert llms.status_code == 200
    assert "text/plain" in llms.headers["content-type"]
    assert "Eranos" in llms.text

    llms_full = client.get("/llms-full.txt")
    assert llms_full.status_code == 200
    assert "text/plain" in llms_full.headers["content-type"]
    assert len(llms_full.text) > 500

    card = client.get("/.well-known/agent-card.json")
    assert card.status_code == 200
    assert "application/json" in card.headers["content-type"]
    assert card.json()["endpoints"]["mcp"] == "/mcp"

    # Stateless JSON-RPC 2.0 MCP
    init_resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        },
    )
    assert init_resp.status_code == 200
    assert init_resp.json()["result"]["serverInfo"]["name"] == "eranos"

    notif_resp = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert notif_resp.status_code == 202

    ping_resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert ping_resp.status_code == 200
    assert ping_resp.json()["result"] == {}

    list_resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    assert list_resp.status_code == 200
    tool_names = {t["name"] for t in list_resp.json()["result"]["tools"]}
    assert tool_names == {"list_tracks", "search_catalog", "get_kit", "practice_verify_kit"}

    tracks_call = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "list_tracks", "arguments": {}},
        },
    )
    assert tracks_call.status_code == 200
    assert len(tracks_call.json()["result"]["structuredContent"]["tracks"]) == len(load_tracks())

    search_call = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "search_catalog", "arguments": {"spdx": "CC-BY-4.0"}},
        },
    )
    assert search_call.status_code == 200
    found_kits = search_call.json()["result"]["structuredContent"]["kits"]
    assert [k["kit"]["kit_id"] for k in found_kits] == ["KIT-HOTLINE-02"]

    kit_call = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "get_kit", "arguments": {"kit_id": "KIT-RECRUIT-01"}},
        },
    )
    assert kit_call.status_code == 200
    assert kit_call.json()["result"]["isError"] is False
    assert kit_call.json()["result"]["structuredContent"]["kit"]["kit_id"] == "KIT-RECRUIT-01"

    bundle = load_example_bundles()[0]
    prac_call = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "practice_verify_kit", "arguments": {"draft": bundle["draft"]}},
        },
    )
    assert prac_call.status_code == 200
    prac_struct = prac_call.json()["result"]["structuredContent"]
    assert prac_struct["passed"] is True
    assert prac_struct["persisted"] is False


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
    # One promotion per published example kit, so a cursor past them finds no new entries.
    past_end = len(load_example_bundles()) + 2
    empty = client.get(f"/api/feed?after={past_end}&limit=10")
    assert empty.status_code == 200
    assert empty.json() == {
        "synthetic": True,
        "feed": "noun.promotions",
        "entries": [],
        "next_cursor": past_end,
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
                "entries": [
                    {
                        "seq": 8,
                        "payload": {"store": "eranos.catalog", "key": "KIT-RECRUIT-01"},
                        "namespace": "main",
                        "producer_surface": "surface:eranos",
                        "visibility_scope": "public_commons",
                        "allowed_surfaces": [],
                        "target_cohorts": ["all"],
                        "tags": ["status:verified"],
                    }
                ],
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
          entries: [{{ seq: 5, payload: {{key: "KIT-RECRUIT-01"}}, namespace: "main", producer_surface: "surface:eranos", visibility_scope: "public_commons", allowed_surfaces: [], target_cohorts: ["all"], tags: ["status:verified"] }}],
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
    assert out["fallbackFeed"] == visible(
        {
            "synthetic": True,
            "feed": "noun.promotions",
            "entries": [],
            "next_cursor": 9,
        }
    )
    hs_calls = [c for c in out["calls"] if c["url"].endswith("/v1/handshake")]
    assert len(hs_calls) == 2
    for call in hs_calls:
        assert call["init"]["headers"]["X-Surface-Id"] == "eranos"


def test_cloudflare_worker_discovery_mcp_practice_and_snapshot_assets() -> None:
    worker_path = (REPO_ROOT / "deploy" / "cloudflare" / "worker.js").as_posix()
    dist_dir = (REPO_ROOT / "web" / "public").as_posix()
    example_draft = load_example_bundles()[0]["draft"]

    script = f"""
import fs from "node:fs";
import path from "node:path";
import worker from {json.dumps(worker_path)};

const distDir = {json.dumps(dist_dir)};
const draft = {json.dumps(example_draft)};

const env = {{
  ASSETS: {{
    async fetch(req) {{
      const u = new URL(typeof req === "string" ? req : req.url);
      const target = path.join(distDir, u.pathname.replace(/^\\//, ""));
      if (fs.existsSync(target) && fs.statSync(target).isFile()) {{
        const ext = path.extname(target);
        const ct = ext === ".json"
          ? "application/json; charset=utf-8"
          : ext === ".svg"
            ? "image/svg+xml"
            : "text/html; charset=utf-8";
        return new Response(fs.readFileSync(target), {{
          status: 200,
          headers: {{ "content-type": ct }},
        }});
      }}
      // Simulate Cloudflare SPA soft-200 index.html fallback on missing paths!
      return new Response("<!doctype html><html><body>SPA</body></html>", {{
        status: 200,
        headers: {{ "content-type": "text/html; charset=utf-8" }},
      }});
    }},
  }},
}};

const fav = await worker.fetch(new Request("https://eranos.ta-amps.workers.dev/favicon.svg"), env);
const hz = await worker.fetch(new Request("https://eranos.ta-amps.workers.dev/healthz"), env);
const rob = await worker.fetch(new Request("https://eranos.ta-amps.workers.dev/robots.txt"), env);
const llms = await worker.fetch(new Request("https://eranos.ta-amps.workers.dev/llms.txt"), env);
const llmsFull = await worker.fetch(new Request("https://eranos.ta-amps.workers.dev/llms-full.txt"), env);
const card = await worker.fetch(new Request("https://eranos.ta-amps.workers.dev/.well-known/agent-card.json"), env);

const catFiltered = await worker.fetch(
  new Request("https://eranos.ta-amps.workers.dev/api/catalog?domain=nonprofit_ops&spdx=BSD-3-Clause"),
  env,
);
const missingKit = await worker.fetch(
  new Request("https://eranos.ta-amps.workers.dev/api/catalog/KIT-MISSING-99"),
  env,
);
const practiceOk = await worker.fetch(
  new Request("https://eranos.ta-amps.workers.dev/api/practice", {{
    method: "POST",
    headers: {{ "content-type": "application/json" }},
    body: JSON.stringify({{ draft }}),
  }}),
  env,
);
const mcpInit = await worker.fetch(
  new Request("https://eranos.ta-amps.workers.dev/mcp", {{
    method: "POST",
    headers: {{ "content-type": "application/json" }},
    body: JSON.stringify({{ jsonrpc: "2.0", id: 1, method: "initialize", params: {{}} }}),
  }}),
  env,
);
const mcpSearch = await worker.fetch(
  new Request("https://eranos.ta-amps.workers.dev/mcp", {{
    method: "POST",
    headers: {{ "content-type": "application/json" }},
    body: JSON.stringify({{
      jsonrpc: "2.0",
      id: 2,
      method: "tools/call",
      params: {{ name: "search_catalog", arguments: {{ spdx: "CC-BY-4.0" }} }},
    }}),
  }}),
  env,
);

console.log(JSON.stringify({{
  fav: {{ status: fav.status, ct: fav.headers.get("content-type") }},
  hz: {{ status: hz.status, ct: hz.headers.get("content-type"), body: await hz.json() }},
  rob: {{ status: rob.status, ct: rob.headers.get("content-type"), text: await rob.text() }},
  llms: {{ status: llms.status, ct: llms.headers.get("content-type"), len: (await llms.text()).length }},
  llmsFull: {{ status: llmsFull.status, ct: llmsFull.headers.get("content-type") }},
  card: {{ status: card.status, ct: card.headers.get("content-type"), body: await card.json() }},
  catFiltered: await catFiltered.json(),
  missingKit: {{ status: missingKit.status, ct: missingKit.headers.get("content-type") }},
  practiceOk: await practiceOk.json(),
  mcpInit: await mcpInit.json(),
  mcpSearch: await mcpSearch.json(),
}}));
"""
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=True,
    )
    out = json.loads(res.stdout)
    assert out["fav"] == {"status": 200, "ct": "image/svg+xml; charset=utf-8"}
    assert out["hz"]["status"] == 200
    assert "application/json" in out["hz"]["ct"]
    assert out["hz"]["body"]["ok"] is True
    assert out["rob"]["status"] == 200
    assert "text/plain" in out["rob"]["ct"]
    assert out["llms"]["status"] == 200 and out["llms"]["len"] > 100
    assert out["llmsFull"]["status"] == 200 and "text/plain" in out["llmsFull"]["ct"]
    assert out["card"]["status"] == 200 and out["card"]["body"]["endpoints"]["mcp"] == "/mcp"
    assert [k["kit"]["kit_id"] for k in out["catFiltered"]["kits"]] == ["KIT-GRANT-04"]
    assert out["missingKit"]["status"] == 404
    assert "json" in out["missingKit"]["ct"]
    assert "text/html" not in out["missingKit"]["ct"]
    assert out["practiceOk"]["passed"] is True
    assert out["practiceOk"]["persisted"] is False
    assert out["mcpInit"]["result"]["serverInfo"]["name"] == "eranos"
    assert [
        k["kit"]["kit_id"] for k in out["mcpSearch"]["result"]["structuredContent"]["kits"]
    ] == ["KIT-HOTLINE-02"]


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
    # Hunt, October 30: `re.match` with `$` let a trailing newline through, which the Worker refuses.
    assert client.get("/api/catalog/KIT-GRANT-04%0A").status_code == 400
    assert client.get("/api/nouns/eranos.instructions/site%0A").status_code == 404


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


def test_cloudflare_worker_swarm_fabric_aliases_and_rich_llms() -> None:
    worker_path = (REPO_ROOT / "deploy" / "cloudflare" / "worker.js").as_posix()
    dist_dir = (REPO_ROOT / "web" / "public").as_posix()
    script = f"""
import fs from "node:fs";
import path from "node:path";
import worker from {json.dumps(worker_path)};

const distDir = {json.dumps(dist_dir)};
const calls = [];
const env = {{
  TESSERA_SURFACE_KEY: "test-surface-key",
  ASSETS: {{
    async fetch(req) {{
      const u = new URL(typeof req === "string" ? req : req.url);
      const p = path.join(distDir, u.pathname.replace(/^\\//, ""));
      if (u.pathname !== "/" && fs.existsSync(p) && fs.statSync(p).isFile()) {{
        return new Response(fs.readFileSync(p), {{
          status: 200,
          headers: {{ "content-type": p.endsWith(".json") ? "application/json" : "text/plain" }},
        }});
      }}
      return new Response("not found", {{ status: 404 }});
    }},
  }},
  TESSERA: {{
    async fetch(url) {{
      const u = new URL(url);
      if (u.pathname === "/v1/health") {{
        return Response.json({{
          queues: [
            {{ name: "eq01", counts: {{ ready: 0, leased: 0, waiting: 0, done: 8, dead: 0, cancelled: 0 }} }},
            {{ name: "eq02", counts: {{ ready: 1, leased: 0, waiting: 0, done: 5, dead: 0, cancelled: 0 }} }},
            {{ name: "eq03", counts: {{ ready: 0, leased: 0, waiting: 0, done: 4, dead: 0, cancelled: 0 }} }},
          ],
        }});
      }}
      if (u.pathname === "/ns/main/v1/verbs") {{
        const q = u.searchParams.get("queue");
        return Response.json({{
          verbs: q === "eq02"
            ? [{{ task_id: "t-eq02-1", kind: "build", created_at: 1793500000, tags: ["open:anonymous"], brief: {{ title: "Build grant tracker kit", request_id: "rq-1", part: 1 }} }}]
            : [],
        }});
      }}
      return new Response("not found", {{ status: 404 }});
    }},
  }},
  HERMA: {{
    async fetch(url, init = {{}}) {{
      const u = new URL(url);
      calls.push({{ url: String(url), method: init.method || "GET", headers: init.headers || {{}} }});
      if (u.pathname === "/q/pulse") {{
        return Response.json({{
          queue_counts_by_tier: {{
            ngo_priority: {{ ready: 7, leased: 2, done: 112 }},
            public_general: {{ ready: 11, leased: 3, done: 263 }},
          }},
          worker_fleet: {{ registered_workers: 51 }},
          queue_embodiments: {{ hybrid_search_sidecar: {{ indexed_unique_contents: 1103 }} }},
        }});
      }}
      if (u.pathname === "/q/feedback") {{
        if ((init.method || "GET") === "POST") {{
          const body = JSON.parse(init.body || "{{}}");
          return Response.json({{ ok: true, accepted: true, proxied: true, summary: body.summary || "" }}, {{ status: 201 }});
        }}
        return Response.json({{ ok: true, proxied: true, items: [{{ id: "fb-1", summary: "live herma feedback" }}] }});
      }}
      return new Response("not found", {{ status: 404 }});
    }},
  }},
}};

const fab = await (await worker.fetch(new Request("https://eranos.ta-amps.workers.dev/api/fabric"), env)).json();
const fabOffline = await (await worker.fetch(new Request("https://eranos.ta-amps.workers.dev/api/fabric"), {{}})).json();
const healthAlias = await worker.fetch(new Request("https://eranos.ta-amps.workers.dev/health"), env);
const healthJson = await healthAlias.clone().json();
const tasksAlias = await (await worker.fetch(new Request("https://eranos.ta-amps.workers.dev/api/tasks"), env)).json();
const tasksOfflineResp = await worker.fetch(new Request("https://eranos.ta-amps.workers.dev/api/tasks"), {{}});
const dashRedirect = await worker.fetch(new Request("https://eranos.ta-amps.workers.dev/dashboard", {{ headers: {{ accept: "text/html" }} }}), env);
const dashJson = await (await worker.fetch(new Request("https://eranos.ta-amps.workers.dev/dashboard", {{ headers: {{ accept: "application/json" }} }}), env)).json();
const llms = await (await worker.fetch(new Request("https://eranos.ta-amps.workers.dev/llms.txt"), env)).text();
const llmsFull = await (await worker.fetch(new Request("https://eranos.ta-amps.workers.dev/llms-full.txt"), env)).text();

console.log(JSON.stringify({{
  fab,
  fabOffline,
  healthStatus: healthAlias.status,
  healthJson,
  tasksAlias,
  tasksOfflineStatus: tasksOfflineResp.status,
  dashRedirectStatus: dashRedirect.status,
  dashLocation: dashRedirect.headers.get("location"),
  dashJson,
  llmsLen: llms.length,
  llmsFullLen: llmsFull.length,
  llms,
  calls,
}}));
"""
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=True,
    )
    out = json.loads(res.stdout)
    assert out["fab"]["swarm"] == {
        "ngo_ready": 7,
        "ngo_leased": 2,
        "ngo_done": 112,
        "general_ready": 11,
        "general_leased": 3,
        "general_done": 263,
        "registered_workers": 51,
        "stored_task_objects": 1103,
    }
    assert "swarm" not in out["fabOffline"]
    assert out["healthStatus"] == 200
    assert out["healthJson"]["ok"] is True
    assert out["healthJson"]["surface"] == "eranos"
    assert len(out["tasksAlias"]["tasks"]) == 1
    assert out["tasksAlias"]["tasks"][0]["task_id"] == "t-eq02-1"
    assert out["tasksOfflineStatus"] == 200
    assert out["dashRedirectStatus"] == 307
    assert out["dashLocation"] == "https://herma.ta-amps.workers.dev/dashboard"
    assert out["dashJson"]["dashboard_url"] == "https://herma.ta-amps.workers.dev/dashboard"
    assert out["dashJson"]["swarm"]["registered_workers"] == 51
    assert out["llmsLen"] > 20000
    assert out["llmsFullLen"] > out["llmsLen"]
    for expected in (
        "https://eranos.ta-amps.workers.dev",
        "https://agora.ta-amps.workers.dev",
        "https://herma.ta-amps.workers.dev",
        "https://tessera.ta-amps.workers.dev",
        "/q/feedback",
        "/q/upload",
        "16 MiB",
        "step_mode",
        "atomic_cognitive_step",
        "atomic_build_step",
    ):
        assert expected in out["llms"], expected


def test_every_eranos_api_route_refuses_writes() -> None:
    """Owner rule: Eranos /api/* is GET/HEAD only; writes go to Tessera directly (no proxy, no Herma key here).
    POST /api/practice and POST /api/handshake predate the rule and are the two listed exceptions."""
    routes = [
        "/api/catalog",
        "/api/catalog/KIT-HOTLINE-02",
        "/api/tracks",
        "/api/examples",
        "/api/requests",
        "/api/fabric",
        "/api/open-tasks",
        "/api/models",
        "/api/nouns/eranos.instructions/home",
        "/api/feed",
        "/api/health",
        "/api/tasks",
        "/api/feedback",
    ]
    script = f"""
import worker from {json.dumps((REPO_ROOT / "deploy" / "cloudflare" / "worker.js").as_uri())};
const out = [];
for (const path of {json.dumps(routes)}) {{
  for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {{
    const r = await worker.fetch(new Request("https://eranos.ta-amps.workers.dev" + path, {{ method, headers: {{ "content-type": "application/json" }}, body: "{{}}" }}), {{}});
    out.push([path, method, r.status]);
  }}
}}
console.log(JSON.stringify(out));
"""
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script], check=True, capture_output=True, text=True
    )
    for path, method, status in json.loads(run.stdout):
        assert status in (404, 405), (path, method, status)
