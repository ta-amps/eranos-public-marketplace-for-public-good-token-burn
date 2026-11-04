#!/usr/bin/env python3
"""Build one process package from a request file: python3 scripts/build.py requests/first-process.json [--no-docker]"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from process_packages import build_process  # noqa: E402

spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
result = build_process(spec["request"], spec["plan_part"], run_docker="--no-docker" not in sys.argv,
                       builder={"id": "local-builder-b4", "key_id": "local-builder-b4-key"})
r = result["test_report"]
print(json.dumps({"bundle_path": result["bundle_path"], "bundle_sha256": result["bundle_sha256"], "passed": r["passed"],
                  "failures": r["failures"], "reuse_key": result["reuse"]["key"], "model_calls": r["model_calls"],
                  "checks": {k: v.get("passed") for k, v in r["checks"].items()}}, indent=2))
