#!/usr/bin/env python3
"""Prepare (default) or perform (--execute) the go-live writes for one reviewed process package.

    python3 scripts/golive.py prepare --build out/<pack>.build.json --review out/<pack>.review.json
    python3 scripts/golive.py execute --build ... --review ... --step bucket|records|herma-records|herma-sync

`prepare` writes every request body to golive/<pack>/ and the exact commands to golive/<pack>/COMMANDS.md;
it sends nothing. `execute` sends one step at a time and needs the owner's approvals (hosted writes;
Herma admin for the sync). Keys are read from 0600 env files named by TESSERA_KEY_FILE and
HERMA_ADMIN_KEY_FILE (lines NAME=value); they are never printed, logged or written anywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from process_packages.handler import BUCKET, finalize_catalog_record  # noqa: E402

TESSERA_URL = os.environ.get("TESSERA_URL", "")
HERMA_URL = os.environ.get("HERMA_URL", "")
if not TESSERA_URL or not HERMA_URL:
    raise SystemExit("set TESSERA_URL and HERMA_URL: your key goes only to the addresses you name")
HERMA_NAMESPACE = "herma.provisions.process-packages"
FILM_PROMPT = ("Say someone asks for a data-cleaning pipeline. It becomes one verb, and the agent holding it splits it up. "
               "Workers anywhere claim the pieces.")


def jdump(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def read_key(env_name: str, var: str) -> str:
    path = Path(os.environ.get(env_name, ""))
    if not path.is_file():
        raise SystemExit(f"{env_name} must name a 0600 env file")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise SystemExit(f"{env_name} is readable by others; chmod 600 it first")
    for line in path.read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        if name.strip() == var and value.strip():
            return value.strip().strip('"')
    raise SystemExit(f"{var} is not in the file named by {env_name}")


def herma_payloads(build: dict[str, Any], catalog_key: str, template_store: str = "eranos.process_templates",
                   template_key: str | None = None) -> dict[str, Any]:
    report, solution = build["test_report"], build["solution_record"]
    pack_id, sha = report["pack_id"], build["test_report"]["bundle"]["sha256"]
    template_key = template_key or pack_id
    refs = [f"noun:eranos.catalog/{catalog_key}", f"verb:{template_store}/{template_key}"]
    entries = [
        {"entry_id": refs[0], "kind": "noun", "title": solution["value"]["title"],
         "summary": "Reviewed catalog entry for a tested data-cleaning pipeline that a nonprofit runs on its own computer.",
         "schema_or_body": {"store": "eranos.catalog", "key": catalog_key, "bundle_sha256": sha},
         "source_uri": f"{TESSERA_URL}/v1/stores/eranos.catalog/records/{catalog_key}", "updated_at": report["finished_at"]},
        {"entry_id": refs[1], "kind": "verb", "title": "Run the cleaning process (Task)",
         "summary": "Runs the tested process on a folder of spreadsheet exports where the files are; returns counts only; 0 model tokens.",
         "schema_or_body": {"store": template_store, "key": template_key,
                            "command": "python3 run_process.py --input FOLDER --output RESULTS"},
         "source_uri": f"{TESSERA_URL}/v1/stores/{template_store}/records/{template_key}", "updated_at": report["finished_at"]},
    ]
    provision = {
        "prov_id": "PROV-DATA-CLEANING-PIPELINE",
        "title": "Data-cleaning pipeline for volunteer sign-up spreadsheets (reviewed Task Object)",
        "summary": "Points any agent asked for a data-cleaning pipeline at the reviewed, tested process package, so it reuses it instead of building one.",
        "priority": 280, "enabled": True, "action": "shim_context", "context_refs": refs,
        "inject_position": "system_prefix", "dedupe_mode": "once_per_conversation", "max_chars": 1600,
        "inject_text": (f"A reviewed, tested data-cleaning pipeline already exists as a Task Object: {pack_id} (catalog {catalog_key}). "
                        "It removes duplicates, puts dates and phone numbers in one format, flags missing contact details for a "
                        "person, and writes a short report. It runs where the files are (Docker or Python 3.10+), with 0 model "
                        f"tokens per run; no private data leaves the organization. Bundle SHA-256 {sha}. Reuse it rather than "
                        f"building a new one: reuse key {report['reuse']['key']}."),
        "uris": [{"uri": f"urn:ta-amps:process-package:{pack_id}", "label": "Data-cleaning pipeline package", "kind": "doc",
                  "inline_excerpt": "Task Object plus a runnable Task; configs for eight agent harnesses; Docker Compose; tests on made-up sample files."}],
        "metadata_tags": {"domain": "data-cleaning",
                          "fabric_governance": json.dumps({"allowed_surfaces": ["surface:herma", "surface:eranos"], "namespace": "main",
                                                           "producer_surface": "surface:eranos", "tags": ["status:verified"],
                                                           "target_cohorts": ["all"], "visibility_scope": "public_commons"},
                                                          sort_keys=True, separators=(",", ":"))},
        "triggers": {"mode": "any",
                     "keyword": {"any_keywords": ["data-cleaning pipeline", "data cleaning pipeline", "data-cleaning", "data cleaning",
                                                  "clean our volunteer", "clean volunteer sign-up", "spreadsheet cleaning",
                                                  "clean spreadsheets", "remove duplicates", "fix date formats", "fix phone formats",
                                                  "flag missing contact"],
                                 "path_globs": ["*signup*.csv", "*sign-up*.csv", "*volunteer*.csv"]},
                     "semantic": {"exemplars": [FILM_PROMPT, build["solution_record"]["value"]["summary"],
                                                "a reusable process to clean our volunteer sign-up spreadsheets: remove duplicates, fix date and phone formats"],
                                  "concepts": ["data-cleaning", "pipeline", "spreadsheet", "duplicates", "dates", "phone"],
                                  "threshold": 0.26}},
    }
    return {"entries": entries, "index": {"entry_ids": refs}, "provision": provision}


def record_body(rec: dict[str, Any]) -> dict[str, Any]:
    return {k: rec[k] for k in ("value", "expected_version", "producer_surface", "visibility_scope", "allowed_surfaces",
                                "target_cohorts", "tags") if k in rec}


def prepare(build_path: Path, review_path: Path) -> Path:
    build = json.loads(build_path.read_text(encoding="utf-8"))
    review = json.loads(review_path.read_text(encoding="utf-8"))
    report = build["test_report"]
    if review["verdict"] != "approved":
        raise SystemExit("the review did not approve this package; nothing to prepare")
    pack_id = report["pack_id"]
    out = ROOT / "golive" / pack_id
    out.mkdir(parents=True, exist_ok=True)
    catalog = finalize_catalog_record(build["catalog_record"], review)
    template, solution = build["task_template_record"], dict(build["solution_record"])
    solution = json.loads(json.dumps(solution))
    solution["visibility_scope"] = "public_commons"
    solution["allowed_surfaces"] = ["surface:eranos", "surface:herma"]
    solution["tags"] = [t for t in solution["tags"] if t != "status:quarantined"] + ["status:verified"]
    solution["value"]["review"] = {"reviewed_by": review["reviewed_by"], "review_sha256": review["review_sha256"],
                                   "verdict": review["verdict"]}
    solution["value"]["bundle"]["url"] = f"{TESSERA_URL}/v1/buckets/{BUCKET}/objects/{pack_id}.tar.gz"
    herma = herma_payloads(build, catalog["key"], template["store"])
    files = {
        "bucket-define.json": {"name": BUCKET, "description": "Reviewed process packages (Task Objects) that nonprofits run themselves.",
                               "producer_surface": "surface:eranos", "visibility_scope": "public_commons",
                               "allowed_surfaces": ["surface:eranos", "surface:herma"]},
        "bucket-object-governance.json": {"producer_surface": "surface:eranos", "visibility_scope": "public_commons",
                                          "allowed_surfaces": ["surface:eranos", "surface:herma"],
                                          "tags": ["kind:process_package", f"package:{pack_id}", f"reuse:{report['reuse']['key']}"],
                                          "sha256": report["bundle"]["sha256"], "size": report["bundle"]["bytes"]},
        "catalog-record.json": catalog,
        "task-template-record.json": template,
        "solution-record.json": solution,
        "herma-context-entries.json": herma["entries"],
        "herma-context-index.json": herma["index"],
        "herma-provision.json": herma["provision"],
        "herma-sync-body.template.json": {"base_url": TESSERA_URL, "bearer_token": "<read from TESSERA_KEY_FILE at send time>",
                                          "namespace": HERMA_NAMESPACE, "builtin": True},
        "herma-preview-check.json": {"wire_format": "chat_completions", "messages": [{"role": "user", "content": FILM_PROMPT}]},
    }
    for name, value in files.items():
        (out / name).write_text(jdump(value), encoding="utf-8")
    return out


def herma_prepare(build_path: Path, catalog_key: str | None, template_key: str | None = None) -> Path:
    """Herma's payloads alone, for a package the worker loop built, reviewed and published (B1 writes
    the blob and the catalog and template records itself; only the provision sync is left)."""
    build = json.loads(build_path.read_text(encoding="utf-8"))
    pack_id = build["test_report"]["pack_id"]
    out = ROOT / "golive" / pack_id
    out.mkdir(parents=True, exist_ok=True)
    herma = herma_payloads(build, catalog_key or build["catalog_record"]["key"], template_key=template_key)
    files = {"herma-context-entries.json": herma["entries"], "herma-context-index.json": herma["index"],
             "herma-provision.json": herma["provision"],
             "herma-sync-body.template.json": {"base_url": TESSERA_URL, "bearer_token": "<read from TESSERA_KEY_FILE at send time>",
                                               "namespace": HERMA_NAMESPACE, "builtin": True},
             "herma-preview-check.json": {"wire_format": "chat_completions", "messages": [{"role": "user", "content": FILM_PROMPT}]}}
    for name, value in files.items():
        (out / name).write_text(jdump(value), encoding="utf-8")
    return out


def send(method: str, url: str, key: str | None, body: bytes | None, headers: dict[str, str]) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, method=method, headers={**headers, **({"authorization": f"Bearer {key}"} if key else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            return resp.status, resp.read().decode("utf-8", "replace")[:600]
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:600]


def execute(build_path: Path, step: str) -> None:
    build = json.loads(build_path.read_text(encoding="utf-8"))
    pack_id = build["test_report"]["pack_id"]
    out = ROOT / "golive" / pack_id
    load = lambda name: json.loads((out / name).read_text(encoding="utf-8"))  # noqa: E731
    receipts = out / "receipts.jsonl"
    results = []
    if step == "bucket":
        key = read_key("TESSERA_KEY_FILE", "TESSERA_KEY")
        results.append(("define", *send("POST", f"{TESSERA_URL}/v1/buckets/define", key,
                                        json.dumps(load("bucket-define.json")).encode(), {"content-type": "application/json"})))
        data = Path(build["test_report"]["bundle"]["path"]).read_bytes()
        results.append(("upload", *send("POST", f"{TESSERA_URL}/v1/buckets/{BUCKET}/objects/{pack_id}.tar.gz?expected_version=0", key,
                                        data, {"content-type": "application/gzip",
                                               "x-tessera-governance": json.dumps(load("bucket-object-governance.json"))})))
    elif step == "records":
        key = read_key("TESSERA_KEY_FILE", "TESSERA_KEY")
        for name in ("solution-record.json", "task-template-record.json", "catalog-record.json"):
            rec = load(name)
            results.append((name, *send("POST", f"{TESSERA_URL}/v1/stores/{rec['store']}/records/{rec['key']}", key,
                                        json.dumps(record_body(rec)).encode(), {"content-type": "application/json"})))
    elif step == "herma-records":
        key = read_key("TESSERA_KEY_FILE", "TESSERA_KEY")
        gov = {"producer_surface": "surface:herma", "visibility_scope": "public_commons", "expected_version": 0}
        for entry in load("herma-context-entries.json"):
            results.append((entry["entry_id"], *send("POST", f"{TESSERA_URL}/v1/stores/{HERMA_NAMESPACE}.context/records/"
                                                     + urllib.request.quote(entry["entry_id"], safe=""), key,
                                                     json.dumps({**gov, "value": entry}).encode(), {"content-type": "application/json"})))
        results.append(("context index", *send("POST", f"{TESSERA_URL}/v1/stores/{HERMA_NAMESPACE}.context/records/index", key,
                                               json.dumps({**gov, "value": load("herma-context-index.json")}).encode(),
                                               {"content-type": "application/json"})))
        prov = load("herma-provision.json")
        results.append((prov["prov_id"], *send("POST", f"{TESSERA_URL}/v1/stores/{HERMA_NAMESPACE}/records/{prov['prov_id']}", key,
                                               json.dumps({**gov, "value": prov}).encode(), {"content-type": "application/json"})))
    elif step == "herma-sync":
        admin = read_key("HERMA_ADMIN_KEY_FILE", "HERMA_ADMIN_KEY")
        reader = read_key("TESSERA_KEY_FILE", "TESSERA_KEY")
        body = {**load("herma-sync-body.template.json"), "bearer_token": reader}
        results.append(("sync", *send("POST", f"{HERMA_URL}/v1/sync/tessera", admin, json.dumps(body).encode(),
                                      {"content-type": "application/json"})))
        results.append(("preview", *send("POST", f"{HERMA_URL}/api/preview", None, json.dumps(load("herma-preview-check.json")).encode(),
                                         {"content-type": "application/json"})))
    else:
        raise SystemExit(f"unknown step {step}")
    with receipts.open("a", encoding="utf-8") as fh:
        for name, status, text in results:
            fh.write(json.dumps({"step": step, "item": name, "status": status, "response_head": text[:300]}) + "\n")
            print(f"{step}: {name}: HTTP {status}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=("prepare", "herma-prepare", "execute"))
    parser.add_argument("--catalog-key")
    parser.add_argument("--template-key", help="the live template record key, <request id>.<part>.<pack id>")
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--step", choices=("bucket", "records", "herma-records", "herma-sync"))
    args = parser.parse_args()
    if args.action == "herma-prepare":
        print(f"prepared: {herma_prepare(args.build, args.catalog_key, args.template_key)}")
        return 0
    if args.action == "prepare":
        if not args.review:
            parser.error("prepare needs --review")
        print(f"prepared: {prepare(args.build, args.review)}")
    else:
        if not args.step:
            parser.error("execute needs --step")
        execute(args.build, args.step)
    return 0


if __name__ == "__main__":
    sys.exit(main())
