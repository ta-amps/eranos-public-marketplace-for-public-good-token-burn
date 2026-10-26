"""Domain records for Eranos kits, agent skills, MCP tool specs, custom operational artifacts,
review decisions, and task briefs. Pure Ring 0: stdlib and pydantic only."""

from __future__ import annotations

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

KIT_ID = r"^[A-Z]{2,4}-[A-Z0-9]{2,8}-[0-9]{2}$"
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


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


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
        if info.field_name == "sample_input" and "SYNTHETIC" not in value:
            raise ValueError("every sample_input must carry a visible SYNTHETIC mark")
        return value


class KitRequest(_Record):
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


class KitDraft(_Record):
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


class PublishedKit(_Record):
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
