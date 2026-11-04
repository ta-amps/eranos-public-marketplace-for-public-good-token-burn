"""The process package as a seed pack in the library's own layout, built and checked offline with the
library's vendored scripts (build_packs.py and validate_packs.py at library commit 1685005).

The pack folder holds exactly README.md, source.json, nouns.json, verbs.json, manifest.json and
code/ (the launchable process), so it drops into `packs/` of the library unchanged.
"""

from __future__ import annotations

import re

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
VENDOR = HERE.parent / "vendor"
LIBRARY = VENDOR / "library"
PERSON_STEP_TEMPLATE = {
    "describes": "what a person did at a step that stays with people, without names or row details",
    "schema": {
        "type": "object", "additionalProperties": False, "required": ["step", "outcome", "by_role", "on"],
        "properties": {
            "step": {"type": "string", "pattern": "^[a-z][a-z0-9-]{1,39}$"},
            "outcome": {"type": "string", "enum": ["done", "changed", "held", "not_needed"]},
            "by_role": {"type": "string", "minLength": 3, "maxLength": 80},
            "on": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
            "notes": {"type": "array", "minItems": 0, "maxItems": 5,
                      "items": {"type": "string", "minLength": 1, "maxLength": 300}},
        },
    },
    "rules": ["by_role names a role, such as coordinator, never a person.",
              "No names, contact details or row values: the record says what happened at the step."],
}
COUNT = {"type": "integer", "minimum": 0, "maximum": 10000000}
RUN_REPORT_TEMPLATE = {
    "describes": "the counts a run of the process produced, with no rows, names or contact details",
    "schema": {
        "type": "object", "additionalProperties": False,
        "required": ["process_id", "files", "rows_in", "rows_out", "duplicates_removed", "flags_for_a_person",
                     "inputs_unchanged", "runner_sha256"],
        "properties": {
            "process_id": {"type": "string", "pattern": "^[a-z][a-z0-9-]{1,40}$"},
            "files": COUNT, "rows_in": COUNT, "rows_out": COUNT, "duplicates_removed": COUNT,
            "flags_for_a_person": COUNT, "changes_recorded": COUNT,
            "inputs_unchanged": {"type": "boolean"},
            "runner_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "summary_written_by": {"type": "string", "enum": ["fixed template", "local model"]},
        },
    },
    "example": {"process_id": "process-sheet-cleaning-example", "files": 4, "rows_in": 23, "rows_out": 19,
                "duplicates_removed": 4, "flags_for_a_person": 11, "changes_recorded": 46,
                "inputs_unchanged": True, "runner_sha256": "0" * 64, "summary_written_by": "fixed template"},
    "rules": ["Counts only. The cleaned rows and flags.csv stay in the results folder on the organization's computer."],
}


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def library_scripts() -> tuple[Any, Any]:
    """The vendored build_packs and validate_packs modules (validate imports build_packs by name)."""
    if str(LIBRARY / "scripts") not in sys.path:
        sys.path.insert(0, str(LIBRARY / "scripts"))
    bp = sys.modules.get("build_packs") or load_module("build_packs", LIBRARY / "scripts" / "build_packs.py")
    vp = sys.modules.get("validate_packs") or load_module("validate_packs", LIBRARY / "scripts" / "validate_packs.py")
    return bp, vp


def without_surface_names(text: str) -> str:
    """A request's own words, with any listed surface or product name replaced: packs carry no brand names."""
    _, vp = library_scripts()
    if not vp.surface_name_in(text):
        return text
    return re.sub(r"[\w-]+", lambda m: "this site" if vp.surface_name_in(m.group(0)) else m.group(0), text)


