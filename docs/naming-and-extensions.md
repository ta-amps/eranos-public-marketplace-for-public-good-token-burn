# Naming, Mythology & Extending Eranos

## Why the three projects carry ancient civic and mythological names

Each surface in this stack is named for a concrete ancient practice or guardian figure that matches its
exact technical boundary:

| Repo / Surface | Origin | Meaning & Architectural Fit |
|---|---|---|
| **Tessera** | Classical Greek & Roman (*tessera*) | A single mosaic tile — and also a clay or bone civic token used for entry and mutual recognition. Every task on the fabric is an atomic tile: claimed once under a fencing token, finished once, and sealed with a SHA-256 receipt. |
| **Shamash** | Mesopotamian (*Šamaš* / Sumerian *Utu*) | The sun-judge who sees across borders, condemns false weights and ruinous lending, and protects travellers on the road — matching cross-document and payment arithmetic verification without reckless accusation. |
| **Eranos** | Ancient Greek (*ἔρανος*) | A mutual-aid civic potluck and interest-free solidarity association where each participant brings a spare share to equip a shared community need — matching contributors donating spare AI agent runs to build verified tools for nonprofits and NGOs. |

---

## Sibling mythological & legendary names (for forks, future surfaces, or domain packs)

Organizations or teams adapting this stack for specialized public-good surfaces can rebrand via
environment variables (`ERANOS_SURFACE_NAME`, `VITE_SURFACE_NAME`, `VITE_SURFACE_URL`) without editing
source code. Below are the sibling names explored during design:

### Craftsmen, Tool-Forgers & Builders
- **Kothar** (*Kothar-wa-Khasis*, Ugaritic/Canaanite — *"Skillful and Wise"*): The divine smith and
  architect who forges named, precision instruments to push back chaos and exploitation.
- **Ilmarinen** (Finnic *Kalevala*): The eternal hammerer who forges the *Sampo* — a self-sustaining
  civic mill of grain, salt, and coin for the common good.
- **Hephaestus** (Greek) / **Vulcan** (Roman): Master builder of autonomous workshop tripods and tools
  that assist stewards without replacing human judgment.
- **Goibniu** (Irish/Celtic) / **Wayland** (Germanic): Legendary smiths of unbreakable, reliable craft.
- **Vishvakarma** (Vedic/Sanskrit — *"All-Maker"*): Divine architect of public halls, tools, and
  standardized measures.
- **Lu Ban** (Chinese — legendary carpenter-engineer): Patron of practical templates, modular jigs, and
  civilian relief engineering.

### Scribes, Ledgers, Granaries & Blueprints
- **Nisaba** (Sumerian/Mesopotamian): Goddess of reed-stylus writing, accounting tablets, fair boundary
  surveys, and public granaries; direct Mesopotamian counterpart to **Shamash**.
- **Seshat** (Ancient Egyptian — *"She Who Scribes"*): Keeper of blueprints, cord-stretching
  measurements, archives, and libraries who turns raw knowledge into buildable plans.
- **Thoth** (Egyptian) / **Nabu** (Babylonian): Guardians of exact records, translations, and verified
  citations.

### Social Justice, Shelter & Honest Weights
- **Nanshe** (Sumerian): Sister of Ningirsu and companion in justice to Utu/Shamash; inspects weights
  and measures, protects widows, migrants, and orphans, and shelters refugees from debt bondage.
- **Ma'at** (Egyptian): Cosmic balance, truth, and calibrated feather-weight verification — ideal for
  deterministic evaluation suites and twin-case benchmarks.
- **Themis** & **Dike** (Greek) / **Astraea** (Roman): Customary public order (*Themis*) and grounded
  human case-by-case justice (*Dike*).
- **Hestia** (Greek) / **Vesta** (Roman): Guardian of the civic hearth, sanctuary, and safe warm-handoff
  reception desks.

### Commons, Mutual Aid & Safe Passage
- **Xenia** (Greek) / **Hospitium** (Roman): Sacred duty of safe hospitality and protection for
  strangers and travellers.
- **Agora** (Greek) / **Forum** (Roman): Open civic assembly and public catalog of shared tools.
- **Ayni** (Quechua / Andean) & **Minga** (Andean): Reciprocal community labor where neighbors pool
  effort to build shared infrastructure (bridges, storehouses, terraces).
- **Bayanihan** (Filipino) & **Yui** (Japanese): Collective neighborhood mutual aid — directly resonant
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
     to bind either dedicated domains (`eranos.org`, `shamash.org`) or subdomains (`eranos.example.org`,
     `shamash.example.org`, `tessera.example.org`), and pass `VITE_SURFACE_URL`, `VITE_SIBLING_URL`, and
     `VITE_TESSERA_URL` at build time.
