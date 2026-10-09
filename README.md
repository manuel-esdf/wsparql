# wsparql

POC evaluating https://ollaya.dev/ for routing natural-language questions to predefined SPARQL queries.

## Goal

Allow a user to ask a question in natural language and automatically select the most relevant predefined SPARQL query to execute on a knowledge graph.
The system does not generate SPARQL.
It only chooses among trusted, existing queries, extracts their parameters from the question, and answers "no suitable query" when nothing fits.

## Input

Everything the system knows lives in one profile directory (`PROFILE` in `.env`, currently `profile/eu-expense-poc`, see its [README](profile/eu-expense-poc/README.md)):

- a TBOX ontology describing the domain (`tbox.ttl`);
- CSV source files with the business data (`csv/*.csv`, one file per class); the ABOX (`abox.ttl`) is derived from them by a
  minimal ETL (`make abox`): the TBOX is the schema, column = property, its `rdfs:range` types the value, committed, no Ollaya;
- a catalog of predefined SPARQL queries (`query-catalog.yaml`: description, parameters with example values; `queries/*.rq`);
- test questions with the expected query (`tests/test-questions.yaml`).

The tag dictionary (concepts and user intentions) is not written by hand: it is derived from the ontology, and the tags of
each query are detected by Ollaya from the query description. Both live in `profile/profile.db`, see
[GENERATE-TAGS-FROM-ONTOLOGY.md](GENERATE-TAGS-FROM-ONTOLOGY.md).

## Decision process

| Stage | Command | How |
|---|---|---|
| Tag dictionary (once per profile version) | `make tags-gen` | rules on `tbox.ttl` + `abox.ttl`: classes with data, TBOX individuals, boolean/numeric/date properties, fixed intents; description = `rdfs:comment`; no Ollaya |
| Query tags (once per profile version) | `make query-tags` | one `noul` question per tag on each catalog query description; a query's tags = probability ≥ 0.5 |
| Natural language question | `make ask Q="..."` | |
| Detect relevant tags with Ollaya | `make tags` | one `noul` question per tag in a single `/v1/systemone` call, probability per tag |
| Identify the most relevant SPARQL queries | `make candidates` | pure Python: mean detected probability over each query's tags, top 5 |
| Ollaya selects the best candidate | `make select` | one `choice` question over the 3 candidate descriptions plus `none`; `none` or confidence below 0.4 = no suitable query |
| Fallback when that answer is `none` | `make ask` | one more `choice` over the SPARQL (labels in place of the opaque IRIs) text of all 10 queries plus `none`; its answer is final |
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
    make tags-gen            # tag dictionary from the ontology -> profile/profile.db
    make query-tags          # Ollaya tags the 10 catalog descriptions (seconds each)
    make tags-cache          # Ollaya tags the 59 test questions (minutes), optional: ask/demo call Ollaya for uncached questions

## Usage

