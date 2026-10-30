"""Eranos CLI: inspect public-good tracks, run zero-storage practice verification, verify the two-step
Tessera pipeline on example kits, seed volunteer requests, and export static web snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tessera import TaskSpec

from eranos import config
from eranos.adapter import get_adapter
from eranos.donor_worker import DEFAULT_CHAT_BASE, DEFAULT_DONOR_MODEL, run_donor_demo
from eranos.jsonfile import load_json
from eranos.pipeline import (
    ensure_queues,
    example_paths,
    library_root,
    list_published_kits,
    load_example_bundles,
    resume_steward_signoff,
    run_draft_step,
    run_review_step,
    run_spec_step,
    submit_kit_request,
)
from eranos.pipeline.examples import RUN_SCHEMA, bundle_sha256
from eranos.queues import QUEUE_LABELS, STAGES
from eranos.schemas import KitRequest, ReviewDecision, TaskBrief
from eranos.tracks import load_tracks
from eranos.verifier import practice_verify_kit

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_all_examples(backend: Any, graphs: list[Any] | None = None) -> list[dict[str, Any]]:
    bundles = load_example_bundles()
    results: list[dict[str, Any]] = []
    for idx, bundle in enumerate(bundles, start=1):
        req = KitRequest.model_validate(bundle["request"])
        graph = submit_kit_request(backend, req)
        if graphs is not None:
            graphs.append(graph)
        run_spec_step(backend, worker=f"spec-gate-{idx:02d}", key_id=f"key_spec_{idx:02d}")
        run_draft_step(
            backend,
            bundle["draft"],
            worker=f"volunteer-drafter-{idx:02d}",
            key_id=f"key_drafter_{idx:02d}",
        )
        decision = ReviewDecision.model_validate(bundle["review"])
        first_review = run_review_step(
            backend,
            decision,
            worker=f"volunteer-reviewer-{idx:02d}",
            key_id=f"key_reviewer_{idx:02d}",
        )
        if first_review and first_review.get("status") == "parked":
            steward = bundle["steward_signoff"]
            resume_steward_signoff(
                backend,
                graph.review_task_id,
                by=steward["steward"],
                steward=steward["steward"],
                notes=steward["notes"],
            )
            final_review = run_review_step(
                backend,
                ReviewDecision(
                    kit_id=req.kit_id,
                    verdict="approved",
                    reviewed_by=f"volunteer-reviewer-{idx:02d}",
                    reviewed_by_key=f"key_reviewer_{idx:02d}",
                    notes=decision.notes,
                ),
                worker=f"volunteer-reviewer-{idx:02d}",
                key_id=f"key_reviewer_{idx:02d}",
            )
            if final_review is None or final_review["status"] != "published":
                raise RuntimeError(f"Expected {req.kit_id} to publish after steward sign-off")
            results.append(final_review)
        else:
            if first_review is None or first_review["status"] != "published":
                raise RuntimeError(f"Expected {req.kit_id} to publish on review")
            results.append(first_review)
    return results


# DMI chassis types (SMBIOS 3.x), read only to say honestly what kind of computer ran the examples.
LAPTOP_CHASSIS = frozenset({8, 9, 10, 14, 30, 31, 32})
DESKTOP_CHASSIS = frozenset({3, 4, 5, 6, 7, 13, 15, 16, 24, 35, 36})
WHERE = {"laptop": "a laptop", "desktop": "a desktop computer", "unknown": "a local computer"}


def _machine_class() -> str:
    try:
        chassis = int(Path("/sys/class/dmi/id/chassis_type").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return "unknown"
    if chassis in LAPTOP_CHASSIS:
        return "laptop"
    return "desktop" if chassis in DESKTOP_CHASSIS else "unknown"


def _git_state(path: Path) -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "tree_clean": None}
    return {"commit": commit, "tree_clean": not dirty}


def _task_receipt(backend: Any, task_id: str, workers: dict[str, str]) -> dict[str, Any]:
    results = backend.results(task_id)
    if not results:
        raise RuntimeError(f"example run left no result for {task_id}")
    last = results[-1]
    return {
        "task_id": task_id,
        "worker": workers.get(task_id),
        "key_id": last.completed_by_key,
        "ok": last.ok,
        "receipt_sha256": last.receipt_hash,
        "state_after": str(last.state_after),
        "submitted_at": last.created_at.isoformat()
        if hasattr(last.created_at, "isoformat")
        else str(last.created_at),
    }


def cmd_record_example_runs(out_dir: Path) -> int:
    """Check, build and review every example kit on this store; write one evidence noun per kit."""
    repo = _git_state(REPO_ROOT)
    library = _git_state(library_root())
    machine = _machine_class()
    bundles = load_example_bundles()
    paths = example_paths()
    graphs: list[Any] = []
    backend = get_adapter()
    try:
        results = _run_all_examples(backend, graphs)
        workers: dict[str, str] = {}
        after = 0
        while True:
            events = backend.events(after=after, limit=1000)
            if not events:
                break
            for event in events:
                if event.type == "claimed" and event.task_id and event.worker:
                    workers[event.task_id] = event.worker
            after = events[-1].seq
        records = []
        for path, bundle, graph, final in zip(paths, bundles, graphs, results, strict=True):
            published = final["published"]
            draft_receipt = _task_receipt(backend, graph.draft_task_id, workers)
            draft_output = backend.results(graph.draft_task_id)[-1].output
            review_task = backend.task(graph.review_task_id)
            records.append(
                {
                    "schema": RUN_SCHEMA,
                    "synthetic": True,
                    "kit_id": graph.kit_id,
                    "title": bundle["request"]["title"],
                    "example": {
                        "path": path.relative_to(REPO_ROOT).as_posix(),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    },
                    "inputs_sha256": bundle_sha256(bundle),
                    "seed_pack": bundle.get("seed_pack"),
                    "verbs": [
                        {
                            "verb": "check",
                            "queue": "eq01",
                            **_task_receipt(backend, graph.spec_task_id, workers),
                        },
                        {
                            "verb": "build",
                            "queue": "eq02",
                            **draft_receipt,
                            "draft_sha256": draft_output["blob_sha256"],
                            "verification": {
                                "passed": draft_output["verification"]["passed"],
                                "checks_run": len(draft_output["verification"]["checks_run"]),
                                "fixtures": draft_output["verification"]["fixture_count"],
                                "human_only_steps": draft_output["verification"][
                                    "human_only_steps"
                                ],
                            },
                        },
                        {
                            "verb": "review",
                            "queue": "eq03",
                            **_task_receipt(backend, graph.review_task_id, workers),
                            "parked_for_steward": int(review_task.parks) > 0,
                            "steward_signoff": published.get("steward_signoff"),
                            "publication_sha256": published.get("publication_sha256"),
                        },
                    ],
                    "outcome": final["status"],
                    "catalog_version": published["catalog_version"],
                    "where": WHERE[machine],
                    "data": "synthetic",
                    "summary_label": f"example runs on {WHERE[machine]}, synthetic data",
                    "machine": {
                        "class": machine,
                        "os": platform.system(),
                        "python": platform.python_version(),
                    },
                    "source": {
                        "repository": "eranos-public-marketplace-for-public-good-token-burn",
                        **repo,
                        "seed_pack_library": library,
                    },
                    "store": "local Tessera store in a temporary folder, discarded after the run",
                    "model_calls": 0,
                    "recorded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            )
    finally:
        backend.close()
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.json"):
        stale.unlink()
    for record in records:
        (out_dir / f"{record['kit_id']}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    print(f"recorded {len(records)} example runs in {out_dir} on {WHERE[machine]}")
    return 0


def cmd_tracks() -> int:
    for pack in load_tracks().values():
        print(
            f"{pack.id:34s} [{pack.domain}] ({len(pack.organizations)} org types, "
            f"{len(pack.sources)} sources)"
        )
    return 0


def cmd_practice(kit_path: Path, *, track_id: str | None = None) -> int:
    try:
        payload = load_json(kit_path)
    except (OSError, ValueError) as exc:
        err_out = {
            "passed": False,
            "persisted": False,
            "kit_id": "UNSPECIFIED",
            "spdx_license": "Apache-2.0",
            "issues": [f"failed to load strict JSON from {kit_path}: {exc}"],
            "receipt_sha256": None,
        }
        print(json.dumps(err_out, indent=2))
        return 1
    if not isinstance(payload, dict):
        err_out = {
            "passed": False,
            "persisted": False,
            "kit_id": "UNSPECIFIED",
            "spdx_license": "Apache-2.0",
            "issues": ["practice input JSON root must be an object"],
            "receipt_sha256": None,
        }
        print(json.dumps(err_out, indent=2))
        return 1
    result = practice_verify_kit(payload, track_id=track_id)
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


def cmd_verify_examples(*, dry_run: bool = False) -> int:
    if dry_run:
        bundles = load_example_bundles()
        reports = [practice_verify_kit(b) for b in bundles]
        all_passed = all(r["passed"] for r in reports)
        print(
            json.dumps(
                {
                    "passed": all_passed,
                    "persisted": False,
                    "count": len(reports),
                    "results": reports,
                },
                indent=2,
            )
        )
        return 0 if all_passed else 1

    backend = get_adapter()
    try:
        results = _run_all_examples(backend)
        published = list_published_kits(backend)
    finally:
        backend.close()
    print(f"verified and published {len(published)} kits through eq01 -> eq02 -> eq03:")
    for item in results:
        pub = item["published"]
        steward = f" (steward: {pub['steward_signoff']})" if pub.get("steward_signoff") else ""
        print(
            f"  {pub['kit']['kit_id']}: {pub['kit']['title']} "
            f"[draft={pub['kit']['drafted_by']} != review={pub['reviewed_by']}]{steward}"
        )
    return 0


def cmd_seed_requests() -> int:
    backend = get_adapter()
    try:
        ensure_queues(backend)
        briefs_dir = REPO_ROOT / "briefs"
        count = 0
        for path in sorted(briefs_dir.glob("*.json")):
            brief = TaskBrief.model_validate(json.loads(path.read_text(encoding="utf-8")))
            if brief.owner_type == "human":
                continue
            backend.enqueue(
                TaskSpec(
                    queue="eq02",
                    task_id=f"brief-{brief.task_id}",
                    kind=brief.kind,
                    effect_class="write-internal",
                    brief=brief.model_dump(mode="json"),
                )
            )
            count += 1
    finally:
        backend.close()
    print(f"seeded {count} volunteer agent build tasks into eq02")
    return 0


def cmd_export_snapshot(target: Path) -> int:
    target.mkdir(parents=True, exist_ok=True)
    (target / "catalog").mkdir(parents=True, exist_ok=True)
    backend = get_adapter()
    try:
        _run_all_examples(backend)
        kits = list_published_kits(backend)
        counts = backend.counts()
    finally:
        backend.close()

    tracks_payload = {
        "synthetic": True,
        "tracks": [p.model_dump(mode="json") for p in load_tracks().values()],
    }
    catalog_payload = {
        "synthetic": True,
        "two_step_verified": True,
        "kits": [k.model_dump(mode="json") for k in kits],
    }
    for existing in (target / "catalog").glob("*.json"):
        existing.unlink()
    for kit in kits:
        (target / "catalog" / f"{kit.kit.kit_id}.json").write_text(
            json.dumps({"synthetic": True, **kit.model_dump(mode="json")}, indent=2) + "\n",
            encoding="utf-8",
        )

    briefs = [
        TaskBrief.model_validate(json.loads(p.read_text(encoding="utf-8"))).model_dump(mode="json")
        for p in sorted((REPO_ROOT / "briefs").glob("*.json"))
    ]
    requests_payload = {
        "synthetic": True,
        "stages": [
            {
                "queue": s.queue,
                "node": s.node,
                "title": s.title,
                "effect_class": s.effect_class,
                "purpose": s.purpose,
            }
            for s in STAGES
        ],
        "requests": briefs,
    }
    fabric_payload = {
        "display_name": config.fabric_display_name(),
        "plan": "snapshot",
        "synthetic": True,
        "queues": [
            {"name": name, "label": label, **counts[name].model_dump()}
            for name, label in QUEUE_LABELS
            if name in counts
        ],
    }

    (target / "tracks.json").write_text(
        json.dumps(tracks_payload, indent=2) + "\n", encoding="utf-8"
    )
    (target / "catalog.json").write_text(
        json.dumps(catalog_payload, indent=2) + "\n", encoding="utf-8"
    )
    (target / "requests.json").write_text(
        json.dumps(requests_payload, indent=2) + "\n", encoding="utf-8"
    )
    (target / "fabric.json").write_text(
        json.dumps(fabric_payload, indent=2) + "\n", encoding="utf-8"
    )

    default_snapshot_dir = (REPO_ROOT / "web" / "snapshot").resolve()
    if target.resolve() == default_snapshot_dir:
        public_snapshot = REPO_ROOT / "web" / "public" / "snapshot"
        if public_snapshot.exists():
            shutil.rmtree(public_snapshot)
        public_snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(target, public_snapshot)

    print(f"wrote static snapshot to {target} ({len(kits)} kits)")
    return 0


def cmd_donor_demo(*, live_ollama: bool, model: str, base_url: str) -> int:
    result = run_donor_demo(dry_model=not live_ollama, model=model, base_url=base_url)
    print(json.dumps(result, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eranos", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tracks", help="List the public-good build tracks")
    ver = sub.add_parser(
        "verify-examples", help="Run the two-step Tessera pipeline on example kits"
    )
    ver.add_argument(
        "--dry-run",
        action="store_true",
        help="Run zero-storage in-memory verification across all example kits",
    )
    prac = sub.add_parser(
        "practice",
        help="Run zero-storage deterministic verification on a kit JSON file (persisted: false)",
    )
    prac.add_argument("kit", type=Path, help="Path to kit draft or bundle JSON")
    prac.add_argument("--track-id", default=None, help="Optional explicit track ID")
    prac.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit dry-run flag (practice never persists to storage)",
    )
    sub.add_parser("seed-requests", help="Seed open volunteer agent briefs into eq02")
    donor = sub.add_parser(
        "donor-demo",
        help="Run a two-donor (drafter != reviewer) kit build and review over Tessera HTTP",
    )
    donor.add_argument(
        "--live-ollama",
        action="store_true",
        help="Call live open-weights chat endpoint (OLLAMA_API_KEY) instead of offline dry synthesis",
    )
    donor.add_argument("--model", default=DEFAULT_DONOR_MODEL)
    donor.add_argument("--base-url", default=DEFAULT_CHAT_BASE)
    rec = sub.add_parser(
        "record-example-runs",
        help="Check, build and review every example kit and write one example-run evidence noun per kit",
    )
    rec.add_argument("out", type=Path, default=REPO_ROOT / "examples" / "runs", nargs="?")
    snap = sub.add_parser(
        "export-snapshot", help="Write static snapshot JSON files for the web app"
    )
    snap.add_argument("out", type=Path, default=Path("web/snapshot"), nargs="?")

    args = parser.parse_args(argv)
    if args.cmd == "tracks":
        return cmd_tracks()
    if args.cmd == "verify-examples":
        return cmd_verify_examples(dry_run=bool(args.dry_run))
    if args.cmd == "practice":
        return cmd_practice(args.kit, track_id=args.track_id)
    if args.cmd == "seed-requests":
        return cmd_seed_requests()
    if args.cmd == "donor-demo":
        return cmd_donor_demo(
            live_ollama=bool(args.live_ollama),
            model=str(args.model),
            base_url=str(args.base_url),
        )
    if args.cmd == "record-example-runs":
        return cmd_record_example_runs(args.out)
    if args.cmd == "export-snapshot":
        return cmd_export_snapshot(args.out)
    return 1


if __name__ == "__main__":
    sys.exit(main())
