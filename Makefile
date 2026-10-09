-include .env
ENV_VARS = OLLAYA_HOST OLLAYA_MODEL PROFILE
$(foreach v,$(ENV_VARS),$(if $($(v)),,$(error $(v) not set -> cp .env.example .env)))
export $(ENV_VARS)
RUN = uv run python -m wsparql
PROFILE_FILES = VERSION tbox.ttl abox.ttl query-catalog.yaml tests/test-questions.yaml

.DEFAULT_GOAL := help
.PHONY: help install test clean build profile-check abox sparql tags-gen query-tags tags candidates select params ask demo eval eval-direct tags-cache ollaya-check ollaya-smoke-test

help: ## list targets
	@grep -E '^[a-z-]+:.*##' $(firstword $(MAKEFILE_LIST)) | awk -F':.*## ' '{printf "  %-20s %s\n", $$1, $$2}'

install: ## uv sync (creates .venv with rdflib + pyyaml)
	uv sync

test: ## offline unit tests (no Ollaya)
	@uv run python -m unittest discover -s tests

clean: ## drop the derived artefacts: $(PROFILE)/abox.ttl (make abox rebuilds it), profile/profile.db (tags, query tags, tag cache, eval results; make tags-gen query-tags tags-cache rebuild them, minutes on winnow) and __pycache__; keeps .venv
	rm -f $(PROFILE)/abox.ttl $(PROFILE)/../profile.db
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

build: abox tags-gen query-tags tags-cache ## build all derived artefacts in order: abox.ttl (ETL), then profile/profile.db tags (tags-gen), query tags (query-tags, Ollaya) and the question tag cache (tags-cache, Ollaya, minutes on winnow); then make eval

profile-check: ## mandatory profile files present in $(PROFILE); every catalog query has its .rq
	@for f in $(PROFILE_FILES); do test -f $(PROFILE)/$$f || { echo "MISSING $(PROFILE)/$$f"; exit 1; }; done
	@for q in $$(grep -oE '^  [a-z0-9-]+:' $(PROFILE)/query-catalog.yaml | tr -d ' :'); do \
	  test -f $(PROFILE)/queries/$$q.rq || { echo "MISSING $(PROFILE)/queries/$$q.rq (listed in query-catalog.yaml)"; exit 1; }; done
	@echo "profile $(notdir $(PROFILE)) $$(cat $(PROFILE)/VERSION) OK"

abox: ## ETL: build $(PROFILE)/abox.ttl from tbox.ttl + csv/*.csv (file = class, column = property, id = IRI local name, | separates values; the TBOX types the values); committed, rerun after editing a csv; no Ollaya
	@$(RUN) abox

sparql: profile-check ## run a catalog query on the ABOX: make sparql Q=q10-project-expenses-in-period ARGS="acronym=GRAPHIA from=2026-01-01 to=2026-06-30"; no ARGS = catalog example params; no Q = all queries, row counts only
	@$(RUN) sparql "$(Q)" $(ARGS)

tags-gen: profile-check ## derive the tag dictionary from tbox.ttl + abox.ttl (classes, TBOX individuals, datatype properties) plus fixed intent tags, store in profile/profile.db tags (deterministic: no run_id, rows of the profile version replaced); no Ollaya, instant. See GENERATE-TAGS-FROM-ONTOLOGY.md
	@$(RUN) tags-gen

query-tags: profile-check ## Ollaya assesses every tag of the dictionary against each catalog query description (one noul per tag), store {tag: prob} per query in profile/profile.db query_tags (new run_id); a query's tags = those >= 0.5 (seconds per query on winnow)
	@$(RUN) query-tags

tags: profile-check ## detect tags for a question with Ollaya: make tags Q="Which suppliers cost us the most?"; no Q = first tests/test-questions.yaml question
	@$(RUN) tags "$(Q)"

candidates: profile-check ## rank top 3 queries for Q; question tags from the last tags-cache run when Q is cached, else Ollaya; query tags from the last query-tags run. No Q = first tests/test-questions.yaml question
	@$(RUN) candidates "$(Q)"

select: profile-check ## rank candidates, then Ollaya picks the best query or none: make select Q="..."; no Q = first tests/test-questions.yaml question
	@$(RUN) select "$(Q)"

