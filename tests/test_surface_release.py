"""Release regression controls: reject stale modes/assets, retain safe dark ink."""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "surface_release", Path(__file__).parents[1] / "scripts/check_surface_release.py"
)
assert SPEC and SPEC.loader
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(
        '<meta name="color-scheme" content="light"><script src="/assets/ui.js"></script>'
    )
    (tmp_path / "assets/ui.css").write_text(
        ":root{color-scheme:light;background:#F5F2EA;color:#11161f}"
    )
    (tmp_path / "assets/ui.js").write_text(
        'const ids="band-toggle-";const expanded="aria-expanded";'
    )
    return tmp_path


def test_light_shell_allows_dark_text(dist):
    assert release.inspect_assets(dist)["assets/ui.css"]


@pytest.mark.parametrize(
    "bad",
    [
        '<meta name="color-scheme" content="light dark">',
        '<meta name="color-scheme" content="dark">',
    ],
)
def test_retired_shell_rejected(dist, bad):
    (dist / "index.html").write_text(bad)
    with pytest.raises(ValueError, match="Light-only"):
        release.inspect_assets(dist)


def test_dark_os_override_rejected(dist):
    (dist / "assets/ui.css").write_text(
        ":root{color-scheme:light;}@media(prefers-color-scheme:dark){body{background:#11161f}}"
    )
    with pytest.raises(ValueError, match="Retired dark"):
        release.inspect_assets(dist)


def test_legacy_request_template_rejected(dist):
    (dist / "assets/ui.js").write_text('const template="old list of stages";')
    with pytest.raises(ValueError, match="accordion"):
        release.inspect_assets(dist)


def test_manifest_binds_mode_source_and_exact_assets(dist):
    manifest = {
        "source_commit": "head",
        "policy_sha256": "policy",
        "build_mode": "production_live",
        "files": release.inspect_assets(dist),
    }
    (dist / release.MANIFEST).write_text(json.dumps(manifest))
    assert release.verify_manifest(dist, "head", "policy") == manifest
    with pytest.raises(ValueError, match="another source"):
        release.verify_manifest(dist, "other", "policy")
    manifest["build_mode"] = "snapshot"
    (dist / release.MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Snapshot"):
        release.verify_manifest(dist, "head", "policy")
    manifest["build_mode"] = "production_live"
    (dist / release.MANIFEST).write_text(json.dumps(manifest))
    (dist / "assets/ui.js").write_text(
        'const ids="band-toggle-";const expanded="aria-expanded";let changed=1;'
    )
    with pytest.raises(ValueError, match="assets changed"):
        release.verify_manifest(dist, "head", "policy")


def test_nested_manifest_name_remains_hash_bound(dist):
    (dist / "assets/surface-release.json").write_text('{"value":1}')
    manifest = {
        "source_commit": "head",
        "policy_sha256": "policy",
        "build_mode": "production_live",
        "files": release.inspect_assets(dist),
    }
    (dist / release.MANIFEST).write_text(json.dumps(manifest))
    (dist / "assets/surface-release.json").write_text('{"value":2}')
    with pytest.raises(ValueError, match="assets changed"):
        release.verify_manifest(dist, "head", "policy")


def test_production_build_overrides_snapshot_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env.production.local").write_text("VITE_SNAPSHOT=1\n")
    monkeypatch.setattr(release, "ROOT", tmp_path)
    seen = []
    monkeypatch.setattr(
        release.subprocess, "run", lambda argv, **kwargs: seen.append((argv, kwargs))
    )
    release.production_build()
    assert seen[0][0] == ["pnpm", "--dir", "web", "build"]
    assert seen[0][1]["env"]["VITE_SNAPSHOT"] == "0"
    assert (tmp_path / ".env.production.local").read_text() == "VITE_SNAPSHOT=1\n"
