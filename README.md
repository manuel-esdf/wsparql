# wsparql

POC evaluating https://ollaya.dev/ for routing natural-language questions to predefined SPARQL queries.

## Goal

Allow a user to ask a question in natural language and automatically select the most relevant predefined SPARQL query to execute on a knowledge graph.
The system does not generate SPARQL.
It only chooses among trusted, existing queries, extracts their parameters from the question, and answers "no suitable query" when nothing fits.

## Documentation

- [docs/ARCHITECTURE-OVERVIEW.md](docs/ARCHITECTURE-OVERVIEW.md): the chain in seven small diagrams, for a demonstration
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): the same chain in detail, how each artefact and table is generated
- [docs/GENERATE-ABOX.md](docs/GENERATE-ABOX.md): the ETL from `csv/*.csv` + `tbox.ttl` to `abox.ttl`
- [docs/GENERATE-TAGS-FROM-ONTOLOGY.md](docs/GENERATE-TAGS-FROM-ONTOLOGY.md): the tag dictionary and the query tags

## Input

Everything the system knows lives in one profile directory (`PROFILE` in `.env`); `make PROFILE=profile/c3po <target>`
runs any target on another one. Two profiles exist:

- `profile/eu-expense-poc` (1.5.0): synthetic company expenses, 10 queries, 109 test questions ([README](profile/eu-expense-poc/README.md));
- `profile/c3po` (1.2.0): the cost reporting of one H2020 project on the C3PO ontology, 13 parameterised queries,
  29 competency questions ([README](profile/c3po/README.md)).

A profile holds:

- a TBOX ontology describing the domain (`tbox.ttl`, opaque IRIs, `rdfs:label` is the name, `rdfs:comment` the tag description);
- CSV source files with the business data (`csv/*.csv`, one file per class), from which `make abox` derives the ABOX (`abox.ttl`, committed);
- a catalog of predefined SPARQL queries (`query-catalog.yaml`: one competency question per query, parameters with example values; `queries/*.rq`);
- test questions with the expected query (`tests/test-questions.yaml`) and, optionally, expected rows per query (`tests/expected.json`).

The tag dictionary is not written by hand: it is derived from the ontology, and the tags of each query are detected by
Ollaya on the query's competency question. Both live in `profile/profile.db`.

## Decision process

| Stage | Command | How |
|---|---|---|
| Tag dictionary (once per profile version) | `make ontology-tags-gen` | rules on `tbox.ttl` + `abox.ttl`: classes with data, TBOX individuals, boolean/numeric/date properties, fixed intents; no Ollaya |
| Query tags (once per profile version) | `make cq-tag-assessment` | one `noul` question per tag on each competency question; a query's tags = probability ≥ 0.5 |
| Detect the question's tags | `make tags` | one `noul` question per tag in a single `/v1/systemone` call |
| Rank the queries | `make query-ranking` | pure Python: mean detected probability over each query's tags, top 5 |
| Select a query | `make query-selection` | one `choice` over the 5 candidates' competency questions plus `none`; `none` or confidence < 0.4 = no suitable query |
| Fallback when that answer is `none` | `make answer` | one more `choice` over the SPARQL of every catalog query (labels in place of the opaque IRIs) plus `none`; its answer is final |
| Extract parameters | `make param-extraction` | an ABOX value written in the question, else a `choice` over the property's values plus `none`; `from`/`to`: a reporting period named in the question, else regex on quarter, month or year; an optional parameter not found leaves its variable free |
| Execute | `make sparql` | rdflib in memory, parameters bound with `initBindings` (no templating) |
| Answer end to end | `make answer Q="..."` | the blocks below, or "no suitable query" / "no suitable query (missing parameter X)" |

Ollaya only decides (probabilities, choices); it never generates or extracts free text.

## Technical stack

- python ≥ 3.12, uv, rdflib, pyyaml; stdlib `urllib` for Ollaya, stdlib `sqlite3` for `profile/profile.db`
- one Makefile for all tasks (`make` lists them with their full description)
- `cp .env.example .env` then set `OLLAYA_HOST`, `OLLAYA_MODEL`, `PROFILE` (all required, no defaults; `.env` is gitignored)

