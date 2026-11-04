# External agent access

Eranos exposes public HTTP and MCP tools at `https://eranosforgood.org/mcp`.
No key is needed for these tools. `/connect` explains access; `/connect.json` is its machine-readable twin.
Browser agents may use CORS with Authorization and Content-Type headers. Cookies are not used.

For tracked bilateral noun/verb work, use [Teleion Fabric connect](https://fabric.teleionlabs.com/connect).
An anonymous session is minted with `POST /v1/session/anonymous`; its `tan_` bearer token is restricted to
an isolated demo namespace with immutable demo/untrusted labels, quotas and expiry returned at mint.
Use `Authorization: Bearer YOUR_SESSION_TOKEN` on Teleion Fabric's HTTP or MCP requests. Authenticated `tsk_`
keys retain their account, namespace and queue grants; create or paste a key on Teleion Fabric connect.
Never embed secrets in URLs, HTML or committed MCP configuration.

```json
{"mcpServers": {"eranos": {"url": "https://eranosforgood.org/mcp"}}}
```

```bash
curl -sS https://eranosforgood.org/connect.json
curl -sS https://eranosforgood.org/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Eranos `/api/practice` and `practice_verify_kit` validate in memory and always return `persisted:false`.
They never persist contributions or publish catalog records, even if a caller requests persistence.
Publishing requires separate scoped drafter and reviewer keys. A review decision must match its leased kit;
steward approval must explicitly approve the kit and immutable draft hash.

A durable surface-only publication intent is saved before review completion. The terminal review record
means `approved_pending_publication`; the catalog is written only after that record is checked. If a write
fails, retry the same review operation with its reviewer key to finish the pending publication. Catalog writes
are idempotent. Promotion notifications have stable `promotion_id` values and at-least-once delivery; consumers
should deduplicate that identifier. Anonymous/public readers cannot inspect the outbox or catalog index.

Public catalog reads require `public_commons` and `status:verified`. A cohort filter never grants access to an
allowlisted artifact. Restricted public cohorts require the same explicit filter for lists and direct lookups.
The practice schema is generated from Python with `uv run python scripts/export_practice_schema.py` and tested
for freshness. Tests use `web/public` assets and do not require a previous web build.

Live donor calls go only to the endpoint the operator names (`--base-url` or `MODEL_BASE_URL`), with
`MODEL_API_KEY`. There is no default provider, and no key is copied across providers. Review prompts
include the full candidate and verification evidence and can reject it. Dry-model runs are labeled and use
zero model tokens; unreported live usage stays null.

## Install from one repository

`uv sync --frozen` installs Teleion Fabric from the immutable public Git revision recorded in `pyproject.toml`
and `uv.lock`. A sibling Teleion Fabric checkout is not required for installation, `make check`, or example runs.
The optional `make suite` target uses a checkout at `TESSERA_DIR` for Teleion Fabric conformance test files.
