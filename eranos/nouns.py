"""Eranos's page text, onboarding steps, starting brief, research rules and stand-in sources are
nouns. Their versioned source files live in `instructions/` and `examples/sources/`; `seed_nouns`
writes them to Tessera, and the surfaces render them from there (rule 12: no page-content copies).

`public_noun` is the one public lens the API and the Worker share: a noun is shown only when Eranos
produced it, it is public, it is not quarantined, and catalog entries are verified.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tessera import NotFound

from eranos.jsonfile import load_json

ROOT = Path(__file__).resolve().parents[1]
INSTRUCTIONS_STORE = "eranos.instructions"
SOURCES_STORE = "eranos.sources"
TEMPLATES_STORE = "eranos.verb_templates"
PRODUCER = "surface:eranos"
# Stores the generic noun read may show. The catalog keeps its own endpoint and cohort filters.
PUBLIC_STORES = frozenset(
    {
        "eranos.instructions",
        "eranos.plans",
        "eranos.requests",
        "eranos.solutions",
        "eranos.sources",
        "eranos.verb_templates",
    }
)


def instruction_nouns(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    return {p.stem: load_json(p) for p in sorted((root / "instructions").glob("*.json"))}


def source_nouns(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "examples" / "sources").glob("*.json")):
        for source in load_json(path)["sources"]:
            out[str(source["id"])] = source
    return out


# Examples of public research a nonprofit can ask for: the library's public-solution packs.
PUBLIC_RESEARCH_PACKS = ("policy-and-law-watch", "public-budget-report")


def verb_template_nouns(library: Path | None = None) -> dict[str, dict[str, Any]]:
    """The public-solution packs from the seed-pack library, read as given (proposals stay
    proposals: reading them writes, enqueues and activates nothing)."""
    from eranos.pipeline.seed_packs import library_root

    root = library_root(library)
    out: dict[str, dict[str, Any]] = {}
    for pack in PUBLIC_RESEARCH_PACKS:
        manifest = load_json(root / "packs" / pack / "manifest.json")
        verbs = load_json(root / "packs" / pack / "verbs.json")
        out[pack] = {
            "pack": pack,
            "pack_version": manifest["version"],
            "status": manifest["status"],
            "title": manifest["title"],
            "summary": manifest["summary"],
            "route": "public-only",
            "steps": [
                {"title": t["brief"]["title"], "claimant": t["brief"]["claimant"]}
                for t in verbs["tasks"]
            ],
            "source": {"library": root.name, "path": f"packs/{pack}"},
        }
    return out


def _upsert(backend: Any, store: str, key: str, value: Any, tags: list[str]) -> int:
    try:
        current = backend.get_record(store, key)
    except NotFound:
        current = None
    if current is not None and current.value == value and sorted(current.tags) == sorted(tags):
        return int(current.version)
    saved = backend.put_record(
        store,
        key,
        value,
        expected_version=current.version if current is not None else 0,
        producer_surface=PRODUCER,
        visibility_scope="public_commons",
        tags=tags,
    )
    return int(saved.version)


def seed_nouns(backend: Any, root: Path = ROOT) -> dict[str, int]:
    """Write the instruction and stand-in source nouns; unchanged nouns keep their version."""
    versions: dict[str, int] = {}
    for key, value in instruction_nouns(root).items():
        versions[f"{INSTRUCTIONS_STORE}/{key}"] = _upsert(
            backend, INSTRUCTIONS_STORE, key, value, ["kind:instructions", "status:verified"]
        )
    for key, value in source_nouns(root).items():
        tags = ["kind:public_source", "synthetic:true" if value.get("synthetic") else "kind:public"]
        versions[f"{SOURCES_STORE}/{key}"] = _upsert(backend, SOURCES_STORE, key, value, tags)
    for key, value in verb_template_nouns().items():
        tags = ["kind:verb_template", f"pack:{value['pack']}", f"route:{value['route']}"]
        versions[f"{TEMPLATES_STORE}/{key}"] = _upsert(backend, TEMPLATES_STORE, key, value, tags)
    return versions


SNAPSHOT_STORES = ("eranos.instructions", "eranos.sources", "eranos.verb_templates")


def export_nouns(backend: Any, target: Path) -> int:
    """Write the public nouns the pages read to `<target>/nouns/` for the offline snapshot.

    The files are an export of what Tessera holds, read back through the public lens, never a
    second source: the Worker serves Tessera first and falls back to them only when it cannot.
    """
    folder = target / "nouns"
    count = 0
    for store in SNAPSHOT_STORES:
        records = sorted(
            (r for r in backend.list_records(store, limit=100) if public_noun(r)),
            key=lambda r: str(r.key),
        )
        (folder / store).mkdir(parents=True, exist_ok=True)
        for stale in (folder / store).glob("*.json"):
            stale.unlink()
        rows = []
        for record in records:
            row = {"key": record.key, "version": record.version, "value": record.value}
            rows.append(row)
            item = {"synthetic": True, "store": store, **row}
            (folder / store / f"{record.key}.json").write_text(
                json.dumps(item, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            count += 1
        listing = {"synthetic": True, "store": store, "records": rows}
        (folder / f"{store}.json").write_text(
            json.dumps(listing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return count


def public_noun(record: Any) -> bool:
    tags = {str(t).lower() for t in record.tags}
    if record.namespace != "main" or record.visibility_scope != "public_commons":
        return False
    if "status:quarantined" in tags:
        return False
    if record.producer_surface != PRODUCER:
        return False
    return record.store != "eranos.catalog" or "status:verified" in tags
