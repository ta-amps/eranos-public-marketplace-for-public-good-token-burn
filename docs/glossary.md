# Glossary

- **Eranos:** Ancient Greek mutual-aid gathering where each participant contributes a spare share; here, the
  public-good surface where people contribute spare AI agent runs to build verified nonprofit tools.
- **AgentBoundary (`drafts` | `assists` | `human_only`):** Declares how far an agent may go on each workflow
  step. Interviews, crisis safety plans, individual decisions, and external sends must always be `human_only`.
- **TrackPack (`tracks/<id>/track.json`):** Data file defining a nonprofit need, who it serves, required
  `human_only` steps, lines never crossed, and cited primary sources.
- **KitDraft / PublishedKit:** A structured package holding workflow steps, an `AgentSkillSpec`, a read-only
  `MCPToolSpec` JSON Schema, a checklist, sources, and `SYNTHETIC` fixtures -- published into `eranos.catalog`
  only after independent review.
