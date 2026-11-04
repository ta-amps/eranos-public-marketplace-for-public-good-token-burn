"""Domain records for Eranos kits, agent skills, MCP tool specs, custom operational artifacts,
review decisions, and task briefs. Pure Ring 0: stdlib and pydantic only."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eranos.copy import check_non_accusatory, check_safe_topic
from eranos.schemas.tracks import (
    HUMAN_ONLY_KINDS,
    SLUG_ID,
    TRACK_ID,
    AgentBoundary,
    SourceRef,
    StepKind,
    TrackDomain,
)
from eranos.visible import has_example_mark

KIT_ID = r"^[A-Z]{2,4}-[A-Z0-9]{2,8}-[0-9]{2}$"
# A visible mark that a test case is made up. New packages use MADE-UP (the owner asked that public
# packages never use the older word); the older mark stays accepted for existing example kits.
FIXTURE_MARKS: tuple[str, ...] = (
    "Practice case: an example, not a real person or case",
    "MADE-UP",
    "SYNTHETIC",
)
BRIEF_ID = r"^[A-Z][0-9]{1,3}$"
EffectClass = Literal["read", "write-internal", "write-repo", "public"]
OwnerType = Literal["claude-code", "muse-code", "muse-assistant", "human"]
DeliverableKind = Annotated[str, Field(pattern=SLUG_ID)]
ArtifactFormat = Literal[
    "json_schema",
    "markdown_sop",
    "csv_template",
    "open_referral_hsds",
    "rule_pack",
    "checklist_pack",
]
VisibilityScope = Literal["surface_only", "allowlist_surfaces", "public_commons"]

OPEN_SPDX_ALLOWLIST: frozenset[str] = frozenset(
    {
        "Apache-2.0",
        "MIT",
        "BSD-3-Clause",
        "CC-BY-4.0",
        "CC0-1.0",
    }
)
DEFAULT_PRODUCER_SURFACE = "surface:eranos"
DEFAULT_ALLOWED_SURFACES: tuple[str, ...] = (
    "surface:eranos",
    "surface:herma",
    "surface:kothar",
)

_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,31}:[A-Za-z0-9][A-Za-z0-9_./-]{0,63}$")
_COHORT_RE = re.compile(r"^[a-z0-9][a-z0-9_:-]{1,63}$")
_SURFACE_RE = re.compile(r"^surface:[a-z0-9][a-z0-9_-]{1,39}$")


def validate_spdx_license(value: str) -> str:
    cleaned = value.strip()
    if cleaned not in OPEN_SPDX_ALLOWLIST:
        allowed = ", ".join(sorted(OPEN_SPDX_ALLOWLIST))
        raise ValueError(f"spdx_license {value!r} must be in open SPDX allowlist ({allowed})")
    return cleaned


def normalize_tag(tag: str) -> str:
    raw = tag.strip()
    if ":" not in raw:
        raise ValueError(f"tag {tag!r} must follow normalized 'key:value' format")
    key, val = raw.split(":", 1)
    norm = f"{key.strip().lower()}:{val.strip()}"
    if not _TAG_RE.match(norm):
        raise ValueError(f"tag {tag!r} contains invalid characters; expected 'key:value'")
    check_safe_topic(check_non_accusatory(norm))
    return norm


def normalize_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in tags:
        norm = normalize_tag(item)
        if norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def validate_cohorts(cohorts: list[str]) -> list[str]:
    if not cohorts:
        raise ValueError("target_cohorts must specify at least one cohort (e.g. ['all'])")
    out: list[str] = []
    seen: set[str] = set()
    for item in cohorts:
        cleaned = item.strip().lower()
        if not _COHORT_RE.match(cleaned):
            raise ValueError(f"invalid cohort identifier {item!r}")
        check_safe_topic(check_non_accusatory(cleaned))
        if cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out


def validate_surface_id(surface: str) -> str:
    cleaned = surface.strip()
    if not _SURFACE_RE.match(cleaned):
        raise ValueError(f"surface identifier {surface!r} must match 'surface:<slug>'")
    check_safe_topic(check_non_accusatory(cleaned))
    return cleaned


def validate_allowed_surfaces(surfaces: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in surfaces:
        cleaned = validate_surface_id(item)
        if cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _GovernedRecord(_Record):
    spdx_license: str = "Apache-2.0"
    tags: list[str] = Field(default_factory=list)
    target_cohorts: list[str] = Field(default_factory=lambda: ["all"])
    producer_surface: str = DEFAULT_PRODUCER_SURFACE
    visibility_scope: VisibilityScope = "public_commons"
    allowed_surfaces: list[str] = Field(default_factory=lambda: list(DEFAULT_ALLOWED_SURFACES))

    @field_validator("spdx_license")
    @classmethod
    def _check_spdx(cls, value: str) -> str:
        return validate_spdx_license(value)

    @field_validator("tags")
    @classmethod
    def _check_tags(cls, value: list[str]) -> list[str]:
        return normalize_tags(value)

    @field_validator("target_cohorts")
    @classmethod
    def _check_cohorts(cls, value: list[str]) -> list[str]:
        return validate_cohorts(value)

    @field_validator("producer_surface")
    @classmethod
    def _check_producer_surface(cls, value: str) -> str:
        return validate_surface_id(value)

    @field_validator("allowed_surfaces")
    @classmethod
    def _check_allowed_surfaces(cls, value: list[str]) -> list[str]:
        return validate_allowed_surfaces(value)

    @model_validator(mode="after")
    def _check_allowlist_scope(self) -> _GovernedRecord:
        if self.visibility_scope == "allowlist_surfaces" and not self.allowed_surfaces:
            raise ValueError(
                "allowed_surfaces must not be empty when visibility_scope='allowlist_surfaces'"
            )
        return self


class WorkflowStep(_Record):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,39}$")
    title: str = Field(min_length=3, max_length=140)
    kind: StepKind
    boundary: AgentBoundary
    actor: str = Field(min_length=3, max_length=120)
    guidance: str = Field(min_length=5, max_length=500)

    @field_validator("title", "guidance")
    @classmethod
    def _clean(cls, value: str) -> str:
        return check_safe_topic(check_non_accusatory(value))

    @model_validator(mode="after")
    def _enforce_human_only(self) -> WorkflowStep:
        if self.kind in HUMAN_ONLY_KINDS and self.boundary != "human_only":
            raise ValueError(
                f"step '{self.id}' of kind '{self.kind}' must keep boundary='human_only' (got {self.boundary!r})"
            )
        return self


class AgentSkillSpec(_Record):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{2,47}$")
    description: str = Field(min_length=10, max_length=300)
    boundary: Literal["drafts", "assists"]
    instructions: str = Field(min_length=20, max_length=4000)
    refuses: list[str] = Field(min_length=1)

    @field_validator("description", "instructions")
    @classmethod
    def _clean(cls, value: str) -> str:
        return check_safe_topic(check_non_accusatory(value))


class MCPToolSpec(_Record):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,47}$")
    description: str = Field(min_length=10, max_length=300)
    input_schema: dict[str, Any]
    output_fields: list[str] = Field(min_length=1)
    read_only: bool = True

    @field_validator("description")
    @classmethod
    def _clean(cls, value: str) -> str:
        return check_safe_topic(check_non_accusatory(value))

    @model_validator(mode="after")
    def _valid_json_schema_and_read_only(self) -> MCPToolSpec:
        if not self.read_only:
            raise ValueError("MCPToolSpec.read_only must be True for public-good catalog tools")
        if self.input_schema.get("type") != "object" or "properties" not in self.input_schema:
            raise ValueError(
                "MCPToolSpec.input_schema must be a JSON Schema object with properties"
            )
        return self


class CustomArtifactSpec(_Record):
    """Flexible deliverable unit (SOP playbook, HSDS directory schema, intake template, CSV formula
    pack, or red-flag indicator pack) so volunteer agents are not limited to one rigid shape."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,47}$")
    title: str = Field(min_length=4, max_length=140)
    artifact_format: ArtifactFormat
    boundary: Literal["drafts", "assists"] = "drafts"
    summary: str = Field(min_length=10, max_length=400)
    spec: dict[str, Any] | list[str] | str

    @field_validator("title", "summary")
    @classmethod
    def _clean(cls, value: str) -> str:
        return check_safe_topic(check_non_accusatory(value))


