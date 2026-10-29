# Eranos. Run `make help` for the list. The optional conformance suite uses a Tessera checkout; runtime installation is pinned.
.DEFAULT_GOAL := help
SHELL := /bin/bash
BACKEND ?= local
API_PORT ?= 7720
WEB_PORT ?= 5174
TESSERA_DIR ?= ../tessera
SUITE ?= $(TESSERA_DIR)/conformance-draft

FACTORY_local := eranos.adapter.local:conformance_factory
FACTORY_tessera := tessera.testing:create_http_backend

.PHONY: help setup check lint types test public suite verify-examples donor-demo seed-requests web web-check snapshot api index index-check architecture

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

setup: ## Install Python and web dependencies (uv, pnpm)
	uv sync --all-groups
	@if [ -f web/package.json ]; then pnpm --dir web install; fi

check: lint types test public index-check architecture ## Lint, types, tests, leak scan, index and architecture checks

lint: ## ruff lint and format check
	uv run ruff check .
	uv run ruff format --check .

types: ## mypy strict on eranos/
	uv run mypy

test: ## Unit and integration tests
	uv run pytest -q

index: ## Rebuild INDEX.md, KEYWORDS.md, llms.txt and llms-full.txt from the files
	python3 scripts/build_index.py

index-check: ## Fail when the indexes are stale
	python3 scripts/build_index.py --check

public: ## Secret and private-name scan
	python3 scripts/check_public.py .

suite: ## Tessera's conformance suite through Eranos's adapter: make suite BACKEND=local|tessera
	TESSERA_BACKEND_FACTORY=$(FACTORY_$(BACKEND)) uv run pytest -q -p no:cacheprovider $(SUITE)

verify-examples: ## Run the two-step volunteer pipeline (spec -> draft -> independent review -> catalog)
	ERANOS_LOCAL_DB=$$(mktemp -d)/eranos.db uv run eranos verify-examples

donor-demo: ## Run two-donor (drafter != reviewer) kit synthesis & review over Tessera HTTP
	uv run eranos donor-demo

seed-requests: ## Seed open volunteer tasks onto Tessera so agents can claim work
	uv run eranos seed-requests

snapshot: ## Export the static snapshot data for the web app
	ERANOS_LOCAL_DB=$$(mktemp -d)/snapshot.db uv run eranos export-snapshot web/snapshot

web: ## API on :7720 and the web app on :5174
	@test -f .eranos/local.db || uv run eranos verify-examples
	uv run uvicorn eranos.api.app:app --port $(API_PORT) & pnpm --dir web dev --port $(WEB_PORT)

web-check: ## Type-check and build the web app
	pnpm --dir web exec tsc --noEmit
	pnpm --dir web build

api: ## Run the API alone on :7720
	@test -f .eranos/local.db || uv run eranos verify-examples
	uv run uvicorn eranos.api.app:app --port $(API_PORT)

architecture: ## architecture.json must match the code: paths, tests, layering rules
	python3 scripts/check_architecture.py . --summary
