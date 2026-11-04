# Donating Unused Tokens with OpenCode or Meta's Muse Models

Anyone with unused AI coding tokens or spare model capacity can connect an agent to
Eranos's scoped queues (`eq01` spec, `eq02` draft & self-test, `eq03` independent review) on
[Teleion Fabric](https://github.com/ta-amps/tessera-infrastructure-work-and-storage-engine) to build and verify agent kits for NGOs: seed packs of
nouns and verbs holding skills, read-only MCP tool definitions, operational SOPs, and practice-case
self-test fixtures. Eranos and Agora are the only public surfaces; Teleion Fabric and the Teleion Fabric shim are infrastructure.

## Two-donor safety model (`drafter != reviewer`)

No single agent or key can both draft and approve a kit:

1. **Donor 1 (`eq01`, `eq02` only)** claims a `KitRequest`, drafts the workflow steps, skills,
   tool definitions, checklists, and practice-case fixtures, runs `eranos.verifier.verify_kit`, writes the
   canonical SHA-256 blob, and submits the draft record.
2. **Donor 2 (`eq03` only, distinct worker ID and distinct Teleion Fabric key ID)** claims the downstream
   review tile, deterministically re-verifies every `human_only` boundary and practice-case fixture,
   and publishes atomically into `eranos.catalog` via compare-and-set (`put_record`).
3. **Standard mode only**: `eranos.donor_worker.check_donor_model` refuses any `-contributor` tier
   model string before a network call is made.

## Run the bilateral two-donor demo

Offline deterministic mode (CI and air-gapped environments):

```bash
make donor-demo
# or: uv run eranos donor-demo
```

Live bilateral mode calls only the OpenAI-compatible endpoint you name; there is no default provider.
For Meta's Model API, use a Muse model at standard tier:

```bash
MODEL_API_KEY="$(cat ~/.config/eranos/model_key)" \
  uv run eranos donor-demo --live --base-url "$MODEL_BASE_URL" --model muse-spark-1.3
```

The command boots an isolated Teleion Fabric HTTP/MCP service, issues separate scoped keys for
`opencode-donor-01` (`eq01`, `eq02`) and `volunteer-reviewer-02` (`eq03`), verifies that
`opencode-donor-01` is HTTP-403 blocked from claiming `eq03`, builds and verifies
`KIT-DONOR-90`, runs independent review, and prints the CAS catalog version, blob SHA-256,
and Teleion Fabric record hash.

## Connect OpenCode directly over MCP (`/mcp`)

Point OpenCode (`opencode.json`) at Teleion Fabric `/mcp` endpoint with a scoped volunteer key:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "meta-api": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Meta Model API",
      "options": {
        "baseURL": "{env:MODEL_BASE_URL}",
        "apiKey": "{env:MODEL_API_KEY}"
      },
      "models": {
        "muse-spark-1.3": {
          "name": "muse-spark-1.3",
          "tool_call": true
        }
      }
    }
  },
  "mcp": {
    "eranos-fabric": {
      "type": "remote",
      "url": "http://127.0.0.1:8787/mcp",
      "headers": {
        "Authorization": "Bearer {env:TESSERA_VOLUNTEER_KEY}"
      },
      "enabled": true
    }
  }
}
```

With a `queues=["eq02"]` key, OpenCode can call `queues`, `claim`, `register_job`, `put_blob`, and
`submit` to donate spare tokens toward open `briefs/*.json` requests without ever holding `eq03`
review or `eranos.catalog` write authority.
