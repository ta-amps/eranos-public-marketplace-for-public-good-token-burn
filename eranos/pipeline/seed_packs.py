"""Example kits whose nouns and verbs live in the seed-pack library.

A referenced example (`examples/kits/*.json` with a `seed_pack` block) keeps only this catalog's
envelope: the kit id, track, license and governance, and the scripted review used by the example
run. It names the pack's kit noun, and the noun holding the organization's need in its own plain
words, by exact NounRef pins. Everything else
(the step map, skills, read-only tool cards, files, checklist, sources and synthetic test cases)
is read from the library's `packs/<pack>/nouns.json`, so each kit has one source.

Every pin is checked against the SHA-256 of the noun's canonical JSON, and every step must name a
verb template of the same pack with the same title and a matching claimant: a person for
`human_only` steps, an agent otherwise. A mismatch fails loudly. Reading a pack writes, enqueues
and activates nothing.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from tessera.receipts import canonical_json

from eranos.jsonfile import load_json
from eranos.tracks import get_track

LIBRARY_ENV = "ERANOS_SEED_PACKS"
LIBRARY_DIRNAME = "seed-packs-library-of-nouns-and-verbs"
KIT_FORMAT = "agent-kit.v1"
PIN_FIELDS = frozenset({"store", "key", "version", "value_sha256"})
GOVERNANCE_FIELDS = (
    "spdx_license",
    "tags",
    "target_cohorts",
    "producer_surface",
    "visibility_scope",
    "allowed_surfaces",
)
# Test cases may carry more, such as a rendered page and its expected transcription; the catalog
# fixture keeps these fields.
FIXTURE_FIELDS = (
    "id",
    "scenario",
    "sample_input",
    "expected_indicators",
    "expected_human_escalation",
)
ENVELOPE_FIELDS = frozenset(
    {"kit_id", "track_id", "deliverable_kind", "needs_steward_signoff", *GOVERNANCE_FIELDS}
)


class SeedPackError(ValueError):
    """A referenced example does not match the seed pack it names."""


def library_root(explicit: Path | None = None) -> Path:
    """The library checkout: an explicit path, `ERANOS_SEED_PACKS`, or a sibling folder."""
    if explicit is not None:
        return explicit
    configured = os.environ.get(LIBRARY_ENV, "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / LIBRARY_DIRNAME


def value_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class SeedPack:
    """One pack's generated nouns and verb templates, read as data."""

    def __init__(self, root: Path, pack_id: str) -> None:
        folder = root / "packs" / pack_id
        nouns_path, verbs_path = folder / "nouns.json", folder / "verbs.json"
        if not nouns_path.is_file() or not verbs_path.is_file():
            raise SeedPackError(
                f"seed pack {pack_id!r} not found under {root}; set {LIBRARY_ENV} to a checkout "
                f"of {LIBRARY_DIRNAME}"
            )
        self.pack_id = pack_id
        nouns = load_json(nouns_path)
        verbs = load_json(verbs_path)
        self.records: dict[tuple[str, str], dict[str, Any]] = {
            (str(r["store"]), str(r["key"])): r for r in nouns["records"]
        }
        self.templates: dict[str, dict[str, Any]] = {
            str(t["brief"]["template_id"]): t["brief"] for t in verbs["tasks"]
        }

    def value(self, pin: Any, where: str, role: str) -> dict[str, Any]:
        if not isinstance(pin, dict) or set(pin) != PIN_FIELDS:
            raise SeedPackError(f"{where}: expected a NounRef pin {sorted(PIN_FIELDS)}")
        record = self.records.get((str(pin["store"]), str(pin["key"])))
        if record is None:
            raise SeedPackError(
                f"{where}: {pin['key']} is not a noun of seed pack {self.pack_id!r}"
            )
        if pin["version"] != 1:
            raise SeedPackError(
                f"{where}: seed pack nouns are create-only, so the pin is version 1"
            )
        value: dict[str, Any] = record["value"]
        digest = value_sha256(value)
        if digest != pin["value_sha256"]:
            raise SeedPackError(
                f"{where}: {pin['key']} changed in the library (value_sha256 {digest}, pinned "
                f"{pin['value_sha256']}); review the change and update the pin"
            )
        if value.get("role") != role:
            raise SeedPackError(f"{where}: expected a {role} noun, got {value.get('role')!r}")
        return value


