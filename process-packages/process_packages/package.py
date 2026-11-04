"""Deterministic packaging: the launchable code/ folder, the agent configs from the persona compiler,
the containers, the docs, and a byte-reproducible .tar.gz bundle with its SHA-256."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import shutil
import sys
import tarfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RUNNER = HERE.parent / "runner"
VENDOR = HERE.parent / "vendor"
BASE_IMAGE = "python:3.12.13-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36"
FIXED_MTIME = 1793318400  # 2026-10-31T00:00:00Z, so the bundle is byte-reproducible
EXECUTABLE = {"launch.sh", "run_process.py"}
HARNESS_TARGETS = ("claude_code", "codex", "opencode", "cursor", "vscode_copilot", "gemini_cli", "roo_code", "kiro")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def jdump(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def persona_compiler() -> Any:
    sys.path.insert(0, str(VENDOR))
    import persona_compiler  # noqa: PLC0415 (vendored)

    return persona_compiler


def role_spec(ctx: dict[str, Any]) -> dict[str, Any]:
    instructions = "\n".join([
        ctx["skill_text"],
        "",
        ctx.get("role_run") or
        "Run it from this folder with: python3 run_process.py --input FOLDER --output RESULTS, where FOLDER is the folder "
        "the person names and RESULTS is a separate folder. With Docker, the same is: DATA_DIR=FOLDER docker compose run --rm run.",
        ctx.get("role_rules") or
        "Rules that always apply: leave the original files exactly as they are; let a person decide every flagged row; "
        "never reach out to volunteers; never send the files or the results anywhere; use only this process's own command "
        "and do not install or fetch anything; report numbers only from report.md.",
    ])
    return {
        "slug": ctx["slug"],
        "title": ctx["skill_title"],
        "description": ctx["skill_description"],
        "instructions": instructions,
        "allowed_capabilities": ["read", "shell"],
        "allowed_tools": ["Read", "Grep", "Glob", "Bash"],
        "disallowed_tools": ["Write", "Edit", "WebFetch", "WebSearch"],
        "max_turns": ctx.get("role_max_turns", 12),
        "drift_checkpoint_rounds": 8,
    }


def compile_role(role: dict[str, Any], swaps: dict[str, str] | None = None) -> dict[str, Any]:
    """The role compiled for every harness; `swaps` changes a class's wording in the compiler's fixed lines."""
    pc = persona_compiler()
    lint = {
        "delegation_description_audit": pc.score_delegation_description(role["description"]),
        "fluff_stripping": pc.strip_degrading_fluff(role["instructions"]),
        "permission_separation": pc.verify_permission_separation(role),
    }
    compiled = pc.compile_portable_role(role, targets=list(HARNESS_TARGETS))
    for art in compiled["artifacts"].values():
        for old, new in (swaps or {}).items():
            art["content"] = art["content"].replace(old, new)
        if swaps:
            art["content_sha256"] = sha256_bytes(art["content"].encode())
    return {"lint": lint, "compiled": compiled}


def adapted_configs(role: dict[str, Any], compiled: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Formats the harnesses load today where the compiler's file differs (see findings): Roo Code
    reads one `.roomodes` file with customModes, and OpenCode loads agents from markdown files."""
    body = compiled["artifacts"]["opencode"]["content"]
    opencode = json.loads(body)
    md = ["---", f"description: {json.dumps(role['description'])}", "mode: all", "permission:",
          "  edit: deny", "  webfetch: deny", "  bash:", '    "*": deny', '    "python3 run_process.py *": allow',
          '    "python3 -m unittest *": allow', "---", "", opencode["prompt"], ""]
    roo = json.loads(compiled["artifacts"]["roo_code"]["content"])
    return {
        "opencode_markdown": {"path": f".opencode/agents/{role['slug']}.md", "content": "\n".join(md),
                              "adapted_from": "opencode", "why": "OpenCode loads project agents from markdown files with frontmatter."},
        "roo_modes": {"path": ".roomodes", "content": jdump({"customModes": [roo]}),
                      "adapted_from": "roo_code", "why": "Roo Code reads a single .roomodes file holding customModes."},
    }


def claude_settings() -> dict[str, Any]:
    return {
        "permissions": {
            "allow": ["Bash(python3 run_process.py:*)", "Bash(python3 -m unittest:*)", "Read", "Grep", "Glob"],
            "deny": ["WebFetch", "WebSearch", "Edit", "Write", "Bash(curl:*)", "Bash(wget:*)", "Bash(pip:*)",
                     "Bash(rm:*)", "Bash(mv:*)"],
        }
    }