## Setup

    cp .env.example .env     # OLLAYA_HOST=127.0.0.1:11435, OLLAYA_MODEL=winnow, PROFILE=profile/eu-expense-poc
    make install             # uv sync
    make ollaya-check        # uv, ollaya binary, server up, model pulled
    make ollaya-smoke-test   # one tag-detection call
    make test                # offline unit tests, no Ollaya
    make build               # abox -> ontology-tags-gen -> cq-tag-assessment -> question-tag-assessment (minutes on winnow)
    make eval                # routing score

## Usage

| Group | Targets |
|---|---|
| Setup and checks | `install`, `test`, `ollaya-check`, `ollaya-smoke-test`, `profile-check` |
| Derived artefacts | `build` = `abox`, `ontology-tags-gen`, `cq-tag-assessment`, `question-tag-assessment`; `clean` drops them |
| Data, no Ollaya | `sparql Q=<id> ARGS="k=v ..."`, `expected` (compare with `tests/expected.json`) |
| One stage at a time | `tags`, `query-ranking`, `query-selection`, `param-extraction` (each takes `Q="..."`, default: the first test question) |
| End to end | `answer Q="..."`, `demo` (every labeled test question) |
| Evaluation | `eval` (stored in `question_eval`), `eval-direct` (baseline without tags, printed only) |

Example, `make answer Q="List LUMEN expenses for Q1 2026"` (captured on eu-expense-poc 1.3.0; the candidate texts are
the 1.5.0 competency questions):

    Q: List LUMEN expenses for Q1 2026
    tags: cache run_id 3
    tag               prob
    time              1.00
    date-range        1.00
    expense           1.00
    expense-category  0.94
    list              0.92
    budget            0.81

    candidate                       score  prob  competency question
    q06-ineligible-expenses         0.77   0.00  Which expenses are marked as ineligible?
    q10-project-expenses-in-period  0.75   0.96  Which project expenses fall within a date range?
    q09-monthly-expenses            0.52   0.00  What are the monthly expense totals?
    none                                   0.04  no suitable query
    selected: q10-project-expenses-in-period (confidence 0.94)

    param    value       how
    acronym  LUMEN       named in the question
    from     2026-01-01  regex: quarter, month name or year in the question
    to       2026-03-31  regex: quarter, month name or year in the question

    result: 6 rows
    expense  description                          date        amount
    ex:E001  Alice - January personnel cost       2026-01-31  8200.00
    ...

## Tag cache and evaluation

Tag detection is the slow call (one `noul` per tag, seconds to tens of seconds per question on `winnow`), so
`make question-tag-assessment` detects the tags of every test question once and stores them in `profile/profile.db`
(table `question_tag_assessment`, one `run_id` per run, keyed by profile, question, model and `VERSION`).
`query-ranking`, `query-selection`, `answer` and `demo` use the latest cached run when the question is cached, Ollaya otherwise.

`make eval` routes every test question that has an `expected_query` (catalog id or `none`) through the full chain:
the expected query must be selected and return rows, `none` questions must get "no suitable query". It reads the tags
of one `run_id` only (never Ollaya for tags), stores one row per (profile, q_id, run_id) in `question_eval` and says
whether the result matches the previous eval of that `run_id`. It prints two scores: with the direct fallback, and for
the tag route alone. Bump `VERSION` when the ontology, the CSV data or the catalog change.

### Current score

With `winnow`:

| profile | version | labeled questions | with fallback | tag route alone | `eval-direct` |
|---|---|---|---|---|---|
| eu-expense-poc | 1.4.0 (catalog descriptions) | 87 (73 in-domain, 14 `none`) | **86/87** | 76/87 | 80/87 |
| eu-expense-poc | 1.5.0 (competency questions) | 87 | not measured yet | | |
| c3po | 1.1.0 (catalog descriptions) | 29 (all in-domain) | **27/29** | 26/29 | 27/29 |
| c3po | 1.2.0 (competency questions) | 29 | **27/29** (`question_eval` run_ids 2 and 3) | printed by `make eval`, not stored | not measured |

Remaining misses:

- eu-expense-poc 1.4.0: "Show the personnel expenditure for OPENSCIENCE." (expected q02): both routes answer `none`;
  "personnel" reads as the employee query.
