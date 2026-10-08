OLLAYA_HOST  ?= 127.0.0.1:11435
OLLAYA_MODEL ?= winnow
PROFILE      ?= profile/eu-expense-poc
export OLLAYA_HOST OLLAYA_MODEL PROFILE
RUN = uv run python -m wsparql
PROFILE_FILES = VERSION tbox.ttl abox.ttl tags.yaml query-catalog.yaml demo-questions.yaml tests/tag-questions.csv

.DEFAULT_GOAL := help
.PHONY: help install profile-check sparql tags tags-test ollaya-check ollaya-smoke-test

help: ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-20s %s\n", $$1, $$2}'

install: ## uv sync (creates .venv with rdflib + pyyaml)
	uv sync

profile-check: ## mandatory profile files present in $(PROFILE); every catalog query has its .rq
	@for f in $(PROFILE_FILES); do test -f $(PROFILE)/$$f || { echo "MISSING $(PROFILE)/$$f"; exit 1; }; done
	@for q in $$(grep -oE '^  [a-z0-9-]+:' $(PROFILE)/query-catalog.yaml | tr -d ' :'); do \
	  test -f $(PROFILE)/queries/$$q.rq || { echo "MISSING $(PROFILE)/queries/$$q.rq (listed in query-catalog.yaml)"; exit 1; }; done
	@echo "profile $(notdir $(PROFILE)) $$(cat $(PROFILE)/VERSION) OK"

sparql: profile-check ## run a catalog query on the ABOX (make sparql Q=q01-total-expenses-by-project); no Q = all queries, row counts only
	@$(RUN) sparql $(Q)

tags: profile-check ## detect tags for a question with Ollaya: make tags Q="Which suppliers cost us the most?"
	@$(RUN) tags "$(Q)"

tags-test: profile-check ## run every tests/tag-questions.csv question, append results to $(PROFILE)/profile.db
	@$(RUN) tags-test

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
