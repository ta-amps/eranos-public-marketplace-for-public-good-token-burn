#!/usr/bin/env python3
"""Build seed-pack payloads from authored sources, offline and byte-for-byte reproducibly.

    python3 scripts/build_packs.py           # rewrite packs/<pack>/{nouns,verbs,manifest}.json
    python3 scripts/build_packs.py --check   # fail if the committed files differ from a fresh build
    python3 scripts/build_packs.py --instantiate TEMPLATE_ID --inputs inputs.json

Each pack is authored in packs/<pack>/source.json. The build turns it into Tessera
RecordWrite bodies (nouns), TaskSpec templates (verbs) and a proposal manifest.
A pack may also ship tested code as nouns in packs/<pack>/code/; the build only
hashes those files, never runs or imports them, and pins them in the manifest.
It reads local files only. It never calls a service or model, never enqueues or
writes to a fabric and never activates anything. `--instantiate` prints one filled
TaskSpec for review; enqueueing it remains an explicit act with your own grants.
"""

from __future__ import annotations

import argparse
import copy
import fnmatch
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packs"
GENERATED = ("nouns.json", "verbs.json", "manifest.json")
PACK_FILES = ("README.md", "source.json", *GENERATED)
# Optional tested code shipped as nouns. Hashed and pinned, never run by the build or validators.
CODE_DIR = "code"
CODE_SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
                  ".tox", ".hypothesis", "node_modules", "build", "dist", "test-results"}
CODE_SKIP_SUFFIXES = {".pyc", ".pyo"}
CODE_RUNS = (
    "The library runs this code only in its own CI tests; workers run it under their own "
    "permissions. Reading, exporting or importing the pack runs none of it."
)
MAX_EXACT = 2**53

MANIFEST_FORMAT = "ta-amps.seed-pack.proposal.v1"
NOUNS_FORMAT = "ta-amps.seed-pack.nouns.v1"
VERBS_FORMAT = "ta-amps.seed-pack.verbs.v1"
VERB_CONTRACT = "ta-amps.seed-verb-template.v1"
QUEUE_PLACEHOLDER = "conformance-seed-packs"
PRODUCER = "surface:tessera"

NAME_PATTERN = r"^[a-z0-9][a-z0-9_.-]{0,63}$"
KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$"
DIGEST_PATTERN = r"^[0-9a-f]{64}$"
PACK_ID = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9.-]{0,100}$")
SLOT = re.compile(r"^[a-z][a-z0-9_]{0,40}$")

# Packs are shared inside one team surface: Tessera records the importing key's own surface as the
# producer, and surface_only makes items readable, claimable and updatable only by keys on that surface.
GOVERNANCE = {
    "producer_surface": PRODUCER,
    "visibility_scope": "surface_only",
    "allowed_surfaces": [],
    "target_cohorts": ["all"],
}
FLOOR_DIMENSIONS = {
    "determinism": 0.0,
    "evidence_grounding": 0.0,
    "token_efficiency": 0.0,
    "safety_compliance": 0.0,
    "verification_tier": "unverified",
}
DIMENSION_BASIS = {
    "measured": False,
    "method": "unmeasured_floor",
    "reason": (
        "Tessera requires these axes, so each is set to its lowest value and the tier is "
        "unverified. No quality is claimed. Replace them only with measured values and the "
        "evidence that produced them."
    ),
}
PROVENANCE = {
    "source": "original ta-amps authored proposal",
    "license": "MIT",
    "generator": "scripts/build_packs.py",
    "independently_verified": False,
}
STANDARD_OUTCOMES = ("no_change", "unknown", "blocked")
OUTCOME_MEANINGS = {
    "no_change": "The evidence does not justify producing or changing anything. Say why.",
    "unknown": "The question could not be answered with the permitted inputs. List what is missing and what would resolve it.",
    "blocked": "A required input, permission or capability is missing. Ask one precise question.",
}
CLAIMANTS = {"agent", "human", "agent_or_human"}
NETWORK_MODES = {"none", "read_only", "local_only", "sandbox_packages", "assigned_tessera", "provider_destination"}
# Value fields Tessera's store turns into stored tags (extract_payload_tags); packs never set them.
TAGGING_FIELDS = {"tags", "metadata_tags", "domain", "surface", "stage", "kind", "category", "area", "track"}
MODEL_USE = {"worker_allowance", "none"}
REVIEW_RULES = {"owning_policy", "distinct_reviewer"}
INFERENCE_ALLOWANCE = (
    "Existing authorized worker allowance only. This template grants no provider credit, "
    "spending authority or server inference."
)

NOUN_REF_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["store", "key", "version", "value_sha256"],
    "properties": {
        "store": {"type": "string", "pattern": NAME_PATTERN},
        "key": {"type": "string", "pattern": KEY_PATTERN},
        "version": {"type": "integer", "minimum": 1},
        "value_sha256": {"type": "string", "pattern": DIGEST_PATTERN},
    },
}
TEXT_LIST = {"type": "array", "maxItems": 8, "items": {"type": "string", "minLength": 1, "maxLength": 500}}
RUN_NOTES_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "went_right": TEXT_LIST,
        "went_wrong": TEXT_LIST,
        "next_steps": TEXT_LIST,
        "ideas": TEXT_LIST,
    },
}
PACK_PHRASE = "A collection of nouns and verbs for "
# The owner's public vocabulary (Nov 1): Task Objects and Tasks. Accepted next to the library's phrase.
PACK_PHRASES = (PACK_PHRASE, "A collection of Task Objects and Tasks for ")
FOLLOW_UP_STEP = (
    "Return follow-up work the results justify as proposed_verbs and nouns worth creating later as "
    "proposed_nouns. Never enqueue them yourself; an authorized requester decides which to run."
)
CREATES = {
    "nouns": "The worker writes the nouns listed in output_contract.produces and returns their pins.",
    "verbs": (
        "The worker proposes follow-up verbs in output.proposed_verbs, such as a breakdown into smaller "
        "verbs or a research follow-up, with the pins they need. Proposals are never enqueued by the "
        "worker; an authorized requester enqueues the ones worth doing."
    ),
}
REPORT_FILL_RULES = [
    "Copy contract.input_schema and contract.output_schema unchanged, so every run of this template shares one shape fingerprint.",
    "Add context_hash, environment_hash and toolchain_hash as lowercase SHA-256 digests when known; all five contract fields together allow exact matching.",
    "Name the exact harness version, provider and model. Deterministic or human work records the model name as none.",
    "Put what went wrong in an error block and in output.run_notes.went_wrong. The version-1 report has no fields for what went right, next steps or ideas, so those go in output.run_notes.",
    "Leave token counts null with a reason unless the harness or provider measured them.",
]


