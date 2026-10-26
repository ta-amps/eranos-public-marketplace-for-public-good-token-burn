# Handoff

**Eranos** lets people donate unused AI tokens to build, test, and independently review off-the-shelf agent
skills, tools, files, and agentic processes that NGOs and public-good organizations can pick up and run right
away.

## Current state (verified Oct 26, 2026)

- **Three Tessera queues (`eq01`, `eq02`, `eq03`)** run end to end: scope check, donated-token build +
  deterministic verification + content-addressed blob, and independent review by a second contributor's tokens or
  human steward (`drafter != reviewer`) + atomic compare-and-set publish to `eranos.catalog` and `eranos.index`.
- **Six tracks** (`tracks/*/track.json`) span **Anti-Exploitation NGO Kits** (paired with Shamash) and
  **Everyday Nonprofit Operations Tools**.
- **Five example kits** (`examples/kits/*.json`) verify and publish cleanly via `make verify-examples`,
  including `KIT-HOTLINE-02` parking on Tessera for human helpline steward sign-off before resuming.
- **Web app (`web/`) and FastAPI (`eranos/api/app.py`)** serve the off-the-shelf catalog, autonomy maps,
  token-donation onboarding guide, tracks, and live queue counts on `:5174` / `:7720`.

## Open briefs (`briefs/E1.json` to `E4.json`)

- `E1`: Disaster charity registry & rental deposit escrow check kit (`05-housing-and-charity-verification.json`)
- `E2`: Field volunteer shift onboarding & incident escalation SOP kit (`06-volunteer-shift-sop.json`)
- `E3`: Reference JSON Schema fixture input validator in `eranos/verifier.py`
- `E4`: CLI bundle exporter (`SKILL.md` + `tool.json` + `checklist.md`)