def source_json(ctx: dict[str, Any]) -> dict[str, Any]:
    """The authored pack source for one process package (deterministic from ctx)."""
    pack_id, title, slug = ctx["pack_id"], ctx["title"], ctx["slug"]
    content = ctx["kit_content"]
    run_verb = f"{pack_id}.run-cleaning-process"
    review_verb = f"{pack_id}.review-flags"
    follow_verb = f"{pack_id}.follow-up-missing-details"
    step_map = [
        {"id": "run-cleaning-process", "title": "Run the cleaning process on the exported sheets",
         "step_kind": "sheet_cleaning", "boundary": "drafts", "actor": "The organization's own agent or a staff member",
         "guidance": "Run the tested process on the folder of exports. It reads the files without changing them and writes cleaned copies, flags.csv and a short report to a separate results folder.",
         "verb": {"$verb": run_verb}},
        {"id": "review-flags", "title": "Decide every flagged row",
         "step_kind": "individual_decision", "boundary": "human_only", "actor": "Volunteer coordinator",
         "guidance": "A person decides every row marked needs_person: possible duplicates, details that disagree, dates or phone numbers the process could not read, and missing contact details.",
         "verb": {"$verb": review_verb}},
        {"id": "follow-up-missing-details", "title": "Decide whether to ask volunteers for missing details",
         "step_kind": "external_send", "boundary": "human_only", "actor": "Volunteer coordinator",
         "guidance": "Only a person decides whether to ask anyone for a missing detail, and does it through the organization's own channels. The agent never reaches out to anyone.",
         "verb": {"$verb": follow_verb}},
    ]
    nouns = [
        {"slug": "pack", "category": "noun.skill_pack", "role": "pack",
         "title": "A collection of Task Objects and Tasks for " + ctx["pack_phrase"],
         "value": {
             "lets_workers": ctx["description"],
             "kit": {"$pin": "kit"},
             "flow": [{"verb": {"$verb": run_verb}, "claimant": "agent", "boundary": "drafts"},
                      {"verb": {"$verb": review_verb}, "claimant": "human", "boundary": "human_only"},
                      {"verb": {"$verb": follow_verb}, "claimant": "human", "boundary": "human_only"}],
             "human_only": ["Decide every flagged row, including possible duplicates.",
                            "Decide whether anyone is asked for missing details."],
             "rules": ["The process runs where the files are: on the organization's own computer or cloud account. No private data leaves it.",
                       "Use only made-up, clearly marked sample data in this pack. Never put a real person's details into the pack.",
                       "Steps marked for a person stay with people. The agent runs the process and explains the flags; it never decides about a person and never reaches out to anyone."],
             "reuse": {"key": ctx["reuse"]["key"], "class": ctx["reuse"]["class"],
                       "operations": ctx["reuse"]["operations"], "rule": "proc1 normalized description signature"},
             "provenance_notes": ctx["provenance_notes"],
         },
         "relations": [["requires_noun", "kit"], ["requires_noun", "procedure"], ["requires_noun", "code"]]},
        {"slug": "kit", "category": "noun.skill_pack", "role": "kit", "title": title,
         "category_reason": "The agent's whole setup as one Task Object: its step map and pins to every part.",
         "value": {"kit_format": "agent-kit.v1", "summary": ctx["summary"], "goal": ctx["goal"],
                   "target_org": ctx["target_org"], "step_map": step_map,
                   "skills": [{"$pin": "skill.process"}], "tools": [{"$pin": "tool.profile-columns"}],
                   "files": [{"$pin": "file.process-spec"}, {"$pin": "file.flags-sheet"}, {"$pin": "file.launch-steps"}],
                   "checklist": {"$pin": "checklist"}, "sources": {"$pin": "sources"}, "test_cases": {"$pin": "test-cases"}},
         "relations": [["derives_from", "request", "built for this request"], ["requires_noun", "skill.process"],
                       ["requires_noun", "tool.profile-columns"], ["requires_noun", "file.process-spec"],
                       ["requires_noun", "checklist"], ["requires_noun", "sources"], ["requires_noun", "code"]]},
        {"slug": "skill.process", "category": "noun.skill_pack", "role": "skill", "title": "Skill: " + ctx["skill_title"],
         "value": {"name": slug, "description": ctx["skill_description"], "boundary": "drafts",
                   "instructions": ctx["skill_text"],
                   "refuses": ["Changing, moving or deleting the original files",
                               "Deciding which of two possible duplicates is the real one",
                               "Reaching out to volunteers or anyone else",
                               "Sending the files or the results anywhere"]}},
        {"slug": "tool.profile-columns", "category": "noun.mcp_server", "role": "tool",
         "title": "Read-only tool card: list the columns and their roles", "value": content["tool"]},
        {"slug": "file.process-spec", "category": "noun.skill_pack", "role": "file", "title": "Process Steps",
         "category_reason": "The step list the tested runner follows belongs to the kit's skill bundle.",
         "value": {"name": "process_steps", "artifact_format": "rule_pack", "boundary": "drafts",
                   "summary": "The steps the runner follows, in order, with the parameters a person can change in process.json.",
                   "spec": [f"{s['operation']}: {s['instruction']}" for s in ctx["steps"]]}},
        {"slug": "file.flags-sheet", "category": "noun.skill_pack", "role": "file", "title": content["files"]["flags"]["title"],
         "category_reason": "A working file the kit produces for people to check.",
         "value": {**{k: v for k, v in content["files"]["flags"].items() if k != "title"}, "boundary": "drafts"}},
        {"slug": "file.launch-steps", "category": "noun.skill_pack", "role": "file", "title": content["files"]["launch"]["title"],
         "category_reason": "The launch steps belong to the kit's skill bundle.",
         "value": {**{k: v for k, v in content["files"]["launch"].items() if k != "title"}, "boundary": "drafts", "spec": ctx["launch_steps"]}},
        {"slug": "procedure", "category": "noun.reflex_procedure", "role": "procedure",
         "title": "Procedure: " + ctx["skill_title"],
         "category_reason": "A compiled procedure: once built, every run uses 0 model tokens.",
         "value": {"spec": ctx["process_spec"], "runs_with": "code/run_process.py",
                   "model_tokens_per_run": 0, "optional_summary": "off by default; your own agent's command can write one from the counts only"},
         "relations": [["requires_noun", "code"]]},
        {"slug": "code", "category": "noun.code_node", "role": "code", "title": "Code: the tested process runner, tests and containers",
         "value": {"code": {"$code": pack_id}, "language": "python", "dependencies": "standard library only",
                   "entry": "code/run_process.py", "tests": "code/tests/test_process.py",
                   "containers": ["code/Dockerfile", "code/compose.yaml"]}},
        {"slug": "checklist", "category": "noun.skill_pack", "role": "checklist",
         "title": "Checklist a person runs with " + ctx["skill_title"], "value": {"items": content["checklist"]}},
        {"slug": "sources", "category": "noun.public_source", "role": "sources",
         "title": "Dated public sources for " + ctx["skill_title"], "value": {"sources": content["sources"]}},
        {"slug": "test-cases", "category": "noun.benchmark_suite", "role": "test_cases",
         "title": "Made-up test cases (no real data) for " + ctx["skill_title"], "value": {"cases": content["cases"]},
         "relations": [["verifies", "kit"]]},
        {"slug": "request", "category": "noun.seed_hypothesis", "role": "request",
         "title": "The request, in the organization's own words",
         "category_reason": "The public request this process was built for frames what it must do.",
         "value": {"says": without_surface_names(ctx["request"]["description"]), "output_type": ctx["request"].get("output_type"),
                   "frequency": ctx["request"].get("frequency"), "request_id": ctx["request"]["id"],
                   "private_information": "none"}},
        {"slug": "template.run-report", "category": "noun.eval_run", "role": "template",
         "title": "Template: the counts from one run, with no rows", "value": RUN_REPORT_TEMPLATE},
        {"slug": "template.person-step-record", "category": "noun.eval_run", "role": "template",
         "title": "Template: a person's record of a step that stays with people", "value": PERSON_STEP_TEMPLATE},
    ]
    verbs = [
        {"slug": "run-cleaning-process", "kind": "verb.solve_draft", "title": step_map[0]["title"], "claimant": "agent",
         "summary": "Run the tested process on a folder of spreadsheet exports on the organization's own computer, and return only the counts.",
         "outcome": "Cleaned copies, flags.csv and a report in the results folder; the produced Task Object holds counts only.",
         "ready_outcome": "sheets_cleaned", "model_use": "none",
         "pinned": ["procedure", "code", "skill.process", "checklist"],
         "params": {
             "input_folder": {"description": "Folder with the .csv or .tsv exports, on the computer that runs the process.",
                              "schema": {"type": "string", "minLength": 1, "maxLength": 400}},
             "results_folder": {"description": "A separate folder for the results, outside the input folder.",
                                "schema": {"type": "string", "minLength": 1, "maxLength": 400}},
             "summary": {"description": "none, or local for a summary paragraph from a model on the same computer.",
                         "schema": {"type": "string", "enum": ["none", "local"]}, "default": "none"}},
         "produces": [{"name": "run_report", "template": "template.run-report"}],
         "steps": ["Run code/run_process.py with the input and results folders, or the compose run service; the input folder is mounted read-only.",
                   "Never change, move or remove the input files; the receipt lists their SHA-256 before and after.",
                   "Return the counts from report.json in the run report; no rows, names or other personal details leave the results folder.",
                   "Explain the flags marked needs_person in plain words and leave every decision to a person."],
         "acceptance": [
             {"id": "matches-template", "check": "The output validates against template.run-report's schema.", "method": "deterministic"},
             {"id": "inputs-unchanged", "check": "receipt.json shows the same SHA-256 for every input file before and after.", "method": "deterministic"},
             {"id": "counts-only", "check": "The produced Task Object holds no names, addresses, phone numbers or row values.", "method": "deterministic"},
             {"id": "tests-pass", "check": "code/tests pass on the made-up sample files before the first real run.", "method": "deterministic"}],
         "network": ["local_only", "No network for the run. The optional summary talks only to a model on the same computer or the compose service on an internal network."],
         "bounds": {"max_elapsed_seconds": 1800}},
        {"slug": "review-flags", "kind": "verb.verify_gate", "title": step_map[1]["title"], "claimant": "human",
         "summary": step_map[1]["guidance"], "outcome": "A step record saying the flagged rows were decided, changed or held.",
         "ready_outcome": "flags_decided", "model_use": "none", "pinned": ["checklist"],
         "params": {"run_report_digest": {"description": "SHA-256 of the run's report.json, so the record names the run it decided.",
                                          "schema": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}},
         "produces": [{"name": "step_record", "template": "template.person-step-record"}],
         "steps": ["Open flags.csv and look at every row marked needs_person.",
                   "Decide each possible duplicate and each disagreement yourself, using the original sheet.",
                   "Record only the outcome and your role, never names or row values."],
         "acceptance": [
             {"id": "matches-template", "check": "The output validates against template.person-step-record's schema.", "method": "deterministic"},
             {"id": "person-submits", "check": "The submitting key belongs to a person in the step's actor role, not to an agent.", "method": "deterministic"}],
         "bounds": {"max_elapsed_seconds": 604800}, "follows": [run_verb]},
        {"slug": "follow-up-missing-details", "kind": "verb.verify_gate", "title": step_map[2]["title"], "claimant": "human",
         "summary": "A person decides whether anyone is asked for a missing detail. The agent never reaches out to anyone.",
         "outcome": "A step record saying whether follow-up was done, held or not needed.",
         "ready_outcome": "follow_up_decided", "model_use": "none", "pinned": ["checklist"],
         "params": {"run_report_digest": {"description": "SHA-256 of the run's report.json.",
                                          "schema": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}},
         "produces": [{"name": "step_record", "template": "template.person-step-record"}],
         "steps": ["Look at the rows flagged missing_contact or missing_required.",
                   "Decide yourself whether anyone needs a follow-up, through the organization's own channels; nothing is done by the agent.",
                   "Record only the outcome and your role."],
         "acceptance": [
             {"id": "matches-template", "check": "The output validates against template.person-step-record's schema.", "method": "deterministic"},
             {"id": "person-submits", "check": "The submitting key belongs to a person in the step's actor role, not to an agent.", "method": "deterministic"}],
         "bounds": {"max_elapsed_seconds": 604800}, "follows": [review_verb]},
    ]
    return {
        "pack_id": pack_id, "title": title, "version": "0.1.0",
        "summary": "A collection of Task Objects and Tasks for " + ctx["pack_phrase"] + ": " + ctx["summary_tail"],
        "dependencies": [],
        "boundaries": ["Use only made-up, clearly marked sample data.", "Steps marked for a person never go to an agent.",
                       "Outputs stay surface_only in the requester's scope.", "Importing the pack writes nothing and enqueues nothing.",
                       "The process runs where the files are; no private data comes to the library or the fabric."],
        "nouns": nouns, "verbs": verbs,
    }


