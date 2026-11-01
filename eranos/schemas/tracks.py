"""Schema for public-good tracks (`tracks/<id>/track.json`). Pure Ring 0: stdlib and pydantic only."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from eranos.copy import check_non_accusatory, check_safe_topic

TRACK_ID = r"^[a-z][a-z0-9-]{2,47}$"
SLUG_ID = r"^[a-z][a-z0-9_]{2,39}$"

# Open slug types so organizations can add new public-good domains (e.g. humanitarian_aid,
# civic_legal_aid, public_health) and workflow step kinds purely in track JSON without code edits.
TrackDomain = Annotated[str, Field(pattern=SLUG_ID)]
StepKind = Annotated[str, Field(pattern=SLUG_ID)]
AgentBoundary = Literal["drafts", "assists", "human_only"]

HUMAN_ONLY_KINDS: frozenset[str] = frozenset(
    {
        "interview",
        "crisis_safety_plan",
        "legal_judgment",
        "individual_decision",
        "case_referral",
        "grant_signoff",
        "external_send",
    }
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceRef(_Strict):
    title: str = Field(min_length=3, max_length=240)
    url: str = Field(pattern=r"^https://")
    checked_date: date


class OrgMandate(_Strict):
    org_type: str = Field(min_length=3, max_length=120)
    serves: str = Field(min_length=3, max_length=240)
    mandate: str = Field(min_length=5, max_length=400)


class TrackPack(_Strict):
    id: Annotated[str, Field(pattern=TRACK_ID)]
    title: str = Field(min_length=4, max_length=140)
    domain: TrackDomain
    domain_label: str | None = Field(default=None, max_length=80)
    summary: str = Field(min_length=10, max_length=600)
    sister_area: str | None = (
        None  # optional pinned Shamash harm-area slug when fed by Shamash learnings
    )
    organizations: list[OrgMandate] = Field(min_length=1)
    allowed_artifacts: list[str] = Field(min_length=1)
    required_human_only: list[StepKind] = Field(min_length=1)
    never: list[str] = Field(min_length=1)
    sources: list[SourceRef] = Field(min_length=1)
    # Kits on a sensitive track wait for a person's sign-off after review, whoever built them.
    needs_steward_signoff: bool = False
    # Universal process class slug used when building local-execution process packages.
    process_class: Annotated[str, Field(pattern=SLUG_ID)] | None = None

    @field_validator("title", "summary")
    @classmethod
    def _clean_text(cls, value: str) -> str:
        return check_safe_topic(check_non_accusatory(value))