class PackError(ValueError):
    """An authored source or generated payload breaks the pack contract."""


def fail(message: str) -> None:
    raise PackError(message)


# ---------------------------------------------------------------------------
# Canonical JSON identical to tessera.receipts.canonical_json
# ---------------------------------------------------------------------------


def _whole(value: Any) -> Any:
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) >= MAX_EXACT:
        try:
            as_float = float(value)
        except OverflowError as exc:
            raise ValueError("JSON integers must fit IEEE-754") from exc
        if int(as_float) != value:
            raise ValueError("JSON integers must round-trip exactly through IEEE-754")
        return as_float if abs(value) >= 10**16 else value
    if isinstance(value, float) and value.is_integer() and abs(value) < 10**16:
        return int(value)
    if isinstance(value, dict):
        return {key: _whole(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_whole(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _whole(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def value_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def digest(value: Any, domain: str = "") -> str:
    return hashlib.sha256((domain + canonical_json(value)).encode("utf-8")).hexdigest()


def shape_sha256(input_schema: dict[str, Any], output_schema: dict[str, Any]) -> str:
    """The shape fingerprint Tessera derives from a version-1 execution report contract."""
    return digest({"input_schema": input_schema, "output_schema": output_schema}, "execution-shape-v1\0")


def dumps(document: Any) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def dumps_lines(document: dict[str, Any], array: str) -> bytes:
    """Write a payload document with one array item per line, so each record diffs on its own."""
    head = {name: item for name, item in document.items() if name != array}
    lines = [json.dumps(item, ensure_ascii=False, allow_nan=False) for item in document[array]]
    text = json.dumps(head, ensure_ascii=False, allow_nan=False)[:-1] + f', "{array}": [\n'
    return (text + ",\n".join(lines) + "\n]}\n").encode("utf-8")


def load_json(path: Path) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, value in items:
            if name in result:
                fail(f"{path.name}: duplicate JSON property {name!r}")
            result[name] = value
        return result

    def constant(name: str) -> None:
        fail(f"{path.name}: non-finite JSON number {name}")

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def require_fields(obj: Any, where: str, required: set[str], optional: set[str] = frozenset()) -> None:
    if not isinstance(obj, dict):
        fail(f"{where}: must be an object")
    missing = required - set(obj)
    extra = set(obj) - required - set(optional)
    if missing:
        fail(f"{where}: missing {sorted(missing)}")
    if extra:
        fail(f"{where}: unknown fields {sorted(extra)}")


def text_list(value: Any, where: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        fail(f"{where}: must be a {'' if allow_empty else 'non-empty '}list of strings")
    for item in value:
        if not isinstance(item, str) or not item.strip():
            fail(f"{where}: items must be non-empty strings")
    return list(value)


# ---------------------------------------------------------------------------
# JSON Schema subset: the keywords below are the only ones packs may use
# ---------------------------------------------------------------------------

SCHEMA_KEYWORDS = {
    "type", "enum", "const", "properties", "required", "additionalProperties", "items", "minItems",
    "maxItems", "minLength", "maxLength", "pattern", "minimum", "maximum", "description",
}


def _need(ok: bool, message: str) -> None:
    if not ok:
        raise PackError(message)


TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: type(v) is int,
    "number": lambda v: type(v) in (int, float) and math.isfinite(v),
    "boolean": lambda v: type(v) is bool,
    "null": lambda v: v is None,
}


def check_schema(schema: Any, where: str) -> None:
    """A schema may use only the keywords this validator actually enforces."""
    _need(isinstance(schema, dict), f"{where}: schema must be an object")
    unknown = set(schema) - SCHEMA_KEYWORDS
    _need(not unknown, f"{where}: unsupported schema keywords {sorted(unknown)}")
    kinds = schema.get("type")
    if kinds is not None:
        for kind in kinds if isinstance(kinds, list) else [kinds]:
            _need(kind in TYPES, f"{where}: unknown type {kind!r}")
    if "pattern" in schema:
        pattern = schema["pattern"]
        re.compile(pattern)
        _need(not re.search(r"\(\?[=!<P]|\\[1-9]", pattern),
              f"{where}: patterns avoid lookaround and backreferences so every JSON Schema engine agrees")
    for low, high in (("minItems", "maxItems"), ("minLength", "maxLength"), ("minimum", "maximum")):
        if low in schema and high in schema:
            _need(schema[low] <= schema[high], f"{where}: {low} is above {high}")
    for name, sub in schema.get("properties", {}).items():
        check_schema(sub, f"{where}.{name}")
    if "items" in schema:
        check_schema(schema["items"], f"{where}[]")
    if "additionalProperties" in schema:
        _need(type(schema["additionalProperties"]) is bool, f"{where}: additionalProperties must be a boolean")
    for name in schema.get("required", []):
        _need(name in schema.get("properties", {}), f"{where}: required {name!r} has no property schema")


def end_of_text(pattern: str) -> str:
    """JSON Schema engines read a final $ as end of text; Python's $ would also accept a final newline."""
    return pattern[:-1] + "\\Z" if pattern.endswith("$") and not pattern.endswith("\\$") else pattern


def schema_errors(schema: dict[str, Any], value: Any, where: str = "$") -> list[str]:
    errors: list[str] = []
    kinds = schema.get("type")
    if kinds is not None:
        options = kinds if isinstance(kinds, list) else [kinds]
        if not any(TYPES[kind](value) for kind in options):
            return [f"{where}: expected {options}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{where}: not one of {schema['enum']}")
    if "const" in schema and value != schema["const"]:
        errors.append(f"{where}: must equal {schema['const']!r}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", math.inf):
            errors.append(f"{where}: length out of bounds")
        if "pattern" in schema and not re.search(end_of_text(schema["pattern"]), value):
            errors.append(f"{where}: does not match pattern")
    if type(value) in (int, float) and not isinstance(value, bool):
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            errors.append(f"{where}: out of range")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", math.inf):
            errors.append(f"{where}: item count out of bounds")
        if "items" in schema:
            for i, item in enumerate(value):
                errors += schema_errors(schema["items"], item, f"{where}[{i}]")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{where}: missing {name}")
        if schema.get("additionalProperties") is False:
            for name in sorted(set(value) - set(props)):
                errors.append(f"{where}: unexpected {name}")
        for name, sub in props.items():
            if name in value:
                errors += schema_errors(sub, value[name], f"{where}.{name}")
    return errors


# ---------------------------------------------------------------------------
# Library model
# ---------------------------------------------------------------------------

NOUN_FIELDS = {"slug", "category", "role", "title", "value"}
NOUN_OPTIONAL = {"relations", "category_reason", "synthetic"}
VERB_FIELDS = {"slug", "kind", "title", "claimant", "summary", "outcome", "ready_outcome", "produces", "steps", "acceptance"}
VERB_OPTIONAL = {
    "pinned", "slots", "params", "preferred", "suggested", "discovery_requested", "capabilities",
    "bounds", "model_use", "network", "review", "output_fields", "ready_requires", "follows", "notes",
    "update_slot",
}
SOURCE_FIELDS = {"pack_id", "title", "version", "summary", "nouns", "verbs"}
SOURCE_OPTIONAL = {"dependencies", "boundaries", "moved_from"}
# moved_from is provenance only: the repository and exact commit a pack moved from. It stays in
# source.json; nothing generated copies it.
MOVED_FROM_REPOSITORY = re.compile(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
MOVED_FROM_COMMIT = re.compile(r"[0-9a-f]{40}")


def code_ignore_rules(root: Path) -> list[tuple[str, bool, bool]]:
    """Simple patterns from the code folder's own top-level .gitignore: (pattern, anchored, folders only).

    Generated data, caches and local output that the folder ignores are not part of the pinned code.
    """
    path = root / ".gitignore"
    if not path.is_file():
        return []
    rules = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("!"):
            fail(f"{root.parent.name}/{CODE_DIR}/.gitignore: negated patterns are not supported ({line})")
        folders_only = line.endswith("/")
        line = line.rstrip("/")
        rules.append((line.lstrip("/"), line.startswith("/") or "/" in line, folders_only))
    return rules


def code_ignored(rel: Path, is_dir: bool, rules: list[tuple[str, bool, bool]]) -> bool:
    for pattern, anchored, folders_only in rules:
        if folders_only and not is_dir:
            continue
        if fnmatch.fnmatchcase(rel.as_posix() if anchored else rel.name, pattern):
            return True
    return False


def code_files(pack_dir: Path) -> list[Path]:
    """The files of a pack's code/ folder that the pack pins; caches, build output and the folder's
    own .gitignore entries are skipped."""
    root = pack_dir / CODE_DIR
    if not root.exists():
        return []
    if root.is_symlink() or not root.is_dir():
        fail(f"{pack_dir.name}: {CODE_DIR} must be a folder")
    rules = code_ignore_rules(root)
    found = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in CODE_SKIP_DIRS or part.endswith(".egg-info") for part in rel.parts):
            continue
        parents = [Path(*rel.parts[:i]) for i in range(1, len(rel.parts))]
        if any(code_ignored(parent, True, rules) for parent in parents) or code_ignored(rel, path.is_dir(), rules):
            continue
        if path.is_symlink():
            fail(f"{pack_dir.name}/{CODE_DIR}: symbolic links are not allowed ({rel.as_posix()})")
        if path.is_file() and path.suffix not in CODE_SKIP_SUFFIXES:
            found.append(path)
    if not found:
        fail(f"{pack_dir.name}: {CODE_DIR} holds no files")
    return found


def code_digest(pack_dir: Path) -> dict[str, Any] | None:
    """Where a pack's code lives, how many files it has and one SHA-256 over every path and file digest."""
    files = code_files(pack_dir)
    if not files:
        return None
    root = pack_dir / CODE_DIR
    entries = sorted([path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()] for path in files)
    return {"path": f"packs/{pack_dir.name}/{CODE_DIR}", "files": len(entries), "sha256": digest(entries, "pack-code-v1\0")}


class Library:
    """All pack sources, resolved together so cross-pack pins stay consistent."""

    def __init__(self, sources: dict[str, dict[str, Any]], readmes: dict[str, bytes],
                 code: dict[str, dict[str, Any] | None] | None = None) -> None:
        self.sources = sources
        self.readmes = readmes
        self.code = code or {}
        self.nouns: dict[tuple[str, str], dict[str, Any]] = {}
        self.templates: set[str] = set()
        for pack_id, source in sources.items():
            for noun in source["nouns"]:
                self.nouns[(pack_id, noun["slug"])] = noun
            for verb in source["verbs"]:
                self.templates.add(f"{pack_id}.{verb['slug']}")
        self._values: dict[tuple[str, str], dict[str, Any]] = {}
        self._resolving: set[tuple[str, str]] = set()

    @staticmethod
    def store(pack_id: str) -> str:
        return f"seedpack.{pack_id}"

    def key(self, pack_id: str, slug: str) -> str:
        """Keys carry the pack version, so a new version never collides with an earlier one."""
        return f"{pack_id}.v{self.sources[pack_id]['version']}.{slug}"

    def locate(self, pack_id: str, ref: str, where: str) -> tuple[str, str]:
        target_pack, _, slug = ref.rpartition(":")
        target_pack = target_pack or pack_id
        if target_pack != pack_id and target_pack not in self.sources[pack_id].get("dependencies", []):
            fail(f"{where}: {ref!r} needs {target_pack!r} in dependencies")
        if (target_pack, slug) not in self.nouns:
            fail(f"{where}: unknown noun {ref!r}")
        return target_pack, slug

    def pin(self, pack_id: str, ref: str, where: str) -> dict[str, Any]:
        target = self.locate(pack_id, ref, where)
        return {
            "store": self.store(target[0]),
            "key": self.key(*target),
            "version": 1,
            "value_sha256": value_sha256(self.value(*target)),
        }

    def resolve(self, pack_id: str, obj: Any, where: str) -> Any:
        """Replace {"$pin": ref} with a NounRef, {"$key": ref} with a key, {"$verb": id} with a template id
        and {"$code": pack} with that pack's code location, file count and digest."""
        if isinstance(obj, dict):
            if set(obj) == {"$pin"}:
                return self.pin(pack_id, obj["$pin"], where)
            if set(obj) == {"$code"}:
                target = obj["$code"]
                if target != pack_id and target not in self.sources[pack_id].get("dependencies", []):
                    fail(f"{where}: {target!r} needs {target!r} in dependencies")
                if not self.code.get(target):
                    fail(f"{where}: pack {target!r} has no {CODE_DIR} folder")
                return dict(self.code[target])
            if set(obj) == {"$key"}:
                return self.key(*self.locate(pack_id, obj["$key"], where))
            if set(obj) == {"$verb"}:
                if obj["$verb"] not in self.templates:
                    fail(f"{where}: unknown verb template {obj['$verb']!r}")
                return obj["$verb"]
            if any(name.startswith("$") for name in obj):
                fail(f"{where}: unsupported directive in {sorted(obj)}")
            return {name: self.resolve(pack_id, item, f"{where}.{name}") for name, item in obj.items()}
        if isinstance(obj, list):
            return [self.resolve(pack_id, item, f"{where}[{i}]") for i, item in enumerate(obj)]
        return obj

    def relation(self, pack_id: str, entry: Any, where: str) -> dict[str, Any]:
        if not (isinstance(entry, list) and len(entry) in (2, 3) and all(isinstance(x, str) for x in entry)):
            fail(f"{where}: relations are [relation, target] or [relation, target, note]")
        target = self.locate(pack_id, entry[1], where)
        return {
            "relation": entry[0],
            "target_id": f"{self.store(target[0])}/{self.key(*target)}",
            "target_category": self.nouns[target]["category"],
            "note": entry[2] if len(entry) == 3 else "",
        }

    def value(self, pack_id: str, slug: str) -> dict[str, Any]:
        ident = (pack_id, slug)
        if ident in self._values:
            return self._values[ident]
        if ident in self._resolving:
            fail(f"{pack_id}:{slug}: pin cycle")
        self._resolving.add(ident)
        source = self.sources[pack_id]
        noun = self.nouns[ident]
        where = f"{pack_id}:{slug}"
        content = self.resolve(pack_id, noun["value"], where)
        if not isinstance(content, dict):
            fail(f"{where}: value must be an object")
        reserved = {"category_id", "role", "pack", "pack_version", "title", "status", "admission",
                    "license", "content_kind", "provenance", "dimensions", "dimension_basis",
                    "relations", "category_reason"}
        reserved |= TAGGING_FIELDS
        if reserved & set(content):
            fail(f"{where}: value may not set reserved fields {sorted(reserved & set(content))}")
        value: dict[str, Any] = {
            "category_id": noun["category"],
            "role": noun["role"],
            "pack": pack_id,
            "pack_version": source["version"],
            "title": noun["title"],
        }
        if noun.get("category_reason"):
            value["category_reason"] = noun["category_reason"]
        value.update(content)
        value.update(
            {
                "status": "proposal",
                "admission": "not_admitted",
                "content_kind": "synthetic_example" if noun.get("synthetic") else "authored_guidance",
                "license": "MIT",
                "provenance": dict(PROVENANCE),
                "dimensions": dict(FLOOR_DIMENSIONS),
                "dimension_basis": dict(DIMENSION_BASIS),
                "relations": [
                    self.relation(pack_id, entry, f"{where}.relations[{i}]")
                    for i, entry in enumerate(noun.get("relations", []))
                ],
            }
        )
        self._resolving.discard(ident)
        self._values[ident] = value
        return value


# ---------------------------------------------------------------------------
# Source checks
# ---------------------------------------------------------------------------


def check_source(pack_id: str, source: Any) -> None:
    require_fields(source, f"{pack_id}/source.json", SOURCE_FIELDS, SOURCE_OPTIONAL)
    if source["pack_id"] != pack_id or not PACK_ID.fullmatch(pack_id):
        fail(f"{pack_id}: pack_id must match its directory and use lowercase words")
    if not re.fullmatch(r"\d+\.\d+\.\d+", source["version"]):
        fail(f"{pack_id}: version is a display version such as 0.1.0")
    if not str(source["summary"]).startswith(PACK_PHRASES):
        fail(f"{pack_id}: the summary starts with {PACK_PHRASE!r}, in plain English")
    for dep in source.get("dependencies", []):
        if not isinstance(dep, str) or dep == pack_id:
            fail(f"{pack_id}: invalid dependency {dep!r}")
    if "moved_from" in source:
        moved = source["moved_from"]
        require_fields(moved, f"{pack_id}.moved_from", {"repository", "commit"})
        if not (isinstance(moved["repository"], str) and MOVED_FROM_REPOSITORY.fullmatch(moved["repository"])
                and isinstance(moved["commit"], str) and MOVED_FROM_COMMIT.fullmatch(moved["commit"])):
            fail(f"{pack_id}: moved_from names a GitHub repository URL and a full 40-character commit")
    seen: set[str] = set()
    for i, noun in enumerate(source["nouns"]):
        where = f"{pack_id}.nouns[{i}]"
        require_fields(noun, where, NOUN_FIELDS, NOUN_OPTIONAL)
        if not SLUG.fullmatch(noun["slug"]) or noun["slug"] in seen:
            fail(f"{where}: slug must be unique lowercase words, dots and hyphens")
        seen.add(noun["slug"])
        if not str(noun["category"]).startswith("noun."):
            fail(f"{where}: noun category must start with noun.")
        if not isinstance(noun["value"], dict):
            fail(f"{where}: value must be an object")
    if "pack" not in seen:
        fail(f"{pack_id}: every pack needs a descriptor noun with slug 'pack'")
    descriptor = next(noun for noun in source["nouns"] if noun["slug"] == "pack")
    if not descriptor["title"].startswith(PACK_PHRASES):
        fail(f"{pack_id}: the descriptor noun's title starts with {PACK_PHRASE!r}")
    verbs: set[str] = set()
    for i, verb in enumerate(source["verbs"]):
        where = f"{pack_id}.verbs[{i}]"
        require_fields(verb, where, VERB_FIELDS, VERB_OPTIONAL)
        if not SLUG.fullmatch(verb["slug"]) or verb["slug"] in verbs:
            fail(f"{where}: slug must be unique")
        verbs.add(verb["slug"])
        if not str(verb["kind"]).startswith("verb."):
            fail(f"{where}: kind must be a verb category")
        if verb["claimant"] not in CLAIMANTS:
            fail(f"{where}: claimant must be one of {sorted(CLAIMANTS)}")
        if verb.get("model_use", "worker_allowance") not in MODEL_USE:
            fail(f"{where}: model_use must be one of {sorted(MODEL_USE)}")
        if verb["claimant"] == "human" and verb.get("model_use") != "none":
            fail(f"{where}: a human verb records model_use none")
        if verb.get("review", "owning_policy") not in REVIEW_RULES:
            fail(f"{where}: review must be one of {sorted(REVIEW_RULES)}")
        if not re.fullmatch(r"[a-z][a-z_]{2,40}", verb["ready_outcome"]) or verb["ready_outcome"] in STANDARD_OUTCOMES:
            fail(f"{where}: ready_outcome must be a distinct lowercase outcome name")
        text_list(verb["steps"], f"{where}.steps")
        for j, check in enumerate(verb["acceptance"]):
            require_fields(check, f"{where}.acceptance[{j}]", {"id", "check", "method"})
            if check["method"] not in {"deterministic", "judgment"}:
                fail(f"{where}.acceptance[{j}]: method is deterministic or judgment")
        if not verb["produces"]:
            fail(f"{where}: a verb produces at least one noun shaped by a template")
        for j, item in enumerate(verb["produces"]):
            require_fields(item, f"{where}.produces[{j}]", {"name", "template"}, {"max"})
        for j, slot in enumerate(verb.get("slots", [])):
            require_fields(slot, f"{where}.slots[{j}]", {"name", "category", "description"}, {"required", "many", "max"})
            if not SLOT.fullmatch(slot["name"]):
                fail(f"{where}.slots[{j}]: slot names are lowercase identifiers")
        for name, spec in verb.get("params", {}).items():
            if not SLOT.fullmatch(name):
                fail(f"{where}.params: invalid parameter name {name!r}")
            require_fields(spec, f"{where}.params.{name}", {"schema", "description"}, {"required", "default"})


def load_library(packs_dir: Path = PACKS) -> Library:
    sources: dict[str, dict[str, Any]] = {}
    readmes: dict[str, bytes] = {}
    code: dict[str, dict[str, Any] | None] = {}
    for directory in sorted(path for path in packs_dir.iterdir() if path.is_dir()):
        source = load_json(directory / "source.json")
        check_source(directory.name, source)
        sources[directory.name] = source
        readmes[directory.name] = (directory / "README.md").read_bytes()
        code[directory.name] = code_digest(directory)
    for pack_id, source in sources.items():
        for dep in source.get("dependencies", []):
            if dep not in sources:
                fail(f"{pack_id}: dependency {dep!r} is not a pack in this library")
    return Library(sources, readmes, code)


# ---------------------------------------------------------------------------
# Verb templates
# ---------------------------------------------------------------------------


def slot_schema(slot: dict[str, Any]) -> dict[str, Any]:
    if slot.get("many"):
        return {"type": "array", "minItems": 1 if slot.get("required", True) else 0,
                "maxItems": int(slot.get("max", 8)), "items": NOUN_REF_SCHEMA}
    if not slot.get("required", True):
        return {**NOUN_REF_SCHEMA, "type": ["object", "null"]}
    return NOUN_REF_SCHEMA


def build_input_schema(verb: dict[str, Any], pinned_count: int) -> dict[str, Any]:
    slots = verb.get("slots", [])
    params = verb.get("params", {})
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["pinned", "slots", "params"],
        "properties": {
            "pinned": {"type": "array", "minItems": pinned_count, "maxItems": pinned_count, "items": NOUN_REF_SCHEMA},
            "slots": {
                "type": "object",
                "additionalProperties": False,
                "required": [slot["name"] for slot in slots if slot.get("required", True)],
                "properties": {slot["name"]: slot_schema(slot) for slot in slots},
            },
            "params": {
                "type": "object",
                "additionalProperties": False,
                "required": [name for name, spec in params.items() if spec.get("required", True)],
                "properties": {name: spec["schema"] for name, spec in params.items()},
            },
        },
    }


def build_output_schema(verb: dict[str, Any]) -> dict[str, Any]:
    produced = sum(int(item.get("max", 1)) for item in verb["produces"])
    properties: dict[str, Any] = {
        "outcome": {"type": "string", "enum": [verb["ready_outcome"], *STANDARD_OUTCOMES]},
        "summary": {"type": "string", "minLength": 1, "maxLength": 1200},
        "artifacts": {
            "type": "array",
            "maxItems": produced,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["role", "ref"],
                "properties": {
                    "role": {"type": "string", "minLength": 1, "maxLength": 64},
                    "ref": NOUN_REF_SCHEMA,
                    "value": {"type": "object"},
                },
            },
        },
        "checks": {
            "type": "array",
            "maxItems": 64,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "result"],
                "properties": {
                    "id": {"type": "string", "minLength": 1, "maxLength": 80},
                    "result": {"type": "string", "enum": ["pass", "fail", "not_run"]},
                    "evidence": {"type": "string", "maxLength": 2000},
                },
            },
        },
        "unknowns": {
            "type": "array",
            "maxItems": 32,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["item", "reason"],
                "properties": {
                    "item": {"type": "string", "minLength": 1, "maxLength": 300},
                    "reason": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "would_resolve": {"type": "string", "maxLength": 1000},
                },
            },
        },
        "no_change_reason": {"type": "string", "minLength": 1, "maxLength": 2000},
        "blocked_question": {"type": "string", "minLength": 1, "maxLength": 1000},
        "proposed_verbs": {
            "type": "array",
            "maxItems": 10,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "title", "outcome", "why", "priority"],
                "properties": {
                    "kind": {"type": "string", "pattern": "^verb\\.[a-z_]+$"},
                    "template_id": {"type": "string", "minLength": 1, "maxLength": 160},
                    "title": {"type": "string", "minLength": 1, "maxLength": 160},
                    "outcome": {"type": "string", "minLength": 1, "maxLength": 600},
                    "why": {"type": "string", "minLength": 1, "maxLength": 600},
                    "input_pins": {"type": "array", "maxItems": 16, "items": NOUN_REF_SCHEMA},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 3},
                },
            },
        },
        "proposed_nouns": {
            "type": "array",
            "maxItems": 10,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["category", "role", "title", "why"],
                "properties": {
                    "category": {"type": "string", "pattern": "^noun\\.[a-z_]+$"},
                    "role": {"type": "string", "minLength": 1, "maxLength": 64},
                    "title": {"type": "string", "minLength": 1, "maxLength": 160},
                    "why": {"type": "string", "minLength": 1, "maxLength": 600},
                },
            },
        },
        "run_notes": RUN_NOTES_SCHEMA,
    }
    for name, schema in verb.get("output_fields", {}).items():
        if name in properties:
            fail(f"{verb['slug']}: output field {name!r} is part of the shared envelope")
        properties[name] = schema
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["outcome", "summary", "artifacts", "checks", "unknowns"],
        "properties": properties,
    }