def readme(ctx: dict[str, Any]) -> str:
    lines = [
        f"# {ctx['title']}", "", "## What this pack lets workers do", "",
        f"A collection of Task Objects and Tasks for {ctx['pack_phrase']}: {ctx['summary_tail']}", "",
        ctx["description"], "",
        "## Task Objects", "", "| Task Object | What it holds |", "| --- | --- |",
        "| Kit | The agent's whole setup as one Task Object: the step map and pins to every part below |",
        f"| Skill `{ctx['slug']}` | {ctx['skill_description']} |",
        "| Read-only tool card `profile_sheet_columns` | Lists each column with its role and fill counts, without changing any file. |",
        "| Files | The process steps, the flags sheet layout and the launch steps |",
        "| Procedure | The compiled steps the tested runner follows; every run uses 0 model tokens |",
        "| Code | `code/`: the standard-library runner, its tests, made-up sample files (no real data), containers and agent configs |",
        "| Checklist, sources, test cases | What a person checks, dated public sources, 4 made-up test cases (3 go to a person) |",
        "| Request | The public request this was built for, in its own words, with no private information |",
        "| Templates | The counts-only run report and a person's step record |", "",
        "## Tasks", "", "| Task | Who | What happens |", "| --- | --- | --- |",
        "| `run-cleaning-process` | agent, no model | Run the process on a folder of exports; return counts only |",
        "| `review-flags` | person | Decide every flagged row, including possible duplicates |",
        "| `follow-up-missing-details` | person | Decide whether anyone is asked for a missing detail |", "",
        "Each Task can also end with `no_change`, `unknown` or `blocked`, and can propose the next Task.",
        "Tasks for a person are claimed by people, never by an agent.", "",
        "## How to use it", "",
        "Open `code/` and follow `code/README.md`: one command runs it with Docker (`./launch.sh /path/to/sheets`),",
        "or with Python 3.10 or newer (`python3 run_process.py --input /path/to/sheets --output results`).",
        "Agent settings for eight coding harnesses are in `code/` too. To run it as a Task, fill the",
        f"`{ctx['pack_id']}.run-cleaning-process` template with `scripts/build_packs.py --instantiate` and enqueue it yourself.", "",
        "## Limits", "",
        "- A proposal until a reviewer other than the builder re-runs its tests and approves it.",
        "- The test cases are made up (no real data). Passing them shows the process works on them, not that it fits every sheet.",
        "- It reads .csv and .tsv files; export other formats to CSV first.",
        "- Phone numbers are cleaned for the United States, Canada and the United Kingdom; others need a + and country code.",
        "- Sources were checked on 2026-10-31. Recheck them before relying on them.",
    ]
    return "\n".join(lines) + "\n"