def opencode_json() -> dict[str, Any]:
    return {
        "$schema": "https://opencode.ai/config.json",
        "autoupdate": False,
        "share": "disabled",
        "permission": {"edit": "deny", "webfetch": "deny",
                       "bash": {"*": "deny", "python3 run_process.py *": "allow", "python3 -m unittest *": "allow"}},
    }


def dockerfile() -> str:
    return "\n".join([
        "# The runner image: standard-library Python, nothing installed, nothing fetched while building or running.",
        f"FROM {BASE_IMAGE}",
        "ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1",
        "WORKDIR /process",
        "COPY run_process.py process.json ./",
        "COPY tests ./tests",
        "COPY samples ./samples",
        "USER 65534:65534",
        'ENTRYPOINT ["python3", "run_process.py"]',
        'CMD ["--input", "/data", "--output", "/results"]',
        "",
    ])


def compose_yaml(pack_id: str, _unused: str | None = None) -> str:
    """The runner and its tests, each with no network at all; the package has no model service."""
    hardening = ["    read_only: true", "    tmpfs: [/tmp]", "    cap_drop: [ALL]",
                 "    security_opt: [\"no-new-privileges:true\"]",
                 "    mem_limit: 1g", "    cpus: 1.0", "    pids_limit: 256"]
    image = f"    image: {pack_id}:local\n    pull_policy: build"
    lines = [
        f"# {pack_id}: run the process where the files are. No service has a network.",
        f"name: {pack_id}",
        "services:",
        "  run:",
        "    build: .", image,
        '    user: "${HOST_UID:-1000}:${HOST_GID:-1000}"',
        "    network_mode: none", *hardening,
        "    volumes:",
        '      - "${DATA_DIR:-./data}:/data:ro"',
        '      - "${RESULTS_DIR:-./results}:/results"',
        "  test:",
        "    build: .", image,
        '    user: "65534:65534"',
        "    network_mode: none", *hardening,
        "    working_dir: /process",
        '    entrypoint: ["python3", "-W", "error", "-m", "unittest", "discover", "-s", "tests", "-v"]',
        "    command: []",
        "",
    ]
    return "\n".join(lines)


LAUNCH_SH = """#!/bin/sh
# One command: ./launch.sh /path/to/your/sheets [results-folder]
# Uses Docker when it is installed, otherwise Python 3.10 or newer. Your files are only read.
set -eu
if [ "$#" -lt 1 ] || [ ! -d "$1" ]; then
  echo "usage: ./launch.sh /path/to/your/sheets [results-folder]" >&2
  exit 2
fi
HERE=$(cd "$(dirname "$0")" && pwd)
DATA_DIR=$(cd "$1" && pwd)
RESULTS_DIR=${2:-$HERE/results}
mkdir -p "$RESULTS_DIR"
RESULTS_DIR=$(cd "$RESULTS_DIR" && pwd)
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  cd "$HERE"
  DATA_DIR="$DATA_DIR" RESULTS_DIR="$RESULTS_DIR" HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose run --rm run
else
  python3 "$HERE/run_process.py" --input "$DATA_DIR" --output "$RESULTS_DIR"
fi
echo "Open $RESULTS_DIR/report.md, then check every row in flags.csv marked needs_person = yes."
"""

MAKEFILE = """# Checks for the process: standard library only, warnings are errors.
PYTHON ?= python3
.PHONY: check test docker-test
check: test
test:
\t$(PYTHON) -W error -m unittest discover -s tests -v
docker-test:
\tdocker compose run --rm test
"""


