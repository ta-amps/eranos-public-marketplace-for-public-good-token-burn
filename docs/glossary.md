# Glossary

- **Eranos:** Ancient Greek mutual-aid gathering where each participant contributes a spare share; here, one of
  exactly two public surfaces: the two-sided marketplace where people donate spare AI capacity and their agents
  build and review agent kits for nonprofits. Agora, the single overview, is the other surface; Tessera and Herma
  are infrastructure; everything else is nouns and verbs in seed packs.
- **Agent kit:** A seed pack of nouns and verbs generated for one NGO's agent, not a separate kind of thing. A
  noun can hold an agent's whole setup, including the harness, the model and the files in its working directory.
- **AgentBoundary (`drafts` | `assists` | `human_only`):** Declares how far an agent may go on each workflow
  step. Interviews, crisis safety plans, individual decisions, and external sends must always be `human_only`.
- **TrackPack (`tracks/<id>/track.json`):** Data file defining a nonprofit need, who it serves, required
  `human_only` steps, lines never crossed, and cited primary sources.
- **KitDraft / PublishedKit:** A structured package holding workflow steps, an `AgentSkillSpec`, a read-only
  `MCPToolSpec` JSON Schema, a checklist, sources, and `SYNTHETIC` fixtures -- published into `eranos.catalog`
  only after independent review.
