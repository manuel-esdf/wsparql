OLLAYA_HOST  ?= 127.0.0.1:11435
OLLAYA_MODEL ?= winnow
PROFILE      ?= profile/eu-expense-poc
export OLLAYA_HOST OLLAYA_MODEL PROFILE
RUN = uv run python -m wsparql

.DEFAULT_GOAL := help
.PHONY: help install sparql sparql-all ollaya-check ollaya-smoke-test

help: ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-20s %s\n", $$1, $$2}'

install: ## uv sync (creates .venv with rdflib + pyyaml)
	uv sync

sparql: ## run one catalog query on the ABOX: make sparql Q=q01-total-expenses-by-project
	@$(RUN) sparql $(Q)

sparql-all: ## run all catalog queries, print row counts
	@$(RUN) sparql

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