def report_template(input_schema: dict[str, Any], output_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "harness": {"name": "replace-with-harness-name", "version": "replace-with-exact-version"},
        "model": {"provider": "replace-with-provider-or-none", "name": "replace-with-exact-model-or-none"},
        "summaries": {
            "problem": "One sentence: what this run was asked to resolve.",
            "input": "One sentence: which pinned inputs were read.",
            "solution": "One sentence: what was produced or why the outcome was no_change, unknown or blocked.",
        },
        "contract": {"input_schema": input_schema, "output_schema": output_schema},
        "blocks": [{"kind": "error", "text": ""}],
        "artifact_refs": [],
        "usage": {
            "source": "harness_metadata",
            "input_tokens": None,
            "output_tokens": None,
            "reason": "Template only. Replace with measured counters or keep null with a reason.",
        },
    }


def network(verb: dict[str, Any], where: str) -> dict[str, str]:
    raw = verb.get("network", "none")
    mode, detail = ("none", "No network access.") if raw == "none" else (raw if isinstance(raw, list) and len(raw) == 2 else (None, None))
    if mode not in NETWORK_MODES or not isinstance(detail, str) or not detail.strip():
        fail(f"{where}: network is 'none' or [mode, detail] with mode in {sorted(NETWORK_MODES)}")
    return {"mode": mode, "detail": detail}


