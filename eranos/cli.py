"""Eranos CLI: inspect public-good tracks, run zero-storage practice verification, verify the two-step
Tessera pipeline on example kits, seed volunteer requests, and export static web snapshots."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from tessera import TaskSpec

from eranos import config
from eranos.adapter import get_adapter
from eranos.donor_worker import DEFAULT_CHAT_BASE, DEFAULT_DONOR_MODEL, run_donor_demo
from eranos.jsonfile import load_json
from eranos.pipeline import (
    ensure_queues,
    list_published_kits,
    load_example_bundles,
    resume_steward_signoff,
    run_draft_step,
    run_review_step,
    run_spec_step,
    submit_kit_request,
)
from eranos.queues import QUEUE_LABELS, STAGES
from eranos.schemas import KitRequest, ReviewDecision, TaskBrief
from eranos.tracks import load_tracks
from eranos.verifier import practice_verify_kit

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_all_examples(backend: Any) -> list[dict[str, Any]]:
    bundles = load_example_bundles()
    results: list[dict[str, Any]] = []
    for idx, bundle in enumerate(bundles, start=1):
        req = KitRequest.model_validate(bundle["request"])
        graph = submit_kit_request(backend, req)
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
    sub.add_parser("tracks", help="List the six public-good build tracks")
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
    if args.cmd == "export-snapshot":
        return cmd_export_snapshot(args.out)
    return 1


if __name__ == "__main__":
    sys.exit(main())
