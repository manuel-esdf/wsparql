# wsparql

POC evaluating https://ollaya.dev/ for routing natural-language questions to predefined SPARQL queries.

## Goal

Allow a user to ask a question in natural language and automatically select the most relevant predefined SPARQL query to execute on a knowledge graph.
The system does not generate SPARQL.
It only chooses among trusted, existing queries, extracts their parameters from the question, and answers "no suitable query" when nothing fits.

## Input

Everything the system knows lives in one profile directory (`PROFILE` in `.env`, currently `profile/eu-expense-poc`, see its [README](profile/eu-expense-poc/README.md)):

- a TBOX ontology describing the domain (`tbox.ttl`);
- an ABOX dataset containing the actual data (`abox.ttl`);
- a catalog of predefined SPARQL queries (`query-catalog.yaml`: description, tags, parameters with example values; `queries/*.rq`);
- a controlled dictionary of tags describing concepts and user intentions (`tags.yaml`);
- test questions with the expected query (`tests/test-questions.yaml`).

## Decision process

| Stage | Command | How |
|---|---|---|
| Natural language question | `make ask Q="..."` | |
| Detect relevant tags with Ollaya | `make tags` | one `noul` question per tag in a single `/v1/systemone` call, probability per tag |
| Identify the most relevant SPARQL queries | `make candidates` | pure Python: mean detected probability over each query's catalog tags, top 3 |
| Ollaya selects the best candidate | `make select` | one `choice` question over the 3 candidate descriptions plus `none`; `none` or confidence below 0.4 = no suitable query |
| Extract query parameters | `make params` | `acronym`: `choice` over the ABOX project acronyms plus `none`; `from`/`to`: regex on quarter, month name or year |
| Execute SPARQL on the ABOX | `make sparql` | rdflib in memory, parameters bound with `initBindings` (no templating) |
| Return the result | `make ask` | the six demo blocks below, or "no suitable query" / "no suitable query (missing parameter X)" |

Ollaya only decides (probabilities, choices); it never generates or extracts free text.

## Technical stack

- python ≥ 3.12, uv, rdflib, pyyaml; stdlib `urllib` for Ollaya, stdlib `sqlite3` for the local cache
- one Makefile to centralize all tasks (`make` lists them)
- `cp .env.example .env` then set `OLLAYA_HOST`, `OLLAYA_MODEL`, `PROFILE` (all required, no defaults; `.env` is gitignored)

## Setup

    cp .env.example .env     # OLLAYA_HOST=127.0.0.1:11435, OLLAYA_MODEL=winnow, PROFILE=profile/eu-expense-poc
    make install             # uv sync
    make ollaya-check        # uv, ollaya binary, server up, model pulled
    make ollaya-smoke-test   # one tag-detection call
    make test                # offline unit tests, no Ollaya

## Usage

`make help`:

    help                 list targets
    install              uv sync (creates .venv with rdflib + pyyaml)
    test                 offline unit tests (no Ollaya)
    profile-check        mandatory profile files present in $(PROFILE); every catalog query has its .rq
    sparql               run a catalog query on the ABOX: make sparql Q=q10-project-expenses-in-period ARGS="acronym=GRAPHIA from=2026-01-01 to=2026-06-30"; no ARGS = catalog example params; no Q = all queries, row counts only
    tags                 detect tags for a question with Ollaya: make tags Q="Which suppliers cost us the most?"; no Q = first tests/test-questions.yaml question
    candidates           rank top 3 queries for Q; tags from the last tags-cache run when Q is cached, else Ollaya. No Q = first tests/test-questions.yaml question
    select               rank candidates, then Ollaya picks the best query or none: make select Q="..."; no Q = first tests/test-questions.yaml question
    params               extract the query parameters found in Q (acronym: Ollaya choice over ABOX projects + none; from/to: regex on quarter, month, year): make params Q="List LUMEN expenses for Q1 2026"; no Q = working examples, every test question whose expected query takes parameters
    ask                  answer Q end to end: tags, candidates, selected query, parameters, result rows or "no suitable query": make ask Q="List LUMEN expenses for Q1 2026"; no Q = first tests/test-questions.yaml question
    demo                 make ask on every tests/test-questions.yaml question that has an expected_query, off-topic ones included (minutes on winnow)
    eval                 full chain on every tests/test-questions.yaml question that has an expected_query, tags from the latest tags-cache run_id (fails if a question is not cached): expected query selected and returns rows, none answers "no suitable query"; rows stored in profile/profile.db eval_result; N/M, exit 1 on any mismatch (minutes on winnow)
    tags-cache           detect tags for every tests/test-questions.yaml question with Ollaya, store in profile/profile.db (new run_id)
    ollaya-check         prerequisites: uv, ollaya binary, server up, model pulled
    ollaya-smoke-test    one tag-detection query on /v1/systemone; fails if "expense" tag < 0.5

