"""Unit tests for persona_compiler."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from persona_compiler import (
    SUPPORTED_HARNESS_TARGETS,
    compile_portable_role,
    score_delegation_description,
    strip_degrading_fluff,
    verify_permission_separation,
)


def _sample_spec() -> dict:
    return {
        "slug": "schema-diff-auditor",
        "title": "Schema Diff Auditor",
        "description": (
            "Use when auditing JSON schema and SQL migration diffs for breaking field removals; "
            "operates read-only on local files without modifying code."
        ),
        "instructions": (
            "You are a world-class PhD-level architect with 20 years of experience. "
            "You are a 38-year-old woman born and raised in Austin. "
            "In your spare time you love jazz and drinking espresso. "
            "Inspect each modified schema file and emit a JSON array of breaking field changes with file and line numbers."
        ),
        "allowed_capabilities": ["read"],
        "allowed_tools": ["Read", "Grep", "Glob"],
        "disallowed_tools": ["Bash", "Write", "Edit"],
        "max_turns": 6,
        "drift_checkpoint_rounds": 12,
    }


class PersonaCompilerTests(unittest.TestCase):
    def test_strips_expert_demographic_and_backstory_fluff_preserving_contract(self) -> None:
        res = strip_degrading_fluff(_sample_spec()["instructions"])
        self.assertEqual(res["removed_count"], 3)
        self.assertIn("expert_fluff", res["categories_flagged"])
        self.assertIn("demographic_attributes", res["categories_flagged"])
        self.assertIn("irrelevant_backstory", res["categories_flagged"])
        self.assertIn("Inspect each modified schema file", res["cleaned_instructions"])
        self.assertNotIn("espresso", res["cleaned_instructions"])

    def test_delegation_description_scoring_rewards_trigger_artifact_and_boundary(self) -> None:
        good = score_delegation_description(_sample_spec()["description"])
        self.assertEqual(good["score"], 1.0)
        vague = score_delegation_description("A legendary 10x ninja helper.")
        self.assertLess(vague["score"], 0.3)
        self.assertTrue(vague["contains_fluff"])

    def test_permission_separation_blocks_undeclared_shell_or_escalation_prose(self) -> None:
        bad = _sample_spec()
        bad["instructions"] = "Inspect files and run bash commands to overwrite repository files."
        sep = verify_permission_separation(bad)
        self.assertFalse(sep["separated"])
        leaked_caps = {x["capability"] for x in sep["permission_leaks"]}
        self.assertIn("shell", leaked_caps)
        self.assertIn("write", leaked_caps)
        with self.assertRaises(ValueError):
            compile_portable_role(bad)

    def test_compiles_all_eight_supported_harnesses_with_clamped_8_round_checkpoint(self) -> None:
        out = compile_portable_role(_sample_spec())
        self.assertEqual(out["targets_compiled"], len(SUPPORTED_HARNESS_TARGETS))
        self.assertEqual(out["drift_checkpoint_rounds"], 8)
        self.assertIn(".claude/agents/schema-diff-auditor.md", out["artifacts"]["claude_code"]["path"])
        self.assertIn("developer_instructions", out["artifacts"]["codex"]["content"])
        self.assertTrue(out["artifacts"]["codex"]["warnings"])
        opencode_cfg = json.loads(out["artifacts"]["opencode"]["content"])
        self.assertEqual(opencode_cfg["permission"]["bash"], "deny")
        self.assertEqual(opencode_cfg["permission"]["edit"], "deny")

    def test_novice_persona_framing_stripped(self) -> None:
        res = strip_degrading_fluff(
            "Act as a confused beginner who knows little Python. Return exact AST node counts."
        )
        self.assertIn("novice_framing", res["categories_flagged"])
        self.assertEqual(res["cleaned_instructions"], "Return exact AST node counts.")

    def test_invalid_slug_rejected(self) -> None:
        bad = _sample_spec()
        bad["slug"] = "../escape"
        with self.assertRaises(ValueError):
            compile_portable_role(bad)

    def test_cli_compile_determinism(self) -> None:
        code_dir = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "spec.json"
            spath.write_text(json.dumps(_sample_spec()), encoding="utf-8")
            r1 = subprocess.run(
                [sys.executable, "-m", "persona_compiler", "compile", str(spath), "--targets", "claude_code,codex,opencode"],
                cwd=code_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            r2 = subprocess.run(
                [sys.executable, "-m", "persona_compiler", "compile", str(spath), "--targets", "claude_code,codex,opencode"],
                cwd=code_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(r1.stdout, r2.stdout)
            parsed = json.loads(r1.stdout)
            self.assertEqual(parsed["targets_compiled"], 3)


if __name__ == "__main__":
    unittest.main()
