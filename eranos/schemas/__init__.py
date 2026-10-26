"""Domain records and track schemas for Eranos."""

from __future__ import annotations

from eranos.schemas.records import (
    BRIEF_ID,
    KIT_ID,
    AgentSkillSpec,
    EffectClass,
    KitDraft,
    KitRequest,
    MCPToolSpec,
    OwnerType,
    PublishedKit,
    ReviewDecision,
    SyntheticFixture,
    TaskBrief,
    VerificationReport,
    WorkflowStep,
)
from eranos.schemas.tracks import (
    HUMAN_ONLY_KINDS,
    TRACK_ID,
    AgentBoundary,
    OrgMandate,
    SourceRef,
    StepKind,
    TrackDomain,
    TrackPack,
)

__all__ = [
    "BRIEF_ID",
    "HUMAN_ONLY_KINDS",
    "KIT_ID",
    "TRACK_ID",
    "AgentBoundary",
    "AgentSkillSpec",
    "EffectClass",
    "KitDraft",
    "KitRequest",
    "MCPToolSpec",
    "OrgMandate",
    "OwnerType",
    "PublishedKit",
    "ReviewDecision",
    "SourceRef",
    "StepKind",
    "SyntheticFixture",
    "TaskBrief",
    "TrackDomain",
    "TrackPack",
    "VerificationReport",
    "WorkflowStep",
]
