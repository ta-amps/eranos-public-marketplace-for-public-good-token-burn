"""The package's tests: verify_kit, persona lint, the config supply-chain scan, the library's public
check, the shipped unit tests, and `docker compose run --rm test` from a clean folder."""

from __future__ import annotations

import ast
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VENDOR = ROOT / "vendor"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
STDLIB_OK = set(sys.stdlib_module_names)
LOCAL_URL = re.compile(r"https?://(?:127\.0\.0\.1|localhost)(?::\d+)?(?:/|\b)")
ANY_URL = re.compile(r"https?://[^\s\"'<>)]+")
DOC_URL_OK = ("https://opencode.ai/config.json",)  # a JSON schema id, never fetched by the run
RESERVED_URL = re.compile(r"https?://(?:[a-z0-9-]+\.)*example\.(?:com|org|net)\b")  # RFC 2606 names, used by tests


def nice(cmd: list[str]) -> list[str]:
    return ["nice", "-n", "10", *cmd]


def minimal_env(**extra: str) -> dict[str, str]:
    """The only environment package code and its tools ever get: no keys, tokens or worker settings."""
    return {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp"), "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1", **extra}


def verify_kit(draft: dict[str, Any], track_id: str) -> dict[str, Any]:
    """The marketplace's deterministic kit checks (vendored at its commit 6397473), in its own Python."""
    script = (
        "import json, sys; from pathlib import Path\n"
        f"sys.path.insert(0, {str(VENDOR / 'eranos_verify')!r})\n"
        "from eranos.verifier import practice_verify_kit, verify_kit\n"
        "from eranos.schemas import KitDraft\nfrom eranos.tracks import get_track\n"
        "draft = json.load(sys.stdin)\n"
        f"root = Path({str(VENDOR / 'eranos_verify' / 'tracks')!r})\n"
        f"practice = practice_verify_kit(draft, {track_id!r}, tracks_root=root)\n"
        "full = verify_kit(KitDraft.model_validate(draft), get_track(draft['track_id'], root)).model_dump(mode='json')\n"
        "print(json.dumps({'practice': practice, 'verify_kit': full}))\n"
    )
    result = subprocess.run([str(VENV_PYTHON), "-c", script], input=json.dumps(draft), capture_output=True, text=True, check=False,
                            env=minimal_env(), timeout=300)
    if result.returncode != 0:
        return {"passed": False, "error": result.stderr.strip()[-800:]}
    out = json.loads(result.stdout)
    passed = bool(out["practice"]["passed"] and out["verify_kit"]["passed"])
    # Public wording: the marketplace's check names are relabeled where the old word appears.
    labels = {"synthetic_fixtures": "made_up_test_cases"}
    return {"passed": passed, "checks_run": [labels.get(c, c) for c in out["verify_kit"]["checks_run"]],
            "issues": sorted(set(out["practice"]["issues"]) | set(out["verify_kit"]["issues"])),
            "fixture_count": out["verify_kit"]["fixture_count"], "human_only_steps": out["verify_kit"]["human_only_steps"],
            "practice_receipt_sha256": out["practice"]["receipt_sha256"]}


def persona_lint(code: Path, lint: dict[str, Any], configs: list[dict[str, Any]]) -> dict[str, Any]:
    """The compiler's lint plus a re-read of every compiled file: present, digest matches, no fluff left."""
    sys.path.insert(0, str(VENDOR))
    import persona_compiler as pc  # noqa: PLC0415

    problems = []
    if not lint["permission_separation"]["separated"]:
        problems.append("permission leaks: " + json.dumps(lint["permission_separation"]["permission_leaks"]))
    if lint["fluff_stripping"]["removed_count"]:
        problems.append(f"{lint['fluff_stripping']['removed_count']} persona fluff sentences were in the role")
    score = lint["delegation_description_audit"]["score"]
    if score < 0.75:
        problems.append(f"routing description scores {score}, below 0.75")
    per_target = []
    for cfg in configs:
        data = (code / cfg["path"]).read_bytes()
        import hashlib  # noqa: PLC0415

        ok_digest = hashlib.sha256(data).hexdigest() == cfg["sha256"]
        fluff = pc.strip_degrading_fluff(data.decode("utf-8"))["removed_count"]
        per_target.append({"target": cfg["target"], "path": cfg["path"], "digest_matches": ok_digest,
                           "fluff_sentences": fluff, "warnings": cfg["warnings"]})
        if not ok_digest or fluff:
            problems.append(f"{cfg['path']}: digest {'ok' if ok_digest else 'differs'}, fluff {fluff}")
    passing = [t for t in per_target if t["digest_matches"] and not t["fluff_sentences"]]
    return {"passed": not problems, "description_score": score, "targets_passing": len(passing),
            "targets": per_target, "problems": problems}


def supply_chain_scan(code: Path, images_lock: dict[str, Any]) -> dict[str, Any]:
    """Gemini's config scanner plus this package's own rules: pinned images, no runtime fetch, no
    service with a network, a read-only data mount, no model step, and a standard-library-only runner."""
    sys.path.insert(0, str(VENDOR))
    from config_scanner import scan_repository_configs  # noqa: PLC0415

    scan = scan_repository_configs(code, allowlisted_mcp_commands=set())
    rules: list[dict[str, Any]] = []

    def rule(name: str, ok: bool, detail: str) -> None:
        rules.append({"rule": name, "passed": bool(ok), "detail": detail})

    dockerfile = (code / "Dockerfile").read_text(encoding="utf-8")
    froms = re.findall(r"(?m)^FROM\s+(\S+)", dockerfile)
    rule("dockerfile-base-pinned-by-digest", froms and all("@sha256:" in f for f in froms), ", ".join(froms))
    rule("dockerfile-no-fetch", not re.search(r"(?im)^\s*RUN\b|curl|wget|pip install|apt-get|apk add", dockerfile),
         "no RUN, curl, wget, pip, apt or apk lines")
    rule("dockerfile-no-remote-frontend", "# syntax=" not in dockerfile, "no BuildKit frontend image to download")
    compose = (code / "compose.yaml").read_text(encoding="utf-8")
    images = re.findall(r"(?m)^\s+image:\s*(\S+)", compose)
    external = [i for i in images if not i.endswith(":local")]
    pinned = images_lock.get("images", {})
    rule("compose-images-pinned", all("@sha256:" in i or pinned.get(i, {}).get("digest") for i in external),
         ", ".join(f"{i} -> {pinned.get(i, {}).get('digest', 'digest inline')}" for i in external))
    blocks = re.split(r"(?m)^  (?=[a-z][a-z0-9-]*:\s*$)", compose.split("services:", 1)[1].split("\nnetworks:", 1)[0])
    services = {b.split(":", 1)[0]: b for b in blocks if b.strip()}
    built = [n for n, blk in services.items() if "build: ." in blk]
    rule("built-images-never-pulled", all("pull_policy: build" in services[n] for n in built),
         "every service built from the Dockerfile has pull_policy: build, so a same-named registry image is never pulled")
    extra = [name for name in OVERRIDE_NAMES if (code / name).exists()]
    rule("no-compose-overrides-or-env", not extra, f"no override or .env files: {extra or 'none'}")
    networked = [n for n, blk in services.items() if "network_mode: none" not in blk]
    rule("no-service-has-a-network", not networked and set(services) == {"run", "test"},
         f"services: {sorted(services)}; with a network: {networked or 'none'}")
    for name in ("run", "test"):
        rule(f"{name}-has-no-network", "network_mode: none" in services.get(name, ""), "network_mode: none")
        block = services.get(name, "")
        rule(f"{name}-has-limits", all(x in block for x in ("mem_limit:", "cpus:", "pids_limit:", "read_only: true", "cap_drop: [ALL]")),
             "memory, CPU and process limits, read-only, no capabilities")
    rule("data-mounted-read-only", '"${DATA_DIR:-./data}:/data:ro"' in services.get("run", ""), "the data folder is mounted :ro")
    spec = json.loads((code / "process.json").read_text(encoding="utf-8"))
    rule("model-free-by-default", "model" not in spec and (spec.get("summary_hook") or {}).get("default") == "off"
         and all(i.endswith(":local") for i in re.findall(r"(?m)^\s+image:\s*(\S+)", compose)),
         "no model step or model service; the summary hook is off by default")
    tree = ast.parse((code / "run_process.py").read_text(encoding="utf-8"))
    imported = sorted({(a.name if isinstance(n, ast.Import) else n.module).split(".")[0]
                       for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                       for a in (n.names if isinstance(n, ast.Import) else [n]) if (a.name if isinstance(n, ast.Import) else n.module)})
    outside = [m for m in imported if m not in STDLIB_OK and m != "__future__"]
    rule("runner-standard-library-only", not outside, "imports: " + ", ".join(imported))
    urls = []
    for path in sorted(code.rglob("*")):
        if not path.is_file() or path.suffix in (".csv", ".tsv", ".pyc") or "samples" in path.parts or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for url in ANY_URL.findall(text):
            if not LOCAL_URL.match(url) and url not in DOC_URL_OK and not RESERVED_URL.match(url):
                urls.append(f"{path.relative_to(code).as_posix()}: {url}")
    rule("no-remote-urls-in-configs-or-code", not urls, "; ".join(urls) or "only 127.0.0.1, localhost and the compose service")
    settings = json.loads((code / ".claude" / "settings.json").read_text(encoding="utf-8"))
    rule("claude-settings-deny-web-and-edits", {"WebFetch", "WebSearch", "Edit", "Write"} <= set(settings["permissions"]["deny"]),
         "deny: " + ", ".join(settings["permissions"]["deny"]))
    passed = scan["verdict"] == "clean" and all(r["passed"] for r in rules)
    return {"passed": passed, "scanner_verdict": scan["verdict"], "scanned_files": scan["scanned_files_count"],
            "scanner_findings": scan["findings"], "inventory_sha256": scan["inventory_sha256"], "rules": rules}


def public_check(pack_dir: Path) -> dict[str, Any]:
    """The library's check_public.py (secrets and private names) over the whole pack folder."""
    result = subprocess.run([sys.executable, str(VENDOR / "library" / "scripts" / "check_public.py"), str(pack_dir)],
                            capture_output=True, text=True, check=False, env=minimal_env(), timeout=300)
    return {"passed": result.returncode == 0, "output": (result.stdout + result.stderr).strip()[-600:]}


def unit_tests(code: Path) -> dict[str, Any]:
    result = subprocess.run(nice([sys.executable, "-W", "error", "-B", "-m", "unittest", "discover", "-s", "tests", "-v"]),
                            cwd=code, capture_output=True, text=True, check=False, env=minimal_env(), timeout=600)
    ran = re.search(r"Ran (\d+) tests?", result.stderr)
    return {"passed": result.returncode == 0, "tests": int(ran.group(1)) if ran else 0,
            "tail": result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ""}


COMPOSE_LOCKED = ["-f", "compose.yaml", "--env-file", "/dev/null"]
OVERRIDE_NAMES = ("compose.override.yaml", "compose.override.yml", "docker-compose.yml", "docker-compose.yaml",
                  "docker-compose.override.yml", "docker-compose.override.yaml", "compose.yml", ".env")


def docker_test(bundle_path: Path, pack_id: str, workdir: Path | None = None, keep_image: bool = False,
                timeout: int = 600) -> dict[str, Any]:
    """The builder's own check on its own bundle: extract it into a new empty folder and run
    `docker compose run --rm test` there with only compose.yaml (no override or .env file is read),
    a minimal environment and a timeout. Containers, images and networks are removed in `finally`."""
    if shutil.which("docker") is None:
        return {"passed": False, "ran": False, "reason": "docker is not installed"}
    base = Path(tempfile.mkdtemp(prefix="process-clean-", dir=workdir))
    try:
        with tarfile.open(bundle_path, "r:gz") as tar:
            tar.extractall(base, filter="data")
        open_folders(base)
        code = base / pack_id / "code"
        extra = [name for name in OVERRIDE_NAMES if (code / name).exists()]
        if extra:
            return {"passed": False, "ran": False, "reason": f"refused: the bundle holds compose config {extra}"}
        env = minimal_env(COMPOSE_PROJECT_NAME=f"{pack_id}-test-{os.getpid()}", DOCKER_BUILDKIT="1")
        compose = ["docker", "compose", *COMPOSE_LOCKED, "--project-directory", str(code)]
        # A clean test uses no cached layer: a cached folder keeps the permissions of whichever build made it.
        subprocess.run([*compose, "build", "--no-cache", "--pull=false", "test"], capture_output=True, text=True, check=False, env=env, cwd=str(code), timeout=timeout)
        timed_out, log, code_ = False, "", None
        try:
            result = subprocess.run(nice([*compose, "--progress", "plain", "run", "--rm", "test"]), cwd=code,
                                    capture_output=True, text=True, check=False, env=env, timeout=timeout)
            log, code_ = result.stdout + result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            cleanup = subprocess.run([*compose, "down", "--rmi", "local" if not keep_image else "none", "--volumes",
                                      "--remove-orphans", "--timeout", "5"], cwd=code, capture_output=True, text=True,
                                     check=False, env=env, timeout=300)
        ran = re.findall(r"Ran (\d+) tests?", log)
        pulled = bool(re.search(r"(?i)\bpulling\b|pull complete|Downloaded newer image|pull access denied", log))
        return {"passed": not timed_out and code_ == 0 and bool(ran) and re.search(r"(?m)^OK\b", log) is not None and not pulled,
                "ran": True, "timed_out": timed_out, "tests": int(ran[-1]) if ran else 0, "exit_code": code_,
                "limits": "1 GB memory, 1 CPU, 256 processes, user 65534, read-only, %d s" % timeout,
                "environment": sorted(env), "pulled_anything": pulled, "network": "none (network_mode: none)",
                "command": "docker compose -f compose.yaml --env-file /dev/null run --rm test",
                "clean_folder": "a new empty temporary folder with only the extracted bundle",
                "base_image_lines": [ln.strip() for ln in log.splitlines() if "docker.io/library/python" in ln][:3],
                "log_tail": log.strip().splitlines()[-3:], "cleanup_exit_code": cleanup.returncode}
    finally:
        shutil.rmtree(base, ignore_errors=True)


def open_folders(root: Path) -> None:
    """A worker runs with a private umask, so extracted folders come out private; the tests run as another
    user and must be able to read them. This changes the extracted copy only, never the bundle."""
    root = Path(root)
    root.chmod(0o755)
    for path in root.rglob("*"):
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o755)
        elif path.is_file() and not path.is_symlink():
            path.chmod(path.stat().st_mode | 0o444)