def install_md(ctx: dict[str, Any]) -> str:
    return f"""# Install and launch

Everything runs on your own computer or your own cloud account. Your spreadsheets are only read,
never changed, and nothing is sent anywhere. Pick one way.

## 1. Docker (one command)

Install Docker Desktop (Windows, macOS) or Docker Engine (Linux), open a terminal in this folder, then:

    ./launch.sh /path/to/your/sheets

Results go to `results/` here. On Windows PowerShell:

    $env:DATA_DIR="C:\\path\\to\\sheets"; $env:RESULTS_DIR="$PWD\\results"; docker compose run --rm run

The first run builds a small image from the pinned base image `{BASE_IMAGE.split('@')[0]}` (pinned by
digest in the Dockerfile). After that it works with no internet connection: the run has no network at all.

Check it first on the made-up sample sheets in `samples/` (no real data):

    docker compose run --rm test

## 2. Python only (no Docker)

Python 3.10 or newer, no packages to install:

    python3 run_process.py --input /path/to/your/sheets --output results
    python3 -m unittest discover -s tests -v

## 3. Your own agent

Open this folder in your agent harness and ask it to clean the sheets in your folder. Settings are
included for Claude Code, Codex, OpenCode, Cursor, GitHub Copilot, Gemini CLI, Roo Code and Kiro
(see `harness/README.md`). The agent may run only this process's own command; it cannot edit files,
browse the web or reach anyone.

The first time, open the folder in the harness interactively and accept its trust prompt: Claude Code,
for example, ignores the folder's permission settings until a person trusts the folder once. If your
agent runs on a model on your own computer, give that model a context of at least 16384 tokens,
because agent harnesses send long prompts.

## 4. Optional: a summary paragraph from your own agent

Off by default: the process needs no model. If you want a short summary paragraph in the report,
written by your own agent's model, add `--summary-command "<your agent's command>"` to the Python
command. The command runs on your computer, receives only the counts on its input (never a row,
name or address) and must print a short paragraph. The paragraph is kept only when every number in
it appears in the counts; otherwise the report keeps its fixed summary and says why.

## 5. In your own cloud account

Use any virtual machine you control (for example a small Linux VM with Docker): copy this folder and
your sheets to it, then run step 1 there. The sheets stay inside your account. Do not use a shared
or public machine, and delete the copies when you are done.

## Change the defaults

`process.json` holds the steps and their settings, for example `assume_order` (MDY or DMY) for dates
that could be read either way and `default_country` (US, CA or GB) for phone numbers without a
country code. Run the tests again after a change.

Frequency asked for: {ctx['request'].get('frequency') or 'not stated'}. Run it again each time you export new sheets.
"""


def howto_md(ctx: dict[str, Any]) -> str:
    steps = "\n".join(f"{i}. `{s['operation']}`: {s['instruction']}" for i, s in enumerate(ctx["steps"], 1))
    return f"""# How to use: {ctx['title']}

## What it is for

{ctx['description']}

## How it works

{ctx['howto_text']}

## The steps

{steps}

## Read the results

- `results/report.md`: the counts and what needs a person. It holds counts only, never rows.
- `results/flags.csv`: one row per change or question. Rows marked `needs_person = yes` wait for you.
- `results/cleaned/`: the cleaned copies of your sheets, with the same columns.
- `results/receipt.json`: the SHA-256 of every input before and after (unchanged), and of every output.

## What stays with a person

- Deciding every flagged row: possible duplicates, details that disagree, dates or phone numbers the
  process could not read, and missing contact details.
- Deciding whether anyone is asked for a missing detail, through your own channels.

{ctx['howto_credit']}
"""


def code_readme(ctx: dict[str, Any]) -> str:
    return f"""# {ctx['title']}

{ctx['description']}

Quick start (Docker, or Python 3.10+ when Docker is missing):

    ./launch.sh /path/to/your/sheets

Then open `results/report.md` and check every row in `results/flags.csv` marked `needs_person = yes`.

- How it works and how to read the results: [HOWTO.md](HOWTO.md)
- Every way to install and launch, including your own cloud account: [INSTALL.md](INSTALL.md)
- For agents: [AGENTS.md](AGENTS.md) and [SKILL.md](SKILL.md); settings for eight harnesses: [harness/README.md](harness/README.md)
- Tests on made-up sample sheets (no real data): `docker compose run --rm test` or `python3 -m unittest discover -s tests -v`

The process reads `.csv` and `.tsv` files and never changes them. It needs no model, and nothing
leaves your computer.
"""


def agents_md(ctx: dict[str, Any]) -> str:
    return f"""# Instructions for agents in this folder

This folder holds one tested process: {ctx['title'].lower()}. {ctx['summary']}

## How to help

{ctx['skill_text']}

## The only commands to run

    python3 run_process.py --input FOLDER --output RESULTS
    python3 -m unittest discover -s tests -v

or, with Docker, `DATA_DIR=FOLDER docker compose run --rm run` and `docker compose run --rm test`.
FOLDER is the folder the person names; RESULTS must be outside it.

## Rules that always apply

- Leave the original files exactly as they are. The process only reads them.
- A person decides every row in flags.csv marked needs_person = yes, including possible duplicates.
- Never reach out to volunteers, and never send the files or the results anywhere.
- Do not edit the code, install packages or fetch anything from the internet.
- Report numbers only from results/report.md.
"""


