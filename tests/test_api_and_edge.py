"""Tests for Eranos FastAPI endpoints, strict kit_id validation, and Cloudflare edge lockdown."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eranos.api.app import app
from eranos.cli import main as cli_main

SECRET = "edge-secret-for-tests-only"  # check-public: allow


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db = tmp_path / "eranos.db"
    monkeypatch.setenv("ERANOS_LOCAL_DB", str(db))
    monkeypatch.setenv("ERANOS_TRACE", str(tmp_path / "trace.jsonl"))
    monkeypatch.delenv("ERANOS_EDGE_SECRET", raising=False)
    assert cli_main(["verify-examples"]) == 0
    return TestClient(app)


def test_api_serves_tracks_catalog_requests_and_fabric(client: TestClient) -> None:
    assert client.get("/api/health").json()["surface"] == "eranos"
    tracks = client.get("/api/tracks").json()
    assert len(tracks["tracks"]) == 6

    cat = client.get("/api/catalog").json()
    assert cat["two_step_verified"] is True
    assert len(cat["kits"]) == 4

    detail = client.get("/api/catalog/KIT-RECRUIT-01")
    assert detail.status_code == 200
    assert detail.json()["kit"]["kit_id"] == "KIT-RECRUIT-01"

    reqs = client.get("/api/requests").json()
    assert len(reqs["stages"]) == 3
    assert len(reqs["requests"]) >= 4

    fab = client.get("/api/fabric").json()
    assert {q["name"] for q in fab["queues"]} == {"eq01", "eq02", "eq03"}


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
