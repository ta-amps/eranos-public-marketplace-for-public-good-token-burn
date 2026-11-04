#!/usr/bin/env python3
"""Independent review of a built package (run by a worker other than the builder):

    python3 scripts/review.py --build out/<pack>.build.json --reviewer-id ID --reviewer-key-id KEYID

Re-checks the bundle SHA-256 against the build and the catalog record and re-runs
`docker compose run --rm test` from a new empty folder. Refuses when the reviewer is the builder.
Writes out/<pack>.review.json. Sends nothing anywhere."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from process_packages import SelfReviewRefused, review_package  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--build", type=Path, required=True)
parser.add_argument("--reviewer-id", required=True)
parser.add_argument("--reviewer-key-id", required=True)
parser.add_argument("--no-docker", action="store_true")
args = parser.parse_args()
build = json.loads(args.build.read_text(encoding="utf-8"))
build["bundle_sha256"] = build["test_report"]["bundle"]["sha256"]
try:
    review = review_package(Path(build["test_report"]["bundle"]["path"]), build,
                            {"id": args.reviewer_id, "key_id": args.reviewer_key_id}, run_docker=not args.no_docker)
except SelfReviewRefused as exc:
    print(f"refused: {exc}", file=sys.stderr)
    sys.exit(3)
out = args.build.with_name(build["test_report"]["pack_id"] + ".review.json")
out.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"verdict": review["verdict"], "review_sha256": review["review_sha256"], "written": str(out)}))
