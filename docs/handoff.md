# Handoff

## Integration checkpoint, October 29, 2026

The reviewed release is merged into `main`. The tested implementation revision is
`92d54425cc5ac2969508e9ca213fd1608d9ef4e0`; [its GitHub checks](https://github.com/ta-amps/eranos-public-marketplace-for-public-good-token-burn/actions/runs/40873435007) passed.
Fresh builds matched the deployed Worker executable exactly.

56 tests passed. Example kit verification, local fabric conformance (30 passed, six skipped), and the production web build passed.

The installed dependency now pins merged Teleion Fabric. Contributors execute scoped work; shared kit publication retains the distinct-reviewer and steward gates. Unattended live donor spending is not enabled by this integration.

Follow the [worker-first policy](WORKER-FIRST-EXECUTION.md): independently
schedulable reasoning is a claimed verb; inputs, contracts, artifacts and evidence
are scoped nouns. Workers reason and self-check. Authentication, leases, CAS,
types and records stay deterministic. Server inference is an explicitly
configured, scoped and bounded exception. Missing capacity or invalid input does
not enable it automatically.

The earlier inventory below is dated history. These checks cover the recorded
implementations and fixtures; they are not universal harness, load or rendered-UI
certification.

## Earlier handoff

> Note, October 29, 2026: this dated section predates the current model, in which Eranos and Agora are the only public surfaces, Teleion Fabric and the Teleion Fabric shim are infrastructure, and everything else, agent kits included, is nouns and verbs in seed packs; the exploitation and scam surface it pairs with is archived, and its nouns and verbs are now a pack in the [pack library](https://github.com/ta-amps/seed-packs-library-of-nouns-and-verbs).

**Eranos** lets people donate unused AI tokens to build, test, and independently review off-the-shelf agent
skills, tools, files, and agentic processes that NGOs and public-good organizations can pick up and run right
away.

## Current state (checked Oct 26, 2026)

- **Three Teleion Fabric queues (`eq01`, `eq02`, `eq03`)** run end to end: scope check, donated-token build +
  deterministic verification + content-addressed blob, and independent review by a second contributor's tokens or
  human steward (`drafter != reviewer`) + atomic compare-and-set publish to `eranos.catalog` and `eranos.index`.
- **Six tracks** (`tracks/*/track.json`) span **Anti-Exploitation NGO Kits** (paired with Shamash) and
  **Everyday Nonprofit Operations Tools**.
- **Five example kits** (`examples/kits/*.json`) verify and publish cleanly via `make verify-examples`,
  including `KIT-HOTLINE-02` parking on Teleion Fabric for human helpline steward sign-off before resuming.
- **Web app (`web/`) and FastAPI (`eranos/api/app.py`)** serve the off-the-shelf catalog, autonomy maps,
  token-donation onboarding guide, tracks, and live queue counts on `:5174` / `:7720`.

## Open briefs (`briefs/E1.json` to `E4.json`)

- `E1`: Disaster charity registry & rental deposit escrow check kit (`05-housing-and-charity-verification.json`)
- `E2`: Field volunteer shift onboarding & incident escalation SOP kit (`06-volunteer-shift-sop.json`)
- `E3`: Reference JSON Schema fixture input validator in `eranos/verifier.py`
- `E4`: CLI bundle exporter (`SKILL.md` + `tool.json` + `checklist.md`)
