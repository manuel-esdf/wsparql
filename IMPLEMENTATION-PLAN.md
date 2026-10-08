# Implementation plan

Each step is one commit, adds one `make` target, and is testable by hand with the
command shown. Ollaya must be running (`make ollaya-check`) from step 2 on.

Stack: python ≥ 3.12, uv, rdflib (SPARQL on the ABOX in memory), pyyaml (profile
files), stdlib `urllib` for Ollaya (no SDK exists). One package `wsparql/`,
one CLI entry point `python -m wsparql <command> ...`, all wrapped by the Makefile.
`OLLAYA_HOST` / `OLLAYA_MODEL` are exported by the Makefile and read from the env.

Facts that shape the plan:
- Ollaya `/v1/systemone` has three question types: `noul` (probability a statement
  holds), `choice` (criteria = label→description, 2..255 options → `choice`,
  `confidence`, `probabilities`), `score`. It never generates or extracts free text.
- `q02` and `q10` have hard-coded `"LUMEN"` / Q1-2026 dates; they must become
  parameterised for the "extract parameters" stage. rdflib `initBindings` binds
  SPARQL variables without string templating.
- The TBOX has no subclass hierarchy today, so the README's "role of the ontology"
  cannot be exercised with current data; it is kept as an optional last step.

## Step 0 — done: Makefile, `ollaya-check`, `ollaya-smoke-test`

Commit e81241f.

## Step 1 — uv project + run catalog queries on the ABOX

Goal: prove the data layer. Load `tbox.ttl` + `abox.ttl` into an rdflib graph,
load `tags.yaml`, `query-catalog.yaml`, `tests/test-questions.yaml`, `queries/*.rq`.

Files:
- `pyproject.toml` (deps: rdflib, pyyaml), `.gitignore` (`.venv`, `__pycache__`; `uv.lock` kept)
- `wsparql/__init__.py`, `wsparql/profile.py` (`load(profile_dir)` → one object with
  `graph`, `tags`, `catalog`, `queries`, `test_questions`; `run(query_id, **bindings)` → rows)
- `wsparql/__main__.py` (argparse: `sparql <query-id>`)
- Makefile: `install` (`uv sync`), `sparql Q=<id>` (no Q = all, row counts), `PROFILE ?= profile/eu-expense-poc`
- `profile/<name>/VERSION` (semver) and Makefile `profile-check` (mandatory files + one `.rq` per catalog entry); `sparql`/`tags` depend on it

Manual test:

    make install
    make sparql Q=q01-total-expenses-by-project   # 3 rows, LUMEN first
    make sparql                                   # no Q: all 10 queries, each prints row count > 0

Commit: "Run catalog queries on the ABOX with rdflib"

## Step 2 — Ollaya client + tag detection

Goal: README stage "detect relevant tags with confidence scores".

Files:
- `wsparql/ollaya.py`: `decide(state, questions) -> answers` (POST `/v1/systemone`,
  urllib, env `OLLAYA_HOST`, `OLLAYA_MODEL`), `detect_tags(question, tags) -> {tag: prob}`
  (one `noul` question per tag, 19 tags in one call, sorted by prob desc)
- `__main__.py`: `tags "<question>"` prints `tag  prob` table
- Makefile: `tags Q="..."`
- `tags-cache` (added later): detects tags for every `tests/test-questions.yaml` question and
  caches them in `profile/profile.db` (git-ignored, shared by all profiles; `wsparql/cache.py`,
  sqlite3 table `tag_cache`, one `run_id` per `make tags-cache`)

Manual test:

    make tags Q="Which suppliers cost us the most?"
    # expect expense, supplier, ranking, total high (>0.5); travel, month low

Commit: "Detect tags with Ollaya noul questions"

## Step 3 — candidate queries by tag overlap (no Ollaya call)

Goal: README stage "identify the most relevant SPARQL queries". Pure Python:
score(query) = mean of detected probabilities over the query's catalog tags;
return top 3. Deterministic and explainable.

Files:
- `wsparql/pipeline.py`: `candidates(tag_probs, catalog, k=3) -> [(qid, score)]`
- `__main__.py`: `candidates "<question>"` prints tags then ranked candidates; tags come from
  the last `tags-cache` run when the question is cached (same profile, VERSION, model), else Ollaya
- `tests/test_offline.py` (unittest, no Ollaya): hand-made tag_probs → expected ranking
- Makefile: `candidates Q="..."`, `test` (`uv run python -m unittest`)

Manual test:

    make test
    make candidates Q="How much budget remains on each project?"
    # expect q05-budget-vs-spent ranked first

Commit: "Rank candidate queries by tag overlap"

