"""Queue definitions for Eranos's volunteer pipeline on Tessera (`eq01`, `eq02`, `eq03`)."""

from __future__ import annotations

from dataclasses import dataclass

from tessera import QueueConfig


@dataclass(frozen=True)
class StageSpec:
    queue: str
    node: str
    title: str
    effect_class: str
    purpose: str


STAGES: tuple[StageSpec, ...] = (
    StageSpec(
        queue="eq01",
        node="spec",
        title="Scope & safety gate",
        effect_class="read",
        purpose="Check track alignment, required human_only steps, and safe-topic rules before drafting.",
    ),
    StageSpec(
        queue="eq02",
        node="draft",
        title="Volunteer agent draft & deterministic checks",
        effect_class="write-internal",
        purpose="One volunteer agent builds the kit, fixtures, skill, and MCP tool spec; verifier runs.",
    ),
    StageSpec(
        queue="eq03",
        node="review",
        title="Independent review & CAS catalog publish",
        effect_class="write-internal",
        purpose="A different agent or human steward (drafter != reviewer) audits and publishes to eranos.catalog.",
    ),
)

QUEUE_LABELS: tuple[tuple[str, str], ...] = (
    ("eq01", "Scope"),
    ("eq02", "Draft + check"),
    ("eq03", "Independent review"),
)

QUEUE_CONFIGS: tuple[QueueConfig, ...] = (
    QueueConfig(name="eq01", lease_seconds=600, heartbeat_seconds=60, miss_limit=3),
    QueueConfig(name="eq02", lease_seconds=1800, heartbeat_seconds=60, miss_limit=3),
    QueueConfig(name="eq03", lease_seconds=1800, heartbeat_seconds=60, miss_limit=3),
)