def sandbox_test(code_dir: Path, image_ref: str, timeout: int = 300) -> dict[str, Any]:
    """The reviewer's run of the vetted tests: plain `docker run` with every setting chosen here and
    nothing read from the package. The pinned base image runs the tests from the reviewer's own
    checked copy, mounted read-only; no network, no capabilities, a non-root user, limits, a tmpfs
    for /tmp, a time limit inside and outside the container, and `docker rm -f` in `finally`."""
    if shutil.which("docker") is None:
        return {"passed": False, "ran": False, "reason": "docker is not installed"}
    name = f"b4-review-{os.getpid()}-{secrets.token_hex(4)}"
    cmd = ["docker", "run", "--rm", "--name", name, "--pull", "never", "--network", "none", "--read-only",
           "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "256", "--memory", "1g",
           "--memory-swap", "1g", "--cpus", "1", "--user", "65534:65534", "--tmpfs", "/tmp:rw,size=64m,mode=1777",
           "--mount", f"type=bind,src={Path(code_dir).resolve()},dst=/process,readonly", "--workdir", "/process",
           "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "HOME=/tmp", image_ref,
           "timeout", str(max(30, timeout - 30)), "python3", "-B", "-W", "error", "-m", "unittest", "discover", "-s", "tests", "-v"]
    timed_out, log, code_ = False, "", None
    try:
        result = subprocess.run(nice(cmd), capture_output=True, text=True, check=False, env=minimal_env(), timeout=timeout)
        log, code_ = result.stdout + result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        removed = subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True, check=False,
                                 env=minimal_env(), timeout=60)
    ran = re.findall(r"Ran (\d+) tests?", log)
    return {"passed": not timed_out and code_ == 0 and bool(ran) and re.search(r"(?m)^OK\b", log) is not None,
            "ran": True, "timed_out": timed_out, "tests": int(ran[-1]) if ran else 0, "exit_code": code_,
            "container": name, "removed": removed.returncode in (0, 1), "command": " ".join(cmd[:2] + ["(flags set by the reviewer)"]),
            "limits": "no network, read-only, no capabilities, no new privileges, user 65534, 1 GB, 1 CPU, 256 processes, "
                      f"tmpfs /tmp, {timeout} s", "log_tail": log.strip().splitlines()[-3:]}