## Step 4 — Ollaya selects the best candidate, or "no suitable query"

Goal: README stages "Ollaya selects the best candidate" + "no suitable query".
One `choice` question: criteria = `{qid: description}` for the top-3 candidates
plus `none: "None of these queries answers the question"`. Result = `none`,
or confidence < `MIN_CONFIDENCE` (0.4, module constant) → no suitable query.

Files:
- `pipeline.py`: `select(question, candidates, catalog) -> (qid | None, confidence, probabilities)`;
  tags come from the cache when the question is cached (as in `candidates`)
- `__main__.py`: `select "<question>"`, and `eval` (runs every `tests/test-questions.yaml`
  question that has an `expected_query`, catalog id or `none`: expected vs selected, `N/M`, exit 1 if any mismatch)
- Makefile: `select Q="..."`, `eval`

Manual test:

    make select Q="Show me the ineligible expenses"      # q06, confidence shown
    make select Q="What is the weather in Paris?"        # "no suitable query"
    make eval                                            # target M/M (one choice call per labeled question, tags from the cache)

Commit: "Select the best query with an Ollaya choice question"

## Step 5 — parameter extraction + parameterised queries

Goal: README stage "extract query parameters". Only q02 and q10 take parameters.

- Rewrite `q02` and `q10`: replace literal `"LUMEN"` by `?acronym`, dates by
  `?from` / `?to`; values are injected with rdflib `initBindings` (no templating).
- `query-catalog.yaml`: `params: {acronym: LUMEN}` (q02), `params: {acronym: LUMEN, from: ..., to: ...}` (q10);
  the example values are what the queries used to hard-code, `make sparql` without `ARGS` uses them.
- Extraction:
  - `acronym`: Ollaya `choice` over `SELECT DISTINCT ?acronym` from the ABOX + `none`.
  - `from`/`to`: regex for `Q[1-4] YYYY`, `YYYY-MM`, `YYYY`, month names
    (`# ponytail: regex; switch to an Ollaya choice over quarters/years if phrasing varies`).
  - A required param not found → "no suitable query (missing parameter X)".

Files: `pipeline.py` (`extract_period`, `extract_params`), `tests/test_offline.py` (date regex cases,
`initBindings` run on q10), `__main__.py`: `params "<question>"` (extracts every catalog-declared
parameter in isolation, no question = the test questions whose expected query takes parameters; step 6's `ask` extracts the selected query's ones), Makefile: `params Q="..."`, `sparql ... ARGS="k=v ..."`

Manual test:

    make test
    make params Q="List LUMEN expenses for Q1 2026"   # acronym=LUMEN from=2026-01-01 to=2026-03-31
    make params Q="How are GRAPHIA expenses distributed by cost category?"  # acronym=GRAPHIA, from/to -
    make sparql Q=q10-project-expenses-in-period ARGS="acronym=GRAPHIA from=2026-01-01 to=2026-06-30"   # 3 rows

Commit: "Extract query parameters and bind them at execution"

## Step 6 — end-to-end `ask` and demo

Goal: the "Expected demo" section of the README, in one command. Prints the six
blocks: question, tags + scores, candidates, selected query (+ confidence),
parameters, result rows (or the "no suitable query" message).

Files: `pipeline.py` (`ask(question) -> dict` chaining steps 2–5), `__main__.py`:
`ask "<question>"`, `demo` (the labeled test questions, including the off-topic ones),
`eval` extended to run the full chain and check the result is non-empty.
Makefile: `ask Q="..."`, `demo`.

Manual test:

    make ask Q="Which European project has spent the most money?"
    make demo
    make eval      # POC success criterion: M/M routed, `none` questions answered "no suitable query"

Commit: "End-to-end ask command and demo"

## Step 7 — docs

Update `README.md` with the Makefile usage (`make help` output) and the final
`make eval` score. Commit: "Document usage and eval results".

## Optional (only if a step above shows the need)

- **Ontology expansion**: use `rdfs:subClassOf` from the TBOX to add parent-class
  tags before ranking (README "role of the ontology"). Current TBOX has no
  subclass hierarchy, so there is nothing to exercise yet.
- **Faster model**: `ollaya pull laya:en` + `make OLLAYA_MODEL=laya:en eval`
  if winnow latency makes `eval` too slow for the demo.
- **Tag threshold / calibration**: if step 4 misroutes, tune `MIN_CONFIDENCE`
  or k; keep the numbers as module constants, no config file.

## Deliberately skipped

No external triple store (rdflib in memory is enough for 128 lines of ABOX),
no web UI, no text generation, no HTTP server, no config framework.