def write_target(pack_id: str, verb: dict[str, Any], slots: list[dict[str, Any]], where: str) -> dict[str, Any]:
    """Create-only by default; an explicit update slot allows one compare-and-set write to that noun."""
    slot = verb.get("update_slot")
    if slot is None:
        return {"write_mode": "create_only", "store_param": "output_store",
                "key_rule": f"{pack_id}.<role>.<task_id>[.<n>]", "expected_version": 0}
    if slot not in {item["name"] for item in slots if not item.get("many") and item.get("required", True)}:
        fail(f"{where}: update_slot must name a required single-valued slot")
    return {
        "write_mode": "compare_and_set",
        "target_slot": slot,
        "expected_version": {"from_slot": slot},
        "update_rule": f"Write a new version of the noun pinned in slot {slot!r}, in its own store and key, with its pinned version as the expected version. A version conflict means re-read and stop.",
    }


def build_verb(lib: Library, pack_id: str, verb: dict[str, Any]) -> dict[str, Any]:
    where = f"{pack_id}.{verb['slug']}"
    pinned_refs = list(dict.fromkeys(verb.get("pinned", [])))
    produces = verb["produces"]
    pinned = [lib.pin(pack_id, ref, f"{where}.pinned") for ref in pinned_refs]
    template_refs = [lib.pin(pack_id, item["template"], f"{where}.produces") for item in produces]
    relations = [lib.relation(pack_id, ["requires_noun", ref], f"{where}.pinned") for ref in pinned_refs]
    relations += [
        lib.relation(pack_id, ["produces_noun", item["template"], f"output {item['name']}"], f"{where}.produces")
        for item in produces
    ]
    params = verb.get("params", {})
    params_template = {name: copy.deepcopy(spec["default"]) if "default" in spec else None for name, spec in params.items()}
    params_template["output_store"] = f"{lib.store(pack_id)}.outputs"
    param_specs = {
        **{name: {key: spec[key] for key in ("description", "schema", "required", "default") if key in spec}
           for name, spec in params.items()},
        "output_store": {
            "description": "Store for the produced nouns. The default is a placeholder; use the store your owner assigned.",
            "schema": {"type": "string", "pattern": NAME_PATTERN},
            "required": True,
            "default": f"{lib.store(pack_id)}.outputs",
        },
    }
    if "output_store" in params:
        fail(f"{where}: output_store is a standard parameter")
    shaped = {**verb, "params": param_specs}
    input_schema = build_input_schema(shaped, len(pinned))
    output_schema = build_output_schema(verb)
    slots = verb.get("slots", [])
    outcomes = [verb["ready_outcome"], *STANDARD_OUTCOMES]
    ready_requires = ["artifacts", *verb.get("ready_requires", [])]
    bounds = {"max_attempts": 2, "max_elapsed_seconds": 1800, **verb.get("bounds", {})}
    for name, bound in bounds.items():
        if type(bound) is not int or bound < 0:
            fail(f"{where}: bound {name} must be a non-negative integer")
    model_use = verb.get("model_use", "worker_allowance")
    review = verb.get("review", "owning_policy")
    brief: dict[str, Any] = {
        "category_id": verb["kind"],
        "contract": VERB_CONTRACT,
        "pack": pack_id,
        "pack_version": lib.sources[pack_id]["version"],
        "template_id": f"{pack_id}.{verb['slug']}",
        "title": verb["title"],
        "plain_summary": verb["summary"],
        "outcome": verb["outcome"],
        "claimant": verb["claimant"],
        "inputs": {
            "pinned": pinned,
            "slots": {slot["name"]: [] if slot.get("many") else None for slot in slots},
            "params": params_template,
        },
        "slot_specs": {
            slot["name"]: {
                "category": slot["category"],
                "required": slot.get("required", True),
                "many": bool(slot.get("many", False)),
                "description": slot["description"],
            }
            for slot in slots
        },
        "param_specs": param_specs,
        "input_schema": input_schema,
        "output_contract": {
            "visibility_scope": "surface_only",
            "allowed_surfaces": [],
            **write_target(pack_id, verb, slots, where),
            "produces": [
                {"name": item["name"], "template": ref, "max": int(item.get("max", 1))}
                for item, ref in zip(produces, template_refs)
            ],
            "delivery": (
                "Write produced nouns surface_only under your own authenticated surface, which is the "
                "requester's assigned surface, so the requester and that surface's reviewers can read "
                "them. Never use public_commons or allowlist other surfaces. Return every produced "
                "noun's pin in output.artifacts; add its value when the requester asks for inline delivery."
            ),
        },
        "output_schema": output_schema,
        "permitted_outcomes": outcomes,
        "outcome_meanings": {
            verb["ready_outcome"]: "The declared nouns were produced and every deterministic acceptance check passed.",
            **OUTCOME_MEANINGS,
        },
        "outcome_requirements": {
            verb["ready_outcome"]: ready_requires,
            "no_change": ["no_change_reason"],
            "unknown": ["unknowns"],
            "blocked": ["blocked_question"],
        },
        "acceptance_checks": [dict(check) for check in verb["acceptance"]],
        "creates": dict(CREATES),
        "guidance": {
            "required": [*text_list(verb["steps"], f"{where}.steps"), FOLLOW_UP_STEP],
            "preferred": text_list(verb.get("preferred", []), f"{where}.preferred", allow_empty=True),
            "suggested": text_list(verb.get("suggested", []), f"{where}.suggested", allow_empty=True),
            "discovery_requested": bool(verb.get("discovery_requested", False)),
        },
        "required_capabilities": text_list(
            verb.get("capabilities", ["read permitted noun versions", "write candidate nouns in the requester's scope"]),
            f"{where}.capabilities",
        ),
        "bounds": bounds,
        "execution": {
            "reasoning": "human" if verb["claimant"] == "human" else ("authorized_worker" if model_use == "worker_allowance" else "deterministic_tools"),
            "model_use": model_use,
            "inference_allowance": INFERENCE_ALLOWANCE,
            "server_fallback": False,
            "maximum_automatically_enqueued_children": 0,
            "network": network(verb, where),
            "external_effects": "none",
        },
        "review": {
            "required": review,
            "self_approval_permitted": False,
            "publication_permitted": False,
            "admission_permitted": False,
        },
        "instantiation": {
            "status": "template",
            "fill_before_enqueue": [slot["name"] for slot in slots if slot.get("required", True)],
            "rule": (
                "Replace each slot with exact NounRef pins, set the params, then recompute the "
                "idempotency key with scripts/build_packs.py --instantiate. Enqueue only with your "
                "own grants in a queue your owner assigned."
            ),
        },
        "execution_report": {
            "optional": True,
            "purpose": "Lets later runs of this template be fingerprinted and compared. It is worker reported, not proof.",
            "template": report_template(input_schema, output_schema),
            "fill_rules": list(REPORT_FILL_RULES),
            "run_notes_field": "output.run_notes",
            "shape_sha256": shape_sha256(input_schema, output_schema),
        },
        "dimensions": dict(FLOOR_DIMENSIONS),
        "dimension_basis": dict(DIMENSION_BASIS),
        "relations": relations,
    }
    if verb.get("follows"):
        brief["follows_templates"] = [lib.resolve(pack_id, {"$verb": item}, where) for item in verb["follows"]]
    if verb.get("notes"):
        brief["notes"] = text_list(verb["notes"], f"{where}.notes")
    template_key = template_idempotency_key(pack_id, verb["slug"], QUEUE_PLACEHOLDER, verb["kind"], brief)
    return {
        "queue": QUEUE_PLACEHOLDER,
        "kind": verb["kind"],
        "effect_class": "write-internal",
        "priority": 50,
        "idempotency_key": template_key,
        "depends_on": [],
        **copy.deepcopy(GOVERNANCE),
        "tags": [
            f"category:{verb['kind']}",
            f"pack:{pack_id}",
            f"template:{verb['slug']}",
            f"claimant:{verb['claimant']}",
            "status:quarantined",
        ],
        "brief": brief,
    }