`make help`:

    help                 list targets
    install              uv sync (creates .venv with rdflib + pyyaml)
    test                 offline unit tests (no Ollaya)
    clean                drop the derived artefacts: $(PROFILE)/abox.ttl (make abox rebuilds it), profile/profile.db (tags, query tags, tag cache, eval results; make tags-gen query-tags tags-cache rebuild them, minutes on winnow) and __pycache__; keeps .venv
    build                build all derived artefacts in order: abox.ttl (ETL), then profile/profile.db tags (tags-gen), query tags (query-tags, Ollaya) and the question tag cache (tags-cache, Ollaya, minutes on winnow); then make eval
    profile-check        mandatory profile files present in $(PROFILE); every catalog query has its .rq
    abox                 ETL: build $(PROFILE)/abox.ttl from tbox.ttl + csv/*.csv (TBOX IRIs are opaque, rdfs:label is the name: file = class label, column = property label, id = IRI local name, | separates values; the TBOX types the values); committed, rerun after editing a csv; no Ollaya
    sparql               run a catalog query on the ABOX: make sparql Q=q10-project-expenses-in-period ARGS="acronym=GRAPHIA from=2026-01-01 to=2026-06-30"; no ARGS = catalog example params; no Q = all queries, row counts only
    tags-gen             derive the tag dictionary from tbox.ttl + abox.ttl (classes, TBOX individuals, datatype properties) plus fixed intent tags, store in profile/profile.db tags (deterministic: no run_id, rows of the profile version replaced); no Ollaya, instant. See GENERATE-TAGS-FROM-ONTOLOGY.md
    query-tags           Ollaya assesses every tag of the dictionary against each catalog query description (one noul per tag), store {tag: prob} per query in profile/profile.db query_tags (new run_id); a query's tags = those >= 0.5 (seconds per query on winnow)
    tags                 detect tags for a question with Ollaya: make tags Q="Which suppliers cost us the most?"; no Q = first tests/test-questions.yaml question
    candidates           rank top 5 queries for Q; question tags from the last tags-cache run when Q is cached, else Ollaya; query tags from the last query-tags run. No Q = first tests/test-questions.yaml question
    select               rank candidates, then Ollaya picks the best query or none: make select Q="..."; no Q = first tests/test-questions.yaml question
    params               extract the query parameters found in Q (acronym: Ollaya choice over ABOX projects + none; from/to: regex on quarter, month, year): make params Q="List LUMEN expenses for Q1 2026"; no Q = working examples, every test question whose expected query takes parameters
    ask                  answer Q end to end: tags, candidates, selected query (fallback: direct choice over the SPARQL (labels in place of the opaque IRIs) when the tag route says none), parameters, result rows or "no suitable query": make ask Q="List LUMEN expenses for Q1 2026"; no Q = first tests/test-questions.yaml question
    demo                 make ask on every tests/test-questions.yaml question that has an expected_query, off-topic ones included (minutes on winnow)
    eval                 full chain on every tests/test-questions.yaml question that has an expected_query, tags from the latest tags-gen / query-tags / tags-cache runs (fails if a question is not cached): expected query selected and returns rows, none answers "no suitable query"; rows stored in profile/profile.db eval_result; N/M with the direct fallback and for the tag route alone, exit 1 on any mismatch (minutes on winnow)
    eval-direct          baseline without tags: for each labeled tests/test-questions.yaml question one Ollaya choice over the SPARQL (labels in place of the opaque IRIs) of all 10 queries + none, then parameters and run; N/M, exit 1 on any mismatch (minutes on winnow)
    tags-cache           detect tags for every tests/test-questions.yaml question with Ollaya (needs make tags-gen), store in profile/profile.db (new run_id)
    ollaya-check         prerequisites: uv, ollaya binary, server up, model pulled
    ollaya-smoke-test    one tag-detection query on /v1/systemone; fails if "expense" tag < 0.5

Example, `make ask Q="List LUMEN expenses for Q1 2026"`:

    Q: List LUMEN expenses for Q1 2026
    tags: cache run_id 3
    tag               prob
    time              1.00
    date-range        1.00
    expense           1.00
    expense-category  0.94
    list              0.92
    budget            0.81

    candidate                       score  prob  description
    q06-ineligible-expenses         0.77   0.00  List expenses marked as ineligible
    q10-project-expenses-in-period  0.75   0.96  List project expenses within a date range
    q09-monthly-expenses            0.52   0.00  Show monthly expense totals
    none                                   0.04  no suitable query
    selected: q10-project-expenses-in-period (confidence 0.94)

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

Tag detection is the slow call (23 `noul` questions, seconds to tens of seconds per question on `winnow`), so
`make tags-cache` detects the tags of every test question once and stores them in `profile/profile.db`
(SQLite, gitignored, table `tag_cache`, one `run_id` per run, keyed by profile, question, model and profile `VERSION`).
`candidates`, `select`, `ask` and `demo` use the last cached run when the question is cached, Ollaya otherwise.

`make eval` routes every test question that has an `expected_query` (catalog id or `none`) through the full chain:
the expected query must be selected and return rows, `none` questions must get "no suitable query".
It reads the tags of one `run_id` only (never Ollaya) and stores one row per (profile, q_id, run_id) in table
`eval_result`, replaced on each run, so an eval is reproducible for a given `run_id` and the summary line says
whether it matches the previous one.

Current score on `profile/eu-expense-poc` with `winnow`, profile 1.4.0 (opaque TBOX IRIs; 109 test questions, 87
labeled: 73 in-domain and 14 `none`; 22 ambiguous ones are unlabeled and skipped), query tags run_id 9, question tags
run_id 10: **86/87** with the direct fallback, **76/87** for the tag route alone, both printed by `make eval`;
`make eval-direct` **82/87**. Profile 1.3.0 (the same TBOX with named IRIs, query tags run_id 3, question tags run_id 4)
scored 86/87, 76/87 and 81/87: the tag route reads descriptions and `rdfs:comment`s, never IRIs, and its 62 answers
are identical; the fallback and the direct route read the SPARQL text, which now gets the labels in place of the opaque
IRIs (`ex:P14` → `ex:amount`, see "Fallback"), and answer the same 87 questions the same way, with higher confidences.
The one miss is "Show the personnel expenditure for OPENSCIENCE." (expected q02): both routes answer `none` (0.90 tag
route, 0.92 fallback), "personnel" reads as the employee query (its tags rank q07, q01, q05). The explored variants were
rerun on the 109 questions against the 1.3.0 baseline, every one a scratch run with the files restored afterwards:

| variant | with fallback | tag route alone | in-domain questions through the fallback |
|---|---|---|---|
| baseline: top 3 candidates, "no query can compute" | 86/87 | 71/87 | 16 |
| top 5 candidates | 86/87 | 74/87 | 13 |
| "computes or contains among its rows" in the tag-route choice too | 86/87 | 72/87 | 15 |
| **both (adopted)** | **86/87** | **76/87** | 11 |
| object-property tags (scratch 1.3.1, 28 tags) | 86/87 | 71/87 | 16 |
| object-property tags + both | 85/87 | 77/87 | 9, and the first wrong query: "What is the total amount spent on LUMEN so far?" → q05 at 0.51 with rows, final |
| q01, q03, q05 described as "... of each European project" (scratch 1.3.2) | 85/87 | 66/87 | 21 |
| catalog description prepended to the raw SPARQL in `select_direct` | eval-direct 80/87 | | |

Top 5 is the ranking fix: the expected query is in the top 3 for 66 of the 73 in-domain questions and in the top 5 for
71 ("How much did GRAPHIA spend in each expense category?" and "What were LUMEN's subcontracting costs?" stay out, their
tags rank q03 and q08 first). The 11 remaining tag-route `none` answers sit on the "Compare ..." descriptions of q01,
q03 and q05 (q_id 2, 6, 19, 61, 62, 63, 71), on q02 one-category questions (65, 66, 67) and on 92. Rewording those
descriptions is the variant that lost most: "of each European project" adds `european-project`, `list` and `breakdown`
to the three queries (q03 6 → 10 tags) and the plain mean pushes 11 questions out of the top 3. The direct route's 6
misses are still "one figure" questions whose answer is a row or a sum of the rows (percentage consumed, remaining
budget, ineligible total, the personnel one above) plus "What is our total spending with CloudHost Europe?" at `none` 0.46.

On the first test set (59 questions, 40 labeled, profile 1.2.0, query tags run_id 1, question tags run_id 2) the score
was **40/40** with the direct fallback and **35/40** for the tag route alone (19 ambiguous questions unlabeled and
skipped; the hand-written tags scored 34/40).
All 7 off-topic questions were answered "no suitable query" and every correctly selected query returned rows, including
the parameterised ones. Three wordings got there:

- the q02 description: "Break down a project's expenses by cost category" made Ollaya tag it with every category plus
  `budget`, 11 tags, and the plain mean of `pipeline.candidates` diluted it out of the top 3 (IDF weighting was tested
  offline and did not help, rare extra tags weigh more, not less). "Breakdown of one European project's expenses by expense
  category" gets 7 tags; the expected query is now among the 3 candidates for 31 of the 33 in-domain questions;
- the selection instructions and the `none` criterion in `pipeline.select`: they now say that the queries are templates
  whose project, employee, supplier and dates are filled in afterwards, and that `none` is for off-topic questions or
  answers no query computes. Before, 5 questions naming a project got `none` with high confidence (33/40);
- the fallback instruction in `pipeline.select_direct`: `none` is for an answer no query "computes or contains among its
  rows". Without it Ollaya read the q02 breakdown as not computing a one-category figure ("What did OPENSCIENCE spend on
  equipment?": `none` 0.73 against q02 0.25, and a SPARQL comment listing the categories made it worse); with it q02 wins
  at 0.73 and the closest off-topic call moves from `none` 0.49 to 0.63 (39/40 before).

The 5 misses of the tag route are all `none` answers, so the fallback takes them: the direct choice over the raw SPARQL
gets all 5 right and the 7 off-topic questions still get `none` (the closest call is "Write a SPARQL query to list all
suppliers.", `none` at 0.81). The `via` column of `make eval` says which route answered each question.

The fallback reads the raw query text, so the wording of the `.rq` files is part of the routing. Dropping the stored
`ex:chargedToProject` (profile 1.2.0, no inference: the project of an expense is reached through its work package)
first went through the path `ex:chargedToWorkPackage/ex:belongsToProject`: 38/40 (33/40 for the direct route alone),
the equipment question falling to `none` 0.89 and the "Write a SPARQL query" question to q08 0.69, with the tag route
untouched at 35/40 (it reads descriptions, not queries). The wording that restored 40/40, with wider margins than
before, is an explicit join written project-first in all six project queries, `?project a ex:EuropeanProject ;
ex:acronym ?acronym . ?workPackage ex:belongsToProject ?project . ?expense ... ex:chargedToWorkPackage ?workPackage`,
plus `?acronym` in the SELECT of q02: q02 at 0.98 for the equipment question, `none` at 0.81 for the SPARQL one.
Tried on the way, no gain: the same join expense-first (q02 0.83 → `none`), a `#` comment on q02 (worse, as before),
and the join without the `a ex:EuropeanProject` type on `?project` (q5 `none` 0.89).
Tried after that, no gain: the catalog description prepended to the raw SPARQL in `select_direct`. `make eval-direct`
stays at 36/40 with a different miss: "Which project has the smallest remaining budget?" passes (q05 0.50) but the
equipment question goes to `none` 0.91, and since the fallback shares `select_direct` that would cost 40/40 (the
equipment question is one of the 5 the tag route misses). Not adopted.
Also tried, no gain: the same "computes or contains among its rows" phrase in the tag route's `pipeline.select`
instructions. `make eval` unchanged, 40/40 and 35/40, the same 5 questions through the fallback, 14 tag-route confidences
move by at most 0.14 and no selection changes. The 3 tag-route `none` answers that are not ranking misses all land on a
"Compare ..." description with the expected query among the candidates: "What is the total amount spent on LUMEN so
far?" (`none` 0.59 against q01 0.39), "Compare travel costs between LUMEN and GRAPHIA." (`none` 0.88 against q03 0.11)
and "What is the budget of each European project?" (`none` 0.92 against q05 0.07). The lever there is the description
wording of q01, q03 and q05, not the instructions.
Tried next, worse: those three descriptions reworded to what the rows hold, "Total expenses of each European project",
"Travel expenses of each European project", "Budget, spent amount and remaining budget of each European project"
(scratch profile 1.3.0, query tags run_id 3, question tags run_id 4): **39/40** with the fallback, **32/40** tag route
alone. "of each European project" made Ollaya add `european-project`, `list` and `breakdown` to the three (q03 6 → 10
tags, q05 4 → 8, q01 6 → 7) and the plain mean diluted again, as with the first q02 description: the budget-of-each-project
question is won, but four others fall to `none` on the tag route ("How much budget is left on OPENSCIENCE?", "Compare
the budget and the actual spending of every project.", "Rank the projects by travel spending." and the percentage
question, which the fallback cannot answer either, hence 39/40), while the LUMEN total and the LUMEN/GRAPHIA travel
comparison still get `none`. Not adopted; the 1.2.0 descriptions stay.
An acronym hint to the tagger, "(LUMEN, GRAPHIA or OPENSCIENCE)" appended to the `european-project` tag description,
was tried after that: it lets the tag route answer the equipment question but costs two others at the candidate stage,
34/40 alone and 40/40 with the fallback, so it is not adopted (numbers in GENERATE-TAGS-FROM-ONTOLOGY.md).
Profile 1.4.0 made the TBOX IRIs opaque (`ex:C06`, `ex:P14`, `ex:I02`; the name lives in `rdfs:label`, see
GENERATE-ABOX.md), so the raw `.rq` text lost its vocabulary: `?expense a ex:C06 ; ex:P04 ?workPackage ; ex:P14 ?amount`,
only the variable names left to read. Measured first as-is, no comments and no label rendering, on the 109 questions:
`make eval-direct` stayed at 81/87 but with other misses, 3 recovered ("Which project has the smallest remaining
budget?" q05 0.66, "How much ineligible spending do we have in total?" q06 0.56, "What is our total spending with
CloudHost Europe?" q08 0.51) and 3 lost ("What was spent on the Data ingestion work package?" `none` 0.71, "How much did
we spend in March 2026?" to q10 0.53 with no acronym to bind, "Compare GRAPHIA and OPENSCIENCE travel spending." `none`
0.48), with smaller margins all over (the LUMEN total q01 0.95 → 0.67; the closest off-topic call `none` 0.81 → 0.70,
"Write a SPARQL query to list all suppliers."). Through the fallback that cost the travel comparison, 86/87 → 85/87,
the tag route unchanged at 76/87. Adopted instead: `Profile.readable`, the same text with every labeled TBOX term
replaced by its label in camelCase (`ex:P14` → `ex:amount`, `ex:C02` → `ex:EuropeanProject`), which is what
`select_direct` sends and what `make eval-direct` scores; the `.rq` files stay opaque and carry no comments (a `#`
comment on q02 cost a question earlier). It is the 1.3.0 wording again except q02's `?category rdfs:label
?categoryName`: `make eval` is back to **86/87**, every fallback answer equal to 1.3.0 with the two travel comparisons
up (q03 0.83 → 0.98 and 0.78 → 0.94), the closest off-topic call `none` 0.73 (the SPARQL question again).
`make eval-direct` **82/87**: against 1.3.0 it recovers the smallest-remaining-budget question (q05 at 0.46, just above
the 0.4 minimum) and the CloudHost total (q08 0.66) and loses "Rank external providers by total expenditure."
(`none` 0.57); the other 4 misses are the 1.3.0 ones.

`make eval-direct` is the baseline without tags: for each labeled question, one `choice` over the raw SPARQL text of all
10 queries plus `none`, then the same parameter extraction and run. It scores **36/40** on its own, with other misses than
the tag route (all 4 are "one figure" questions on q04, q05 and q06, "How is the LUMEN spending split across work
packages?", "What percentage of the GRAPHIA budget has already been consumed?", "How much ineligible spending do we have
in total?"); no question fails in both, which is why the two routes combined reach 40/40. On this catalog the tag stage does not buy
accuracy by itself. It buys explainability (the tag and
candidate tables) and a choice over 5 short descriptions instead of 10 full queries, which is what matters once the
catalog grows past what one `choice` can hold. On the 109-question set the tag route does buy accuracy where the
direct route cannot: 5 of its 6 misses are answered by the tag route (table above).

## Role of the Ontology

The TBOX provides additional semantic knowledge.

For example, if Researcher is a subclass of Person, the system can use this relationship during query selection without asking the AI model to rediscover it.

Exercised for the tag dictionary: classes, TBOX individuals and datatype properties become tags, their `rdfs:comment` is the
instruction Ollaya reads (`make tags-gen`). Not exercised for ranking: the current TBOX has no subclass hierarchy, so there is
nothing to expand before ranking.

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
- `wsparql/`: `ollaya.py` (HTTP client, `decide`, `detect_tags`), `profile.py` (profile loader, `run` with bindings), `tags.py` (tag dictionary from the ontology), `pipeline.py` (`candidates`, `select`, `extract_period`, `extract_params`, `answer`), `db.py` (`tags`, `query_tags`, `tag_cache`, `eval_result`), `__main__.py` (CLI behind the Makefile)
- `profile/eu-expense-poc/`: the profile (see its README); `profile/profile.db`: local cache, gitignored
- `tests/test_offline.py`: unit tests without Ollaya (`make test`)
- `GENERATE-TAGS-FROM-ONTOLOGY.md`: how the tags are derived from the ontology and the query tags from the descriptions

Deliberately skipped: external triple store, web UI, text generation, HTTP server, config framework.
