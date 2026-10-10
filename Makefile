-include .env
ENV_VARS = OLLAYA_HOST OLLAYA_MODEL PROFILE
$(foreach v,$(ENV_VARS),$(if $($(v)),,$(error $(v) not set -> cp .env.example .env)))
export $(ENV_VARS)
RUN = uv run python -m wsparql
PROFILE_FILES = VERSION tbox.ttl abox.ttl query-catalog.yaml tests/test-questions.yaml

.DEFAULT_GOAL := help
.PHONY: help install test clean build profile-check abox sparql expected query-selection param-extraction answer demo eval ollaya-check ollaya-smoke-test

help: ## list targets
	@grep -E '^[a-z-]+:.*##' $(firstword $(MAKEFILE_LIST)) | awk -F':.*## ' '{printf "  %-20s %s\n", $$1, $$2}'

install: ## uv sync (creates .venv with rdflib + pyyaml)
	uv sync

test: ## offline unit tests (no Ollaya)
	@uv run python -m unittest discover -s tests

clean: ## remove generated ABOX, evaluation database and Python caches; keeps .venv
	rm -f $(PROFILE)/abox.ttl $(PROFILE)/../profile.db
	find wsparql tests -name __pycache__ -type d -prune -exec rm -rf {} +

build: abox ## rebuild the ABOX from CSV data and ontology; no model preprocessing needed

profile-check: ## mandatory profile files present in $(PROFILE); every catalog query has its .rq
	@for f in $(PROFILE_FILES); do test -f $(PROFILE)/$$f || { echo "MISSING $(PROFILE)/$$f"; exit 1; }; done
	@for q in $$(grep -oE '^  q[0-9]+[a-z0-9-]*:' $(PROFILE)/query-catalog.yaml | tr -d ' :'); do \
	  test -f $(PROFILE)/queries/$$q.rq || { echo "MISSING $(PROFILE)/queries/$$q.rq (listed in query-catalog.yaml)"; exit 1; }; done
	@echo "profile $(notdir $(PROFILE)) $$(cat $(PROFILE)/VERSION) OK"

abox: ## ETL: build $(PROFILE)/abox.ttl from tbox.ttl + csv/*.csv (TBOX IRIs are opaque, rdfs:label is the name: file = class label, column = property label, id = IRI local name, | separates values; the TBOX types the values); committed, rerun after editing a csv; no Ollaya
	@$(RUN) abox

sparql: profile-check ## run a catalog query on the ABOX: make sparql Q=q10-project-expenses-in-period ARGS="acronym=GRAPHIA from=2026-01-01 to=2026-06-30"; no ARGS = catalog example params; no Q = all queries, row counts only
	@$(RUN) sparql "$(Q)" $(ARGS)

expected: profile-check ## run every $(PROFILE)/tests/expected.json case (catalog query + params) on the ABOX, compare the row count and that every expected value is among the returned cells; one line per case, exit 1 on any mismatch; no Ollaya
	@$(RUN) expected

query-selection: profile-check ## choose directly among all catalog SPARQL queries or none: make query-selection Q="..."
	@$(RUN) query-selection "$(Q)"

param-extraction: profile-check ## extract the query parameters found in Q (an ABOX value written in the question, else an Ollaya choice over the property's values + none; from/to: a named reporting period's dates, else regex on quarter, month, year): make param-extraction Q="List LUMEN expenses for Q1 2026"; no Q = working examples, every test question whose expected query takes parameters
	@$(RUN) param-extraction "$(Q)"

answer: profile-check ## select a catalog query directly, extract parameters and execute: make answer Q="List LUMEN expenses for Q1 2026"
	@$(RUN) answer "$(Q)"

demo: profile-check ## make answer on every tests/test-questions.yaml question that has an expected_query, off-topic ones included (minutes on winnow)
	@$(RUN) demo

eval: profile-check ## evaluate direct selection on all labeled questions, save a new SQLite run; exit 1 on any mismatch
	@$(RUN) eval

ollaya-check: ## prerequisites: uv, ollaya binary, server up, model pulled
	@command -v uv >/dev/null     || { echo "MISSING uv -> https://docs.astral.sh/uv/"; exit 1; }
	@command -v ollaya >/dev/null || { echo "MISSING ollaya -> curl -fsSL https://ollaya.dev/install.sh | sh"; exit 1; }
	@echo "uv      $$(uv --version)"
	@echo "ollaya  $$(ollaya -v)"
	@curl -sf http://$(OLLAYA_HOST)/ >/dev/null || { echo "server not reachable at $(OLLAYA_HOST) -> ollaya serve"; exit 1; }
	@ollaya list | grep -qE '^$(OLLAYA_MODEL)(:latest)?[[:space:]]' || { echo "model $(OLLAYA_MODEL) not pulled -> ollaya pull $(OLLAYA_MODEL)"; exit 1; }
	@echo "OK"

ollaya-smoke-test: ollaya-check profile-check ## run one direct selection against the configured profile
	@$(RUN) query-selection
