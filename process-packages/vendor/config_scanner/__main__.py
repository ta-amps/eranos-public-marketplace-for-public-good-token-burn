"""CLI entry point for config_scanner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .scanner import diff_self_editing_memory, scan_repository_configs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="config_scanner", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="Scan a repository directory for agent config supply-chain risks")
    p_scan.add_argument("repo_dir", type=Path)
    p_scan.add_argument(
        "--allow-mcp-commands",
        type=str,
        default="",
        help="Optional comma-separated allowlist of MCP server executables",
    )

    p_diff = sub.add_parser("diff-memory", help="Audit a self-editing persona/memory diff (SOUL.md / MemFS)")
    p_diff.add_argument("before_file", type=Path)
    p_diff.add_argument("after_file", type=Path)

    args = parser.parse_args(argv)
    if args.cmd == "scan":
        allow = {c.strip() for c in args.allow_mcp_commands.split(",") if c.strip()} if args.allow_mcp_commands else None
        report = scan_repository_configs(args.repo_dir, allowlisted_mcp_commands=allow)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["verdict"] == "clean" else 1

    before_txt = args.before_file.read_text(encoding="utf-8")
    after_txt = args.after_file.read_text(encoding="utf-8")
    diff_rep = diff_self_editing_memory(before_txt, after_txt, file_label=args.after_file.name)
    print(json.dumps(diff_rep, indent=2, sort_keys=True))
    return 0 if diff_rep["approved_for_auto_persist"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