def _steps(pack: SeedPack, kit: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for item in kit["step_map"]:
        template = pack.templates.get(str(item["verb"]))
        where = f"step {item['id']!r}"
        if template is None:
            raise SeedPackError(
                f"{where} names verb {item['verb']!r}, which the pack does not hold"
            )
        if template["title"] != item["title"]:
            raise SeedPackError(f"{where}: title differs from its verb template {item['verb']!r}")
        person_step = item["boundary"] == "human_only"
        if person_step != (template["claimant"] == "human"):
            raise SeedPackError(
                f"{where} is {item['boundary']} but its verb's claimant is {template['claimant']!r}"
            )
        steps.append(
            {
                "id": item["id"],
                "title": item["title"],
                "kind": item["step_kind"],
                "boundary": item["boundary"],
                "actor": item["actor"],
                "guidance": item["guidance"],
            }
        )
    return steps


def compose_bundle(
    bundle: dict[str, Any], *, root: Path | None = None, tracks_root: Path | None = None
) -> dict[str, Any]:
    """Build the request, draft and example request of a referenced example from its pack."""
    ref = bundle.get("seed_pack")
    if not isinstance(ref, dict) or set(ref) != {"pack_id", "kit", "request"}:
        raise SeedPackError("seed_pack names pack_id, kit and request")
    envelope = dict(bundle.get("request") or {})
    extra = set(envelope) - ENVELOPE_FIELDS
    if extra:
        raise SeedPackError(
            f"the example's request may hold only catalog fields; {sorted(extra)} come from the pack"
        )
    pack = SeedPack(library_root(root), str(ref["pack_id"]))
    kit = pack.value(ref["kit"], "seed_pack.kit", "kit")
    if kit.get("kit_format") != KIT_FORMAT:
        raise SeedPackError(f"seed_pack.kit: expected kit_format {KIT_FORMAT!r}")
    asked = pack.value(ref["request"], "seed_pack.request", "request")
    tests = pack.value(kit["test_cases"], "kit.test_cases", "test_cases")
    for name, noun in (("request", asked), ("test cases", tests)):
        if noun.get("content_kind") != "synthetic_example":
            raise SeedPackError(f"the pack's {name} must be marked as a synthetic example")
    track = get_track(str(envelope.get("track_id", "")), tracks_root)

    request = {
        **envelope,
        "title": kit["title"],
        "goal": kit["goal"],
        "target_org": kit["target_org"],
    }
    draft: dict[str, Any] = {
        "kit_id": envelope.get("kit_id"),
        "track_id": track.id,
        "domain": track.domain,
        "deliverable_kind": envelope.get("deliverable_kind", "full_kit"),
        **{name: envelope[name] for name in GOVERNANCE_FIELDS if name in envelope},
        "title": kit["title"],
        "summary": kit["summary"],
        "target_org": kit["target_org"],
        "steps": _steps(pack, kit),
        "skills": [
            {
                name: value[name]
                for name in ("name", "description", "boundary", "instructions", "refuses")
            }
            for value in (pack.value(pin, "kit.skills", "skill") for pin in kit["skills"])
        ],
        "tools": [
            {
                name: value[name]
                for name in ("name", "description", "input_schema", "output_fields", "read_only")
            }
            for value in (pack.value(pin, "kit.tools", "tool") for pin in kit["tools"])
        ],
        "artifacts": [
            {
                name: value[name]
                for name in ("name", "title", "artifact_format", "boundary", "summary", "spec")
            }
            for value in (pack.value(pin, "kit.files", "file") for pin in kit["files"])
        ],
        "checklist": pack.value(kit["checklist"], "kit.checklist", "checklist")["items"],
        "sources": pack.value(kit["sources"], "kit.sources", "sources")["sources"],
        "fixtures": [
            {name: case[name] for name in FIXTURE_FIELDS if name in case} for case in tests["cases"]
        ],
    }
    composed = {key: item for key, item in bundle.items() if key not in {"request", "seed_pack"}}
    composed["request"] = request
    composed["draft"] = draft
    composed["seed_pack"] = dict(ref)
    says = asked.get("says")
    if not isinstance(says, str) or not says.strip() or asked.get("mark") != "SYNTHETIC":
        raise SeedPackError(
            "the pack's request says what is needed in plain words and is marked SYNTHETIC"
        )
    composed["example_request"] = {
        "title": asked["title"],
        "says": says,
        "mark": asked["mark"],
        "noun": dict(ref["request"]),
    }
    return composed


def resolve_bundle(
    bundle: dict[str, Any], *, root: Path | None = None, tracks_root: Path | None = None
) -> dict[str, Any]:
    """A referenced example composed from its pack; an inline example unchanged."""
    if "seed_pack" not in bundle:
        return bundle
    return compose_bundle(bundle, root=root, tracks_root=tracks_root)


__all__ = [
    "KIT_FORMAT",
    "LIBRARY_DIRNAME",
    "LIBRARY_ENV",
    "SeedPack",
    "SeedPackError",
    "compose_bundle",
    "library_root",
    "resolve_bundle",
    "value_sha256",
]