Example, `make ask Q="List LUMEN expenses for Q1 2026"`:

    Q: List LUMEN expenses for Q1 2026
    tags: cache run_id 1
    tag         prob
    time        1.00
    date-range  1.00
    expense     1.00
    category    0.94
    list        0.92
    budget      0.81

    candidate                       score  prob  description
    q10-project-expenses-in-period  0.80   0.94  List project expenses within a date range
    q06-ineligible-expenses         0.70   0.00  List expenses marked as ineligible
    q02-project-expense-breakdown   0.53   0.00  Break down a project's expenses by cost category
    none                                   0.05  no suitable query
    selected: q10-project-expenses-in-period (confidence 0.93)

    param    value       how
    acronym  LUMEN       Ollaya choice over 3 ABOX projects + none, confidence 0.99
    from     2026-01-01  regex: quarter, month name or year in the question
    to       2026-03-31  regex: quarter, month name or year in the question

    result: 6 rows
    expense  description                          date        amount
    ex:E001  Alice - January personnel cost       2026-01-31  8200.00
    ...

Each stage has its own command (`tags`, `candidates`, `select`, `params`, `sparql`) to inspect it in isolation.

## Tag cache and evaluation

Tag detection is the slow call (19 `noul` questions, seconds to tens of seconds per question on `winnow`), so
`make tags-cache` detects the tags of every test question once and stores them in `profile/profile.db`
(SQLite, gitignored, table `tag_cache`, one `run_id` per run, keyed by profile, question, model and profile `VERSION`).
`candidates`, `select`, `ask` and `demo` use the last cached run when the question is cached, Ollaya otherwise.

`make eval` routes every test question that has an `expected_query` (catalog id or `none`) through the full chain:
the expected query must be selected and return rows, `none` questions must get "no suitable query".
It reads the tags of one `run_id` only (never Ollaya) and stores one row per (profile, q_id, run_id) in table
`eval_result`, replaced on each run, so an eval is reproducible for a given `run_id` and the summary line says
whether it matches the previous one.

Current score on `profile/eu-expense-poc` with `winnow`, run_id 1: **34/40** (19 ambiguous questions are unlabeled and skipped).
All 7 off-topic questions are answered "no suitable query" and every correctly selected query returns rows, including the
parameterised ones. The 6 misses are in-domain questions where the selection `choice` picks `none` with high confidence
(for example "Compare travel costs between LUMEN and GRAPHIA.", "What is the budget of each European project?"): the question
names an entity while the catalog descriptions are generic. Next lever: the wording of the `none` criterion and of the
selection instructions in `wsparql/pipeline.py`.

## Role of the Ontology

The TBOX provides additional semantic knowledge.

For example, if Researcher is a subclass of Person, the system can use this relationship during query selection without asking the AI model to rediscover it.

Not exercised yet: the current TBOX has no subclass hierarchy, so there is nothing to expand before ranking (see IMPLEMENTATION-PLAN.md, optional steps).

## Expected Demo

`make ask Q="..."` (one question) and `make demo` (every labeled test question) show:

- the user question;
- the detected tags and confidence scores;
- the candidate SPARQL queries;
- the selected query;
- the extracted parameters;
- the final result returned from the ABOX.

The system must also be able to answer "no suitable query" when no predefined query matches the question.

## POC Success Criteria

The POC is successful if it demonstrates that natural-language questions can be reliably routed to predefined SPARQL queries while keeping the execution layer controlled, explainable and testable.

## Repository layout

- `Makefile`, `.env.example`, `pyproject.toml`, `uv.lock`
- `wsparql/`: `ollaya.py` (HTTP client, `decide`, `detect_tags`), `profile.py` (profile loader, `run` with bindings), `pipeline.py` (`candidates`, `select`, `extract_period`, `extract_params`, `answer`), `db.py` (`tag_cache`, `eval_result`), `__main__.py` (CLI behind the Makefile)
- `profile/eu-expense-poc/`: the profile (see its README); `profile/profile.db`: local cache, gitignored
- `tests/test_offline.py`: unit tests without Ollaya (`make test`)
- `IMPLEMENTATION-PLAN.md`: the 7 steps, one commit each

Deliberately skipped: external triple store, web UI, text generation, HTTP server, config framework.
