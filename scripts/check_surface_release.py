"""Fail closed before uploading stale, snapshot-mode, or unreviewed surface assets."""

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "deploy/cloudflare/surface-release-policy.json"
DIST = ROOT / "web/dist"
MANIFEST = "surface-release.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def tree(dist: Path) -> dict[str, str]:
    files = {}
    for path in sorted(dist.rglob("*")):
        require(not path.is_symlink(), "Release assets must not contain symlinks")
        if path.is_file() and path != dist / MANIFEST:
            files[path.relative_to(dist).as_posix()] = digest(path.read_bytes())
    return files


def inspect_assets(dist: Path) -> dict[str, str]:
    html = (dist / "index.html").read_text()
    # Light only (rule 13): the meta and the CSS say "only light" or "light", and nothing else.
    metas = re.findall(r'<meta\s+name="color-scheme"\s+content="([^"]*)"', html)
    require(metas and all(m in ("only light", "light") for m in metas), "Light-only HTML required")
    css = "\n".join(p.read_text() for p in (dist / "assets").glob("*.css"))
    require(
        not re.search(
            r"prefers-color-scheme\s*:\s*dark|color-scheme\s*:\s*(?:light\s+dark|dark)", css
        ),
        "Retired dark palette present",
    )
    schemes = re.findall(r"color-scheme\s*:\s*([^;}]+)", css)
    require(bool(schemes), "Compiled light scheme missing")
    require(
        all(s.strip() in ("only light", "light", "light only") for s in schemes),
        "Compiled color-scheme must be only light",
    )
    js = "\n".join(p.read_text() for p in (dist / "assets").glob("*.js"))
    require("band-toggle-" in js and "aria-expanded" in js, "Reviewed request accordion missing")
    for asset in re.findall(r'(?:src|href)="(/assets/[^"?]+)', html):
        require((dist / asset.lstrip("/")).is_file(), "HTML references a missing compiled asset")
    return tree(dist)


def verify_manifest(dist: Path, head: str, policy_hash: str) -> dict:
    manifest = json.loads((dist / MANIFEST).read_text())
    require(manifest["source_commit"] == head, "Built assets belong to another source commit")
    require(manifest["policy_sha256"] == policy_hash, "Release policy changed after build")
    require(manifest["build_mode"] == "production_live", "Snapshot/test builds cannot be deployed")
    require(manifest["files"] == inspect_assets(dist), "Built assets changed or are stale")
    return manifest


def source_head(policy: dict) -> str:
    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)

    status = git("status", "--porcelain", "--untracked-files=all")
    require(
        status.returncode == 0 and not status.stdout.strip(),
        "Commit reviewed changes before building release assets",
    )
    head = git("rev-parse", "HEAD").stdout.strip()
    for commit in policy["required_ancestors"]:
        require(
            git("merge-base", "--is-ancestor", commit, head).returncode == 0,
            "Required UI/backend release ancestry is missing: " + commit,
        )
    return head


def production_build() -> None:
    """Process env wins over Vite dotenv files; only the literal 1 enables snapshot mode."""
    env = {**os.environ, "VITE_SNAPSHOT": "0"}
    subprocess.run(["pnpm", "--dir", "web", "build"], cwd=ROOT, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--check", action="store_true")
    parser.add_argument("--expected-live-version")
    args = parser.parse_args()
    policy_raw = POLICY.read_bytes()
    policy = json.loads(policy_raw)
    head = source_head(policy)
    require(not os.environ.get("VITE_SNAPSHOT"), "Unset VITE_SNAPSHOT for production release")
    if args.prepare:
        require(
            bool(args.expected_live_version),
            "Record the observed live version before release preparation",
        )
        # Vite empties dist on this build. A Playwright snapshot build cannot supply this manifest.
        production_build()
        manifest = {
            "schema": "eranos.surface-release.v1",
            "source_commit": head,
            "policy_sha256": digest(policy_raw),
            "expected_live_version": args.expected_live_version,
            "build_mode": "production_live",
            "files": inspect_assets(DIST),
        }
        (DIST / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")
    checked = verify_manifest(DIST, head, digest(policy_raw))
    print(
        json.dumps(
            {
                "status": "pass",
                "source_commit": head,
                "assets": len(checked["files"]),
                "expected_live_version": checked["expected_live_version"],
            }
        )
    )


if __name__ == "__main__":
    main()
