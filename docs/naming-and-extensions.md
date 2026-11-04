# Naming, Mythology & Extending Eranos

## Why the surfaces and the infrastructure carry ancient civic names

The two public surfaces, Eranos and Agora, and the infrastructure under them, Teleion Fabric and the Teleion Fabric shim, are each named
for a concrete ancient practice that matches its exact technical boundary:

| Name | Origin | Meaning & Architectural Fit |
|---|---|---|
| **Eranos** (surface) | Ancient Greek (*ἔρανος*) | A mutual-aid civic potluck and interest-free solidarity association where each participant brings a spare share to equip a shared community need -- matching the two-sided marketplace where people donate spare AI capacity to build, test, and independently review agent kits for NGOs, nonprofits, and public-good groups. |
| **Agora** (surface) | Ancient Greek (*ἀγορά*) | The open public square where a city gathered and saw what was on offer -- matching the single overview of architecture and setup, use cases, connecting any agent, and contributing. |
| **Teleion Fabric** (infrastructure) | Classical Greek & Roman (*tessera*) | A single mosaic tile -- and also a clay or bone civic token used for entry and mutual recognition. Every task on the fabric is an atomic tile: claimed once under a fencing token, finished once, and sealed with a SHA-256 record. |
| **The Teleion Fabric shim** (infrastructure) | Classical Greek (*herma*) | An inscribed roadside waymarker carved with civic precepts and directions that travellers read on the way -- matching the infrastructure that connects agents to context and models. |

Everything else is nouns and verbs in seed packs, agent kits included, and seed packs take no names. Each pack in
the [pack library](https://github.com/ta-amps/seed-packs-library-of-nouns-and-verbs) is named only for what it does, for example a
collection of nouns and verbs for video and motion made with code. Home is not a surface; its address sends
people to Agora.

---

## Sibling mythological & legendary names (for forks or future surfaces)

Organizations or teams adapting this stack for specialized public-good surfaces can rebrand via
environment variables (`ERANOS_SURFACE_NAME`, `VITE_SURFACE_NAME`, `VITE_SURFACE_URL`) without editing
source code. Below are the sibling names explored during design:

### Craftsmen, Tool-Forgers & Builders
- **Ilmarinen** (Finnic *Kalevala*): The eternal hammerer who forges the *Sampo* -- a self-sustaining
  civic mill of grain, salt, and coin for the common good.
- **Hephaestus** (Greek) / **Vulcan** (Roman): Master builder of autonomous workshop tripods and tools
  that assist stewards without replacing human judgment.
- **Goibniu** (Irish/Celtic) / **Wayland** (Germanic): Legendary smiths of unbreakable, reliable craft.
- **Vishvakarma** (Vedic/Sanskrit -- *"All-Maker"*): Divine architect of public halls, tools, and
  standardized measures.
- **Lu Ban** (Chinese -- legendary carpenter-engineer): Patron of practical templates, modular jigs, and
  civilian relief engineering.

### Scribes, Ledgers, Granaries & Blueprints
- **Nisaba** (Sumerian/Mesopotamian): Goddess of reed-stylus writing, accounting tablets, fair boundary
  surveys, and public granaries.
- **Seshat** (Ancient Egyptian -- *"She Who Scribes"*): Keeper of blueprints, cord-stretching
  measurements, archives, and libraries who turns raw knowledge into buildable plans.
- **Thoth** (Egyptian) / **Nabu** (Babylonian): Guardians of exact records, translations, and checked
  citations.

### Social Justice, Shelter & Honest Weights
- **Nanshe** (Sumerian): Sister of Ningirsu and companion in justice to the sun god Utu; inspects weights
  and measures, protects widows, migrants, and orphans, and shelters refugees from debt bondage.
- **Ma'at** (Egyptian): Cosmic balance, truth, and calibrated feather-weight verification -- ideal for
  deterministic evaluation suites and twin-case benchmarks.
- **Themis** & **Dike** (Greek) / **Astraea** (Roman): Customary public order (*Themis*) and grounded
  human case-by-case justice (*Dike*).
- **Hestia** (Greek) / **Vesta** (Roman): Guardian of the civic hearth, sanctuary, and safe warm-handoff
  reception desks.

### Commons, Mutual Aid & Safe Passage
- **Xenia** (Greek) / **Hospitium** (Roman): Sacred duty of safe hospitality and protection for
  strangers and travellers.
- **Forum** (Roman): The open civic assembly; its Greek counterpart, *agora*, already names the public square.
- **Ayni** (Quechua / Andean) & **Minga** (Andean): Reciprocal community labor where neighbors pool
  effort to build shared infrastructure (bridges, storehouses, terraces).
- **Bayanihan** (Filipino) & **Yui** (Japanese): Collective neighborhood mutual aid -- directly resonant
  with migrant-worker and disaster-relief communities.
- **Hermes** (Greek) / **Iris** (Greek): Swift, faithful protocol routers and cross-language bridges
  (fitting MCP adapters and warm-referral handoffs).
- **Aegis** (Greek) / **Argus** (Greek): Protective origin shield (*Aegis*) and hundred-eyed watchman
  over queue leases and invariants (*Argus*).

---

## Maximum flexibility: adding domains, deliverables, and custom hostnames without code edits

1. **Any public-good domain (`domain` slug + `domain_label`)**:
   - Create `tracks/<your-track>/track.json` with any lowercase slug (`humanitarian_aid`,
     `civic_legal_aid`, `public_health`, `climate_resilience`, `anti_exploitation`, `nonprofit_ops`).
2. **Any combination of deliverables (`KitDraft`)**:
   - `skill` / `skills`: one or many `AgentSkillSpec` definitions
   - `tool` / `tools`: one or many read-only `MCPToolSpec` JSON Schema contracts
   - `artifacts`: standalone `CustomArtifactSpec` items (`markdown_sop`, `csv_template`,
     `open_referral_hsds`, `json_schema`, `rule_pack`, `checklist_pack`) for organizations that run
     zero-infrastructure spreadsheets or printed field playbooks
3. **Separate root domains OR shared-domain subdomains**:
   - Configure `CUSTOM_DOMAIN` in `deploy/hosting.env` + `routes` in `deploy/cloudflare/wrangler.jsonc`
     to bind either a dedicated domain (`eranos.org`) or subdomains (`eranos.example.org`,
     `tessera.example.org`), and pass `VITE_SURFACE_URL`, `VITE_SIBLING_URL`, and
     `VITE_TESSERA_URL` at build time.