def skill_md(ctx: dict[str, Any]) -> str:
    return f"""---
name: {ctx['slug']}
description: {ctx['skill_description']}
---

# {ctx['skill_title'][0].upper() + ctx['skill_title'][1:]}

{ctx['skill_text']}

## Run it

From the folder that holds this file:

    python3 run_process.py --input FOLDER --output RESULTS

FOLDER is the folder the person names; RESULTS is a separate folder. Then read RESULTS/report.md and
RESULTS/flags.csv and explain the rows marked needs_person = yes.

## Rules

- Leave the original files exactly as they are.
- A person decides every flagged row, including possible duplicates.
- Never reach out to volunteers, and never send the files or the results anywhere.
- Use only this process's own command; do not install or fetch anything.
"""


def harness_readme(configs: list[dict[str, Any]]) -> str:
    rows = "\n".join(f"| {c['target']} | `{c['path']}` | {c['how']} |" for c in configs)
    return f"""# Agent settings for eight harnesses

One role, compiled by the portable persona compiler from [role.json](role.json), so every harness
gets the same instructions and the same limits: read files, run only this process's own command,
no edits, no web, no reaching out to anyone.

| Harness | File | Note |
|---|---|---|
{rows}

`CLAUDE.md` points Claude Code at `AGENTS.md`; Codex, OpenCode, Cursor, Copilot, Gemini CLI, Roo Code and
Kiro read `AGENTS.md` or their own file above. `.claude/settings.json` and `opencode.json` allow only the
process's commands. Check each harness's own documentation for its current file names; fields a
harness does not know are ignored.

Two harness behaviors to know: Claude Code applies `.claude/settings.json` only after a person trusts
the folder once, and OpenCode looks up its model list on the internet when it starts (offline it
carries on). The process itself never makes a network request.
"""


HARNESS_HOW = {
    "claude_code": "subagent; run with `claude --agent <slug>`",
    "codex": "agent profile; Codex also reads AGENTS.md",
    "opencode": "compiler output (JSON)",
    "opencode_markdown": "the file OpenCode loads; run with `opencode run --agent <slug>`",
    "cursor": "agent file; Cursor also reads AGENTS.md",
    "vscode_copilot": "custom agent for Copilot in VS Code",
    "gemini_cli": "subagent for Gemini CLI",
    "roo_code": "compiler output (one mode)",
    "roo_modes": "the file Roo Code loads (customModes)",
    "kiro": "custom agent for Kiro",
}