class SyntheticFixture(_Record):
    id: str = Field(pattern=r"^FX-[A-Z0-9-]{2,24}$")
    scenario: str = Field(min_length=5, max_length=240)
    sample_input: str = Field(min_length=10, max_length=2000)
    expected_indicators: list[str] = Field(default_factory=list)
    expected_human_escalation: bool

    @field_validator("scenario", "sample_input")
    @classmethod
    def _clean_and_synthetic(cls, value: str, info: Any) -> str:
        check_safe_topic(check_non_accusatory(value))
        if info.field_name == "sample_input" and not has_example_mark(value):
            raise ValueError("every sample_input must carry the practice-case mark")
        return value


class KitRequest(_GovernedRecord):
    kit_id: Annotated[str, Field(pattern=KIT_ID)]
    track_id: Annotated[str, Field(pattern=TRACK_ID)]
    deliverable_kind: DeliverableKind = "full_kit"
    title: str = Field(min_length=5, max_length=140)
    goal: str = Field(min_length=10, max_length=600)
    target_org: str = Field(min_length=3, max_length=140)
    needs_steward_signoff: bool = False

    @field_validator("title", "goal")
    @classmethod
    def _clean(cls, value: str) -> str:
        return check_safe_topic(check_non_accusatory(value))


class ModelHook(_Record):
    """A kit ships no model: no model file, model download, tuned adapter or local model service.
    The agent that uses the kit runs it with its own model, as process packages do."""

    default: Literal["none"] = "none"
    uses: Literal["your own agent's model"] = "your own agent's model"


