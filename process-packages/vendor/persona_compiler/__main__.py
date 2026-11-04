"""CLI entry point for persona_compiler."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .compiler import (
    SUPPORTED_HARNESS_TARGETS,
    compile_portable_role,
    score_delegation_description,
    strip_degrading_fluff,
    verify_permission_separation,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="persona_compiler", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_lint = sub.add_parser("lint", help="Lint a portable role JSON spec for fluff, description quality, and permission leaks")
    p_lint.add_argument("spec_json", type=Path)

    p_comp = sub.add_parser("compile", help="Compile a portable role JSON spec across target harnesses")
    p_comp.add_argument("spec_json", type=Path)
    p_comp.add_argument(
        "--targets",
        type=str,
        default=",".join(SUPPORTED_HARNESS_TARGETS),
        help="Comma-separated harness targets",
    )

    args = parser.parse_args(argv)
    spec = json.loads(args.spec_json.read_text(encoding="utf-8"))

    if args.cmd == "lint":
        report = {
            "slug": spec.get("slug"),
            "delegation_description_audit": score_delegation_description(str(spec.get("description") or "")),
            "fluff_stripping": strip_degrading_fluff(str(spec.get("instructions") or "")),
            "permission_separation": verify_permission_separation(spec),
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["permission_separation"]["separated"] else 1

    target_list = [t.strip() for t in args.targets.split(",") if t.strip()]
    compiled = compile_portable_role(spec, targets=target_list)
    print(json.dumps(compiled, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