def write_code_folder(code: Path, ctx: dict[str, Any], _unused: str | None = None) -> dict[str, Any]:
    if code.exists():
        shutil.rmtree(code)
    code.mkdir(parents=True)
    runner = Path(ctx.get("runner_dir") or RUNNER)  # each process class ships its own tested runner
    docs = ctx.get("docs") or {}  # a class's own wording; the spreadsheet class uses the text below
    shutil.copy2(runner / "run_process.py", code / "run_process.py")
    shutil.copytree(runner / "tests", code / "tests", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(runner / "samples", code / "samples", ignore=shutil.ignore_patterns("__pycache__"))
    write(code / "process.json", jdump(ctx["process_spec"]))
    write(code / "Dockerfile", dockerfile())
    write(code / "compose.yaml", compose_yaml(ctx["pack_id"]))
    write(code / ".dockerignore", "results/\ndata/\n.git/\n**/__pycache__/\n")
    write(code / ".gitignore", "results/\ndata/\n__pycache__/\n")
    write(code / "launch.sh", ctx.get("launch_sh") or LAUNCH_SH)
    write(code / "Makefile", MAKEFILE)
    write(code / "README.md", docs.get("README.md") or code_readme(ctx))
    write(code / "HOWTO.md", docs.get("HOWTO.md") or howto_md(ctx))
    write(code / "INSTALL.md", docs.get("INSTALL.md") or install_md(ctx))
    write(code / "SKILL.md", docs.get("SKILL.md") or skill_md(ctx))
    write(code / ".claude" / "skills" / ctx["slug"] / "SKILL.md", docs.get("SKILL.md") or skill_md(ctx))
    write(code / "AGENTS.md", docs.get("AGENTS.md") or agents_md(ctx))
    write(code / "CLAUDE.md", "@AGENTS.md\n")
    write(code / ".claude" / "settings.json", jdump(claude_settings()))
    write(code / "opencode.json", jdump(opencode_json()))
    role = role_spec(ctx)
    write(code / "harness" / "role.json", jdump(role))
    result = compile_role(role, ctx.get("compiled_swaps"))
    configs = []
    for target, art in sorted(result["compiled"]["artifacts"].items()):
        write(code / art["path"], art["content"])
        configs.append({"target": target, "path": art["path"], "sha256": art["content_sha256"],
                        "warnings": art["warnings"], "how": HARNESS_HOW[target].replace("<slug>", ctx["slug"])})
    for name, art in adapted_configs(role, result["compiled"]).items():
        write(code / art["path"], art["content"])
        configs.append({"target": name, "path": art["path"], "sha256": sha256_bytes(art["content"].encode()),
                        "warnings": [art["why"]], "how": HARNESS_HOW[name].replace("<slug>", ctx["slug"]),
                        "adapted_from": art["adapted_from"]})
    write(code / "harness" / "README.md", (ctx.get("harness_readme") or harness_readme)(configs))
    for name in EXECUTABLE:
        (code / name).chmod(0o755)
    return {"role": role, "lint": result["lint"], "compiled_bundle_sha256": result["compiled"]["bundle_sha256"],
            "targets_compiled": result["compiled"]["targets_compiled"], "configs": configs}


PACK_FILES = ("README.md", "source.json", "nouns.json", "verbs.json", "manifest.json")
_PATHS: dict[tuple[str, str, str], frozenset[str]] = {}


def expected_paths(pack_id: str, slug: str, runner_dir: Path | None = None) -> frozenset[str]:
    """The exact file list (relative to the bundle root) the generator writes for this pack and slug.

    Found by writing the same folder with placeholder text into a temporary folder, so it can never
    drift from what `write_code_folder` really writes. Anything else in a bundle is refused."""
    import tempfile  # noqa: PLC0415

    runner = Path(runner_dir or RUNNER)
    if (pack_id, slug, str(runner)) in _PATHS:
        return _PATHS[(pack_id, slug, str(runner))]
    steps = [{"operation": "write_report", "instruction": "The process writes a short report with the counts."}]
    ctx = {"pack_id": pack_id, "slug": slug, "title": "Placeholder title", "description": "Placeholder description.",
           "summary": "Placeholder summary.", "skill_title": "placeholder process", "skill_text": "Run the process on the folder.",
           "skill_description": "Use when a coordinator asks to clean spreadsheet files in a local folder; reads them without changing them.",
           "howto_text": "The process reads the files.", "howto_credit": "Fixed text.", "steps": steps,
           "process_spec": {"format": "ta-amps.process-spec.v1", "process_id": pack_id, "steps": []},
           "request": {"frequency": None}, "runner_dir": runner}
    with tempfile.TemporaryDirectory(prefix="b4-paths-") as tmp:
        code = Path(tmp) / pack_id / "code"
        write_code_folder(code, ctx)
        files = {f"{pack_id}/{p.relative_to(code.parent).as_posix()}" for p in code.rglob("*") if p.is_file()}
    files |= {f"{pack_id}/{name}" for name in PACK_FILES}
    _PATHS[(pack_id, slug, str(runner))] = frozenset(files)
    return _PATHS[(pack_id, slug, str(runner))]


def bundle(pack_dir: Path, out_path: Path) -> dict[str, Any]:
    """A byte-reproducible tar.gz of the pack folder: sorted entries, fixed times and owners."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        paths = sorted(p for p in pack_dir.rglob("*") if "__pycache__" not in p.parts)
        entries = [pack_dir] + paths
        for path in entries:
            arc = pack_dir.name if path == pack_dir else f"{pack_dir.name}/{path.relative_to(pack_dir).as_posix()}"
            info = tar.gettarinfo(str(path), arcname=arc)
            info.mtime, info.uid, info.gid, info.uname, info.gname = FIXED_MTIME, 0, 0, "", ""
            info.pax_headers = {}
            if info.isdir():
                info.mode = 0o755
                tar.addfile(info)
            else:
                info.mode = 0o755 if path.name in EXECUTABLE else 0o644
                with path.open("rb") as handle:
                    tar.addfile(info, handle)
    raw = buffer.getvalue()
    gz = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=gz, mtime=0, compresslevel=9) as handle:
        handle.write(raw)
    data = gz.getvalue()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return {"path": str(out_path), "sha256": sha256_bytes(data), "bytes": len(data),
            "files": sum(1 for p in paths if p.is_file())}