class KitDraft(_GovernedRecord):
    kit_id: Annotated[str, Field(pattern=KIT_ID)]
    track_id: Annotated[str, Field(pattern=TRACK_ID)]
    domain: TrackDomain
    deliverable_kind: DeliverableKind = "full_kit"
    title: str = Field(min_length=5, max_length=140)
    summary: str = Field(min_length=15, max_length=600)
    target_org: str = Field(min_length=3, max_length=140)
    steps: list[WorkflowStep] = Field(min_length=2)
    skill: AgentSkillSpec | None = None
    skills: list[AgentSkillSpec] = Field(default_factory=list)
    tool: MCPToolSpec | None = None
    tools: list[MCPToolSpec] = Field(default_factory=list)
    artifacts: list[CustomArtifactSpec] = Field(default_factory=list)
    checklist: list[str] = Field(min_length=3)
    sources: list[SourceRef] = Field(min_length=1)
    fixtures: list[SyntheticFixture] = Field(min_length=2)
    drafted_by: str = Field(min_length=2, max_length=80)
    drafted_by_key: str = Field(min_length=2, max_length=80)
    model_hook: ModelHook = Field(default_factory=ModelHook)

    def all_skills(self) -> list[AgentSkillSpec]:
        out: list[AgentSkillSpec] = []
        if self.skill is not None:
            out.append(self.skill)
        out.extend(s for s in self.skills if all(x.name != s.name for x in out))
        return out

    def all_tools(self) -> list[MCPToolSpec]:
        out: list[MCPToolSpec] = []
        if self.tool is not None:
            out.append(self.tool)
        out.extend(t for t in self.tools if all(x.name != t.name for x in out))
        return out

    @field_validator("title", "summary")
    @classmethod
    def _clean(cls, value: str) -> str:
        return check_safe_topic(check_non_accusatory(value))

    @field_validator("checklist")
    @classmethod
    def _clean_list(cls, items: list[str]) -> list[str]:
        return [check_safe_topic(check_non_accusatory(item)) for item in items]

    @model_validator(mode="after")
    def _validate_deliverables_and_human_floor(self) -> KitDraft:
        if not any(step.boundary == "human_only" for step in self.steps):
            raise ValueError("every kit must declare at least one human_only workflow step")
        if not (self.all_skills() or self.all_tools() or self.artifacts):
            raise ValueError(
                "every submission must provide at least one skill, MCP tool, or custom operational artifact"
            )
        return self