def template_idempotency_key(pack_id: str, slug: str, queue: str, kind: str, brief: dict[str, Any]) -> str:
    """Readable and content-bound: the same template always gets the same enqueue identity."""
    return f"seedpack:{pack_id}:{slug}:" + digest({"queue": queue, "kind": kind, "brief": brief})


def build_noun(lib: Library, pack_id: str, noun: dict[str, Any]) -> dict[str, Any]:
    tags = [f"category:{noun['category']}", f"pack:{pack_id}", f"role:{noun['role']}"]
    tags.append("synthetic:true" if noun.get("synthetic") else "content:authored")
    tags += ["spdx:MIT", "status:quarantined"]
    return {
        "store": lib.store(pack_id),
        "key": lib.key(pack_id, noun["slug"]),
        "expected_version": 0,
        **copy.deepcopy(GOVERNANCE),
        "tags": tags,
        "value": lib.value(pack_id, noun["slug"]),
    }


def build_library(lib: Library) -> dict[str, dict[str, bytes]]:
    """Return generated file bytes for every pack; pure and deterministic."""
    out: dict[str, dict[str, bytes]] = {}
    for pack_id, source in lib.sources.items():
        records = [build_noun(lib, pack_id, noun) for noun in source["nouns"]]
        tasks = [build_verb(lib, pack_id, verb) for verb in source["verbs"]]
        nouns_doc = {"format": NOUNS_FORMAT, "pack_id": pack_id, "status": "proposal_only", "records": records}
        verbs_doc = {"format": VERBS_FORMAT, "pack_id": pack_id, "status": "proposal_only", "tasks": tasks}
        nouns_bytes, verbs_bytes = dumps_lines(nouns_doc, "records"), dumps_lines(verbs_doc, "tasks")
        source_bytes = dumps(source)
        deps = []
        for dep in source.get("dependencies", []):
            used = sorted(
                {
                    ref["key"]
                    for task in tasks
                    for ref in task["brief"]["inputs"]["pinned"] + [p["template"] for p in task["brief"]["output_contract"]["produces"]]
                    if ref["store"] == lib.store(dep)
                }
                | {
                    rel["target_id"].split("/", 1)[1]
                    for record in records
                    for rel in record["value"]["relations"]
                    if rel["target_id"].startswith(lib.store(dep) + "/")
                }
            )
            deps.append({"pack_id": dep, "keys": used})
        manifest = {
            "format": MANIFEST_FORMAT,
            "status": "proposal_only",
            "pack_id": pack_id,
            "title": source["title"],
            "version": source["version"],
            "summary": source["summary"],
            "license": "MIT",
            "store": lib.store(pack_id),
            "queue_placeholder": QUEUE_PLACEHOLDER,
            "files": [
                {"path": "README.md", "sha256": hashlib.sha256(lib.readmes[pack_id]).hexdigest()},
                {"path": "source.json", "sha256": hashlib.sha256(source_bytes).hexdigest()},
                {"path": "nouns.json", "sha256": hashlib.sha256(nouns_bytes).hexdigest()},
                {"path": "verbs.json", "sha256": hashlib.sha256(verbs_bytes).hexdigest()},
            ],
            "nouns": [
                {
                    "key": record["key"],
                    "category_id": record["value"]["category_id"],
                    "role": record["value"]["role"],
                    "value_sha256": value_sha256(record["value"]),
                }
                for record in records
            ],
            "verbs": [
                {
                    "template_id": task["brief"]["template_id"],
                    "kind": task["kind"],
                    "claimant": task["brief"]["claimant"],
                    "idempotency_key": task["idempotency_key"],
                    "report_shape_sha256": task["brief"]["execution_report"]["shape_sha256"],
                }
                for task in tasks
            ],
            **({"code": {**lib.code[pack_id], "runs": CODE_RUNS}} if lib.code.get(pack_id) else {}),
            "dependencies": deps,
            "boundaries": text_list(source.get("boundaries", []), f"{pack_id}.boundaries", allow_empty=True),
            "override_policy": {"automatic_merge": False, "on_conflict": "stop_and_clarify"},
            "importer": None,
            "importer_reason": (
                "No manifest endpoint or generic importer exists. Reading or exporting this pack "
                "writes no records, enqueues no verbs and activates nothing."
            ),
            "activation": {
                "automatic": False,
                "steps": [
                    "An owner assigns the namespace, store and queue.",
                    "Each noun is written create-only with existing grants and read back; its value SHA-256 must match the pin.",
                    "A verb template is filled with exact pins and enqueued explicitly by an authorized requester.",
                ],
            },
            "evaluation": {
                "result": None,
                "reason": "Offline shape, category and digest validation only. No worker has run these verbs.",
            },
        }
        out[pack_id] = {
            "nouns.json": nouns_bytes,
            "verbs.json": verbs_bytes,
            "manifest.json": dumps(manifest),
        }
    return out