def stage_library(stage: Path, pack_dir: Path) -> Path:
    """A library root holding only the vendored scripts, the contract snapshot and this pack."""
    if stage.exists():
        shutil.rmtree(stage)
    (stage / "packs").mkdir(parents=True)
    shutil.copytree(LIBRARY / "scripts", stage / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(LIBRARY / "packs" / "tessera-contract.json", stage / "packs" / "tessera-contract.json")
    shutil.copytree(pack_dir, stage / "packs" / pack_dir.name, symlinks=True)
    return stage


def build_pack_files(pack_dir: Path) -> dict[str, Any]:
    """Run the library's build on this pack alone and write nouns.json, verbs.json and manifest.json."""
    bp, _ = library_scripts()
    lib = bp.load_library(pack_dir.parent)
    built = bp.build_library(lib)[pack_dir.name]
    for name, data in built.items():
        (pack_dir / name).write_bytes(data)
    (pack_dir / "source.json").write_bytes(bp.dumps(lib.sources[pack_dir.name]))
    return {name: len(data) for name, data in built.items()}


def validate_pack(stage: Path, pack_id: str) -> dict[str, Any]:
    """The library's own record, task, manifest, README and worked-example checks on this pack."""
    bp, vp = library_scripts()
    idx = vp.Index(stage)
    files = idx.docs[pack_id]
    directory = stage / "packs" / pack_id
    present = sorted(p.name for p in directory.iterdir())
    vp.require(present == sorted([*bp.PACK_FILES, bp.CODE_DIR]), f"{pack_id}: pack folder layout {present}")
    for name, data in idx.built[pack_id].items():
        vp.require((directory / name).read_bytes() == data, f"{pack_id}/{name} is stale")
    vp.check_manifest(files["manifest.json"], directory, pack_id)
    vp.check_readme((directory / "README.md").read_text(encoding="utf-8"), idx.lib.sources[pack_id]["title"], pack_id)
    records = files["nouns.json"]["records"]
    for record in records:
        vp.check_record(record, pack_id, idx.contract, idx.targets, idx.values, idx.lib.sources[pack_id]["version"])
    for task in files["verbs.json"]["tasks"]:
        vp.check_task(task, pack_id, idx.contract, idx.pins, idx.targets, idx.templates)
    worked = vp.check_fixtures(records, idx.values)
    return {"passed": True, "nouns": len(records), "verbs": len(files["verbs.json"]["tasks"]), "worked_examples": worked,
            "checks": ["layout", "fresh build", "manifest", "readme", "records", "tasks", "worked examples"],
            "skipped": ["library-wide README totals and the Tessera validation receipt: they cover the whole library and are rerun when the pack is added to it"]}


def instantiate_cli(stage: Path, template_id: str, inputs: dict[str, Any], queue: str) -> dict[str, Any]:
    """Run `scripts/build_packs.py --instantiate` exactly as documented, against the staged library."""
    path = stage / "instantiate-inputs.json"
    path.write_text(json.dumps(inputs, indent=2), encoding="utf-8")
    result = subprocess.run([sys.executable, str(stage / "scripts" / "build_packs.py"), "--instantiate", template_id,
                             "--inputs", str(path), "--queue", queue], capture_output=True, text=True, check=False,
                            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}, timeout=120)
    if result.returncode != 0:
        raise ValueError(f"build_packs --instantiate failed: {result.stderr.strip()[:400]}")
    return json.loads(result.stdout)