params: profile-check ## extract the query parameters found in Q (acronym: Ollaya choice over ABOX projects + none; from/to: regex on quarter, month, year): make params Q="List LUMEN expenses for Q1 2026"; no Q = working examples, every test question whose expected query takes parameters
	@$(RUN) params "$(Q)"

ask: profile-check ## answer Q end to end: tags, candidates, selected query (fallback: direct choice over the raw SPARQL when the tag route says none), parameters, result rows or "no suitable query": make ask Q="List LUMEN expenses for Q1 2026"; no Q = first tests/test-questions.yaml question
	@$(RUN) ask "$(Q)"

demo: profile-check ## make ask on every tests/test-questions.yaml question that has an expected_query, off-topic ones included (minutes on winnow)
	@$(RUN) demo

eval: profile-check ## full chain on every tests/test-questions.yaml question that has an expected_query, tags from the latest tags-gen / query-tags / tags-cache runs (fails if a question is not cached): expected query selected and returns rows, none answers "no suitable query"; rows stored in profile/profile.db eval_result; N/M with the direct fallback and for the tag route alone, exit 1 on any mismatch (minutes on winnow)
	@$(RUN) eval

eval-direct: profile-check ## baseline without tags: for each labeled tests/test-questions.yaml question one Ollaya choice over the raw SPARQL of all 10 queries + none, then parameters and run; N/M, exit 1 on any mismatch (minutes on winnow)
	@$(RUN) eval-direct

tags-cache: profile-check ## detect tags for every tests/test-questions.yaml question with Ollaya (needs make tags-gen), store in profile/profile.db (new run_id)
	@$(RUN) tags-cache

ollaya-check: ## prerequisites: uv, ollaya binary, server up, model pulled
	@command -v uv >/dev/null     || { echo "MISSING uv -> https://docs.astral.sh/uv/"; exit 1; }
	@command -v ollaya >/dev/null || { echo "MISSING ollaya -> curl -fsSL https://ollaya.dev/install.sh | sh"; exit 1; }
	@echo "uv      $$(uv --version)"
	@echo "ollaya  $$(ollaya -v)"
	@curl -sf http://$(OLLAYA_HOST)/ >/dev/null || { echo "server not reachable at $(OLLAYA_HOST) -> ollaya serve"; exit 1; }
	@ollaya list | grep -qE '^$(OLLAYA_MODEL)(:latest)?[[:space:]]' || { echo "model $(OLLAYA_MODEL) not pulled -> ollaya pull $(OLLAYA_MODEL)"; exit 1; }
	@echo "OK"

define SMOKE_PAYLOAD
{
  "model": "$(OLLAYA_MODEL)",
  "state": "Which European project has spent the most money?",
  "questions": {
    "expense":  {"type": "noul", "instructions": "The question concerns company expenses or costs"},
    "supplier": {"type": "noul", "instructions": "The question concerns a supplier or external provider"}
  }
}
endef
export SMOKE_PAYLOAD

define SMOKE_CHECK
import json, os, sys
THRESHOLD = 0.5
req = json.loads(os.environ["SMOKE_PAYLOAD"])
answers = json.load(sys.stdin)["answers"]
print("Results:")
for tag in req["questions"]:
    score = answers[tag]["noul"]
    print(f"      {'✓' if score > THRESHOLD else '·'} {tag:<10} {score:.2f}")
score = answers["expense"]["noul"]
if score <= THRESHOLD:
    sys.exit(f"SMOKE FAILED: expense tag not detected ({score:.2f} <= {THRESHOLD})")
endef
export SMOKE_CHECK

ollaya-smoke-test: ## one tag-detection query on /v1/systemone; fails if "expense" tag < 0.5
	@out=$$($(MAKE) -s ollaya-check 2>&1) || { echo "$$out"; exit 1; }
	@echo "Model: $(OLLAYA_MODEL)"
	@echo "Payload:"; echo "$$SMOKE_PAYLOAD"; echo
	@printf '%s' "$$SMOKE_PAYLOAD" | curl -sSf http://$(OLLAYA_HOST)/v1/systemone -d @- \
	| python3 -c "$$SMOKE_CHECK" \
	&& echo "SMOKE OK ✓"