class VerificationReport(_Record):
    kit_id: Annotated[str, Field(pattern=KIT_ID)]
    passed: bool
    checks_run: list[str]
    issues: list[str] = Field(default_factory=list)
    fixture_count: int = Field(ge=0)
    human_only_steps: list[str] = Field(default_factory=list)


class ReviewDecision(_Record):
    kit_id: Annotated[str, Field(pattern=KIT_ID)]
    verdict: Literal["approved", "needs_revision", "park_for_steward"]
    reviewed_by: str = Field(min_length=2, max_length=80)
    reviewed_by_key: str = Field(min_length=2, max_length=80)
    notes: str = Field(min_length=5, max_length=500)

    @field_validator("notes")
    @classmethod
    def _clean(cls, value: str) -> str:
        return check_safe_topic(check_non_accusatory(value))


_GOVERNANCE_FIELDS = (
    "spdx_license",
    "tags",
    "target_cohorts",
    "producer_surface",
    "visibility_scope",
    "allowed_surfaces",
)


class PublishedKit(_GovernedRecord):
    kit: KitDraft
    verification: VerificationReport
    reviewed_by: str = Field(min_length=2, max_length=80)
    reviewed_by_key: str = Field(min_length=2, max_length=80)
    review_notes: str = Field(min_length=5, max_length=500)
    steward_signoff: str | None = None
    draft_receipt: str | None = None
    review_receipt: str | None = None
    blob_sha256: str | None = None
    catalog_version: int = Field(ge=1, default=1)
    review_task_id: str | None = None
    draft_task_id: str | None = None
    draft_sha256: str | None = None
    drafter_key_id: str | None = None
    reviewer_key_id: str | None = None
    publication_sha256: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _inherit_governance_from_kit(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        raw_kit = data.get("kit")
        if isinstance(raw_kit, KitDraft):
            kit_map = raw_kit.model_dump(mode="python")
        elif isinstance(raw_kit, dict):
            kit_map = raw_kit
        else:
            return data
        merged = dict(data)
        for field_name in _GOVERNANCE_FIELDS:
            if field_name not in merged and field_name in kit_map:
                merged[field_name] = kit_map[field_name]
        return merged

    @model_validator(mode="after")
    def _enforce_independent_review(self) -> PublishedKit:
        if not self.verification.passed:
            raise ValueError("unverified kits cannot be published to the catalog")
        if self.reviewed_by == self.kit.drafted_by:
            raise ValueError(
                f"two-step rule violated: reviewer {self.reviewed_by!r} also drafted {self.kit.kit_id}"
            )
        if self.reviewed_by_key == self.kit.drafted_by_key:
            raise ValueError(
                f"two-step rule violated: reviewer key {self.reviewed_by_key!r} matches drafter key"
            )
        if self.visibility_scope == "surface_only" or self.kit.visibility_scope == "surface_only":
            raise ValueError("quarantined surface_only drafts cannot be published to the catalog")
        if "status:quarantined" in self.tags or "status:quarantined" in self.kit.tags:
            raise ValueError("quarantined drafts cannot be published to the catalog")
        return self


class TaskBrief(_Record):
    schema_version: Literal[1] = 1
    task_id: Annotated[str, Field(pattern=BRIEF_ID)]
    repo: str = Field(pattern=r"^[a-z][a-z0-9-]{2,47}$")
    title: str = Field(min_length=5, max_length=140)
    kind: str = Field(min_length=2, max_length=40)
    owner_type: OwnerType
    effect_class: EffectClass
    branch: str = Field(min_length=3, max_length=120)
    depends_on: list[str] = Field(default_factory=list)
    context: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    done_when: str = Field(min_length=5, max_length=400)
    notes: str | None = None

    @model_validator(mode="after")
    def _no_agent_public_effects(self) -> TaskBrief:
        if self.owner_type != "human" and self.effect_class == "public":
            raise ValueError("an agent brief may never hold the public effect class")
        return self