# ---------------------------------------------------------------------------
# Instantiation (pure; prints for review, never enqueues)
# ---------------------------------------------------------------------------


def instantiate(
    task: dict[str, Any], slots: dict[str, Any], params: dict[str, Any], queue: str | None = None
) -> dict[str, Any]:
    """Fill a verb template with exact pins and params, optionally in an assigned queue; return a new TaskSpec."""
    brief = task["brief"]
    if brief.get("instantiation", {}).get("status") != "template":
        fail("only a verb template can be instantiated")
    specs = brief["slot_specs"]
    if set(slots) - set(specs):
        fail(f"unknown slots {sorted(set(slots) - set(specs))}")
    filled_slots: dict[str, Any] = {}
    for name, spec in specs.items():
        value = slots.get(name, [] if spec["many"] else None)
        refs = value if spec["many"] else ([value] if value is not None else [])
        if spec["required"] and not refs:
            fail(f"slot {name!r} is required")
        for ref in refs:
            require_fields(ref, f"slot {name}", {"store", "key", "version", "value_sha256"})
            if not (re.fullmatch(NAME_PATTERN, ref["store"]) and re.fullmatch(KEY_PATTERN, ref["key"])
                    and type(ref["version"]) is int and ref["version"] >= 1
                    and re.fullmatch(DIGEST_PATTERN, ref["value_sha256"])):
                fail(f"slot {name!r} needs an exact NounRef pin")
        filled_slots[name] = value
    if set(params) - set(brief["param_specs"]):
        fail(f"unknown params {sorted(set(params) - set(brief['param_specs']))}")
    filled_params = {**brief["inputs"]["params"], **params}
    for name, spec in brief["param_specs"].items():
        if spec.get("required", True) and filled_params.get(name) is None:
            fail(f"param {name!r} is required")
    inputs = {"pinned": brief["inputs"]["pinned"], "slots": filled_slots, "params": filled_params}
    problems = schema_errors(brief["input_schema"], inputs)
    if problems:
        fail(f"filled inputs do not match the template's input schema: {problems[:3]}")
    target_queue = task["queue"] if queue is None else queue
    if not isinstance(target_queue, str) or not re.fullmatch(NAME_PATTERN, target_queue):
        fail("queue must be an assigned Tessera queue name")
    instance = copy.deepcopy(task)
    instance["queue"] = target_queue
    instance["brief"]["inputs"] = inputs
    instance["brief"]["instantiation"] = {"status": "instance", "template_idempotency_key": task["idempotency_key"]}
    prefix = task["idempotency_key"].rsplit(":", 1)[0]
    try:
        identity = digest({"template": task["idempotency_key"], "queue": target_queue, "inputs": inputs})
    except ValueError as exc:
        fail(f"inputs are not canonical JSON: {exc}")
    instance["idempotency_key"] = prefix + ":" + identity
    return instance


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def write_or_check(check: bool, packs_dir: Path = PACKS) -> list[str]:
    lib = load_library(packs_dir)
    built = build_library(lib)
    problems: list[str] = []
    for pack_id, files in built.items():
        directory = packs_dir / pack_id
        for name, data in files.items():
            path = directory / name
            current = path.read_bytes() if path.exists() else None
            if current == data:
                continue
            if check:
                problems.append(f"{pack_id}/{name} differs from a fresh build; run python3 scripts/build_packs.py")
            else:
                path.write_bytes(data)
        source_bytes = (directory / "source.json").read_bytes()
        if source_bytes != dumps(lib.sources[pack_id]):
            if check:
                problems.append(f"{pack_id}/source.json is not in canonical layout; run python3 scripts/build_packs.py")
            else:
                (directory / "source.json").write_bytes(dumps(lib.sources[pack_id]))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="fail when generated files are stale")
    mode.add_argument("--instantiate", metavar="TEMPLATE_ID", help="print one filled TaskSpec; never enqueues")
    parser.add_argument("--inputs", type=Path, help='JSON object {"slots": {...}, "params": {...}} for --instantiate')
    parser.add_argument("--queue", help="assigned queue for --instantiate (default: the template's placeholder)")
    args = parser.parse_args(argv)
    try:
        if args.instantiate:
            if not args.inputs:
                parser.error("--instantiate needs --inputs")
            lib = load_library()
            built = build_library(lib)
            pack_id = args.instantiate.split(".", 1)[0]
            if pack_id not in built:
                parser.error("unknown pack")
            tasks = json.loads(built[pack_id]["verbs.json"])["tasks"]
            match = [t for t in tasks if t["brief"]["template_id"] == args.instantiate]
            if not match:
                parser.error("unknown verb template")
            inputs = load_json(args.inputs)
            require_fields(inputs, "inputs", set(), {"slots", "params"})
            task = instantiate(match[0], inputs.get("slots", {}), inputs.get("params", {}), args.queue)
            print(json.dumps({"enqueued": False, "task": task}, indent=2, ensure_ascii=False))
            return 0
        problems = write_or_check(args.check)
    except (PackError, ValueError, OSError) as exc:
        print(f"build_packs: {exc}", file=sys.stderr)
        return 1
    if problems:
        for problem in problems:
            print("build_packs: " + problem, file=sys.stderr)
        return 1
    print(json.dumps({"packs": sorted(p.name for p in PACKS.iterdir() if p.is_dir()), "check": args.check,
                      "network": False, "enqueued": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