def kit_draft(pack_dir: Path, envelope: dict[str, Any], tracks_root: Path) -> dict[str, Any]:
    """The marketplace's kit draft composed from the built pack, the way its seed-pack reader does it:
    every pin is resolved by value SHA-256 and every step must match its verb's title and claimant."""
    bp, _ = library_scripts()
    nouns = json.loads((pack_dir / "nouns.json").read_text(encoding="utf-8"))
    verbs = json.loads((pack_dir / "verbs.json").read_text(encoding="utf-8"))
    records = {(r["store"], r["key"]): r["value"] for r in nouns["records"]}
    templates = {t["brief"]["template_id"]: t["brief"] for t in verbs["tasks"]}

    def value(pin: dict[str, Any], role: str) -> dict[str, Any]:
        found = records[(pin["store"], pin["key"])]
        if bp.value_sha256(found) != pin["value_sha256"] or found.get("role") != role:
            raise ValueError(f"pin {pin['key']} does not resolve to a {role} noun with that digest")
        return found

    kit = next(v for v in records.values() if v.get("role") == "kit")
    steps = []
    for item in kit["step_map"]:
        template = templates[item["verb"]]
        if template["title"] != item["title"] or (item["boundary"] == "human_only") != (template["claimant"] == "human"):
            raise ValueError(f"step {item['id']} does not match its verb template")
        steps.append({k: item[k] for k in ("id", "title", "boundary", "actor", "guidance")} | {"kind": item["step_kind"]})
    sys.path.insert(0, str(VENDOR / "eranos_verify"))
    from eranos.tracks import get_track  # noqa: PLC0415 (vendored, imported on use)

    track = get_track(envelope["track_id"], tracks_root)
    return {
        **envelope, "domain": track.domain, "title": kit_title(records), "summary": kit["summary"],
        "target_org": kit["target_org"], "steps": steps,
        "skills": [{k: value(p, "skill")[k] for k in ("name", "description", "boundary", "instructions", "refuses")} for p in kit["skills"]],
        "tools": [{k: value(p, "tool")[k] for k in ("name", "description", "input_schema", "output_fields", "read_only")} for p in kit["tools"]],
        "artifacts": [{k: value(p, "file")[k] for k in ("name", "title", "artifact_format", "boundary", "summary", "spec")} for p in kit["files"]],
        "checklist": value(kit["checklist"], "checklist")["items"],
        "sources": value(kit["sources"], "sources")["sources"],
        "fixtures": [{k: c[k] for k in ("id", "scenario", "sample_input", "expected_indicators", "expected_human_escalation")}
                     for c in value(kit["test_cases"], "test_cases")["cases"]],
    }


def kit_title(records: dict[tuple[str, str], dict[str, Any]]) -> str:
    return next(v["title"] for v in records.values() if v.get("role") == "kit")