- c3po 1.2.0: "What is the total travel cost for ERP1 for the project FAIR-IMPACT?" goes to the travel events query
  (0.50) instead of the expenditure per reporting period; "List all ERP of project FAIR-IMPACT." gets `none` (0.92):
  `european-reporting-period` is detected too weakly and the all-projects query leads the candidates.

### What moved the score

- **Wording is the tuning surface.** A competency question that names many concepts collects many tags, and the plain
  mean of `pipeline.candidates` dilutes it out of the top candidates. Rewording toward "of each European project" or
  listing every category cost questions every time it was tried. IDF weighting did not help.
- **Top 5 candidates instead of 3**, and "computes or contains among its rows" in the `none` instruction of both
  choices: tag route 71 → 76/87 on eu-expense-poc. The selection instruction also says that the queries are templates
  whose parameters are filled in afterwards; without it, questions naming a project got `none`.
- **Fallback.** The tag route's misses are `none` answers, so one more choice over the SPARQL of the whole catalog
  recovers them; a wrong selection would be final. The two routes miss different questions, which is why combined
  they beat either alone. The weak spot is an off-topic question about SPARQL ("Write a SPARQL query to list all
  suppliers.", `none` at 0.73).
- **Opaque IRIs.** The fallback reads `Profile.readable`: the `.rq` text with each TBOX IRI replaced by its label
  (`ex:P14` → `ex:amount`); reading the opaque text as-is cost one answer. Indentation and blank lines are dropped so
  the 29 queries of c3po 1.0.0 fit winnow's 8192-token context; the PREFIX lines stay (dropping them cost 3 answers). A
  bigger catalog needs a fallback that reads fewer queries.
- **Merged queries with optional parameters** (c3po 1.1.0): sibling queries that differed only by a filter confused
  both routes; merging them into 13 queries fixed those four misses.
- **Tried, not adopted:** object-property tags (relations hold on every row, they do not discriminate), an acronym hint
  in the `european-project` description, the catalog description prepended to the SPARQL, `#` comments in the `.rq` files.

The tag stage buys explainability (the tag and candidate tables) and a choice over 5 short competency questions instead
of every full query, which is what matters once the catalog outgrows one `choice`.

## Role of the ontology

The TBOX provides semantic knowledge the model does not have to rediscover:

- it is the schema of the ETL (`make abox`): classes, properties and value types come from it;
- it is the source of the tag dictionary (`make ontology-tags-gen`): classes, TBOX individuals and datatype properties
  become tags, their `rdfs:comment` is the instruction Ollaya reads; a class counts the individuals of its subclasses
  (c3po: `employee` = internal + external employees);
- its labels name the opaque IRIs in the SPARQL the fallback reads.

Not exercised: ranking does not expand a detected child tag to its parent classes.

## Expected demo

`make answer Q="..."` (one question) and `make demo` (every labeled test question) show:

- the user question;
- the detected tags and confidence scores;
- the candidate SPARQL queries;
- the selected query;
- the extracted parameters;
- the final result returned from the ABOX.

The system must also be able to answer "no suitable query" when no predefined query matches the question.

## POC success criteria

The POC is successful if it demonstrates that natural-language questions can be reliably routed to predefined SPARQL queries while keeping the execution layer controlled, explainable and testable.

## Repository layout

- `Makefile`, `.env.example`, `pyproject.toml`, `uv.lock`
- `wsparql/`: `etl.py` (CSV + TBOX → ABOX), `tags.py` (tag dictionary from the ontology), `ollaya.py` (HTTP client,
  `decide`, `detect_tags`), `pipeline.py` (`candidates`, `select`, `select_direct`, `extract_params`, `answer`),
  `profile.py` (profile loader, `readable`, `run` with bindings), `db.py` (`ontology_tags`, `cq_tag_assessment`,
  `question_tag_assessment`, `question_eval`), `__main__.py` (CLI behind the Makefile)
- `profile/eu-expense-poc/`, `profile/c3po/`: the profiles; `profile/profile.db`: SQLite shared by the profiles, gitignored
- `tests/test_offline.py`: unit tests without Ollaya (`make test`)
- `docs/`: architecture and generation notes

Deliberately skipped: external triple store, web UI, text generation, HTTP server, config framework.
