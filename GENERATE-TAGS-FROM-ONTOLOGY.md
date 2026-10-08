# Deriving the tags from the ontology

How `tags.yaml` and the per-query `tags:` lists of `query-catalog.yaml` are replaced by two tables of
`profile/profile.db`: a tag dictionary derived from `tbox.ttl` + `abox.ttl`, and per-query tags assessed by Ollaya
from each query description.

## Why

A tag has exactly two uses in the pipeline: its description is one `noul` instruction sent to Ollaya
(`ollaya.detect_tags`), and its name is a key the catalog attaches to each query (`pipeline.candidates`, mean of the
detected probabilities over a query's tags). Both were hand-written, in three files that had to stay aligned:

- `tbox.ttl` names the concepts (classes, properties, category values);
- `tags.yaml` repeats them as tag descriptions;
- `query-catalog.yaml` repeats them again as the tag list of every query.

The ontology already holds the concepts and each query already has a description. So the dictionary is derived from
the ontology, and the tags of a query are what Ollaya detects when it reads the query description with that
dictionary, exactly as it reads a user question. Tag names never reach Ollaya (only descriptions do), so generated
names are free to differ from the old ones.

## Design

| Stage | Command | Source | Stored in |
|---|---|---|---|
| Tag dictionary | `make tags-gen` | `tbox.ttl` + `abox.ttl`, rules below, no Ollaya | table `tags` |
| Query tags | `make query-tags` | Ollaya `noul` per tag on each catalog query `description` | table `query_tags` |
| Question tags | `make tags-cache`, `make ask` | Ollaya `noul` per tag on the question | table `tag_cache` |
| Candidates | `make candidates` | unchanged: mean question-tag probability over the query's tags, top 3 | |
| Baseline without tags | `make eval-direct` | one Ollaya `choice` over the raw SPARQL text of all 10 queries + `none`, then parameters and run | printed only |
| Fallback | `make ask`, `make eval` | the same direct `choice`, run only when the tag route answers `none`; its answer is final | `eval_result` (the `via` column of `make eval` says which route answered) |

A query's tag list is the set of tags with probability ≥ 0.5 in `query_tags`; the probabilities are kept, so the
threshold can change without calling Ollaya again. `select`, `params` and `sparql` read descriptions and the ABOX, not tags,
and are untouched by this change.

## Where the 19 hand-written tags came from

| tag | source in the ontology | kind |
|---|---|---|
| expense, project, work-package, employee, supplier, category | `owl:Class` `ex:Expense`, `ex:EuropeanProject`, `ex:WorkPackage`, `ex:Employee`, `ex:Supplier`, `ex:ExpenseCategory` | class |
| travel | individual `ex:Travel` of `ex:ExpenseCategory`, declared in `tbox.ttl` | TBOX individual |
| budget, eligibility | `owl:DatatypeProperty` `ex:budget` (`xsd:decimal`), `ex:eligible` (`xsd:boolean`) | datatype property |
| time | the `xsd:date` properties `ex:expenseDate`, `ex:startDate`, `ex:endDate` | datatype property |
| total, breakdown, comparison, ranking, list, trend, month, date-range | none: the shape of the answer the user wants | intent |
| remaining | none: q05 computes `budget - spent`; q05 keeps `budget` and `comparison` | dropped |

11 tags are in the ontology, 8 are intents that no ontology contains, 1 is neither.

## Rules (`wsparql/tags.py`)

Generic, applied in order; the first rule to produce a name wins. `tbox` is the TBOX graph alone, `g` is TBOX + ABOX.

| | Rule | Extraction (rdflib) | On this profile |
|---|---|---|---|
| R1 | one tag per `owl:Class` with at least 2 individuals in the data | `tbox.subjects(RDF.type, OWL.Class)`, count `g.subjects(RDF.type, c)` | 6 classes; `ex:Company` (1 individual) skipped: it cannot discriminate questions |
| R2 | one tag per individual declared in the TBOX: they are controlled vocabulary, not data | `tbox.subject_objects(RDF.type)` whose object is an `owl:Class` | the 5 `ex:ExpenseCategory` values |
| R3 | one tag per `xsd:boolean` or numeric datatype property; all `xsd:date` properties collapse into one `time` tag; `xsd:string` skipped | `tbox.subjects(RDF.type, OWL.DatatypeProperty)`, `rdfs:range` | `eligible`, `budget`, `amount`, `time`; `name`, `acronym`, `grantAgreement`, `description`, `country` skipped |
| R4 | fixed intent tags, the same for every profile | `INTENT` dict in `wsparql/tags.py` | the 8 intents above |

ABOX individuals (projects, employees, suppliers) never become tags: they are parameter values, already handled by
the `acronym` choice in `pipeline.extract_params`, and a tag per entity would grow with the data.

- **name**: slug of `rdfs:label`, else of the IRI local name split on camelCase: `European project` → `european-project`,
  `OtherGoodsServices` → `other-goods-services`.
- **description**: `rdfs:comment` when present, else a template (`The question concerns: expense category`).
  The templates are a fallback; the wording Ollaya sees belongs in the ontology, so `tbox.ttl` carries an
  `rdfs:comment` on the 6 classes, on `budget`, `amount`, `eligible` and on the 5 category individuals, reusing the
  old `tags.yaml` wording where one existed (it scored 34/40).

## Result on eu-expense-poc

`make tags-gen` (23 tags):

    tag                    source                           description
    employee               class ex:Employee                The question concerns an employee or personnel member
    european-project       class ex:EuropeanProject         The question concerns one or more European projects
    expense                class ex:Expense                 The question concerns company expenses or costs
    expense-category       class ex:ExpenseCategory         The question concerns an expense category
    supplier               class ex:Supplier                The question concerns a supplier or external provider
    work-package           class ex:WorkPackage             The question concerns a project work package
    equipment              individual ex:Equipment          The question concerns equipment purchases
    other-goods-services   individual ex:OtherGoodsServices The question concerns other goods and services costs
    personnel              individual ex:Personnel          The question concerns personnel costs
    subcontracting         individual ex:Subcontracting     The question concerns subcontracting costs
    travel                 individual ex:Travel             The question concerns travel expenses
    amount                 property ex:amount               The question concerns the amount of an expense
    budget                 property ex:budget               The question concerns allocated project budget
    eligible               property ex:eligible             The question concerns whether costs are eligible
    time                   property xsd:date                The question includes a temporal dimension
    total                  intent                           The user wants a total amount
    breakdown              intent                           The user wants a breakdown by dimension
    comparison             intent                           The user wants to compare several entities or values
    ranking                intent                           The user wants entities ordered by amount
    list                   intent                           The user wants individual records listed
    trend                  intent                           The user wants evolution over time
    month                  intent                           The question concerns monthly aggregation
    date-range             intent                           The question specifies or implies a period

Compared with the old `tags.yaml`: renamed `project` → `european-project`, `category` → `expense-category`,
`eligibility` → `eligible`; added `personnel`, `equipment`, `subcontracting`, `other-goods-services`, `amount`;
dropped `remaining`. Each question now costs 23 `noul` questions instead of 19.

`make query-tags` with `winnow` (tags ≥ 0.5 per query, detected by Ollaya on the descriptions):

    [ 1/10] q01-total-expenses-by-project    expense, european-project, comparison, amount, total, expense-category
    [ 2/10] q02-project-expense-breakdown    european-project, expense, expense-category, breakdown, budget, comparison, amount
    [ 3/10] q03-travel-expenses-by-project   travel, comparison, expense, amount, expense-category, other-goods-services
    [ 4/10] q04-expenses-by-work-package     work-package, amount, expense, total, breakdown, comparison
    [ 5/10] q05-budget-vs-spent              comparison, expense, budget, amount
    [ 6/10] q06-ineligible-expenses          expense, eligible, list, expense-category, budget
    [ 7/10] q07-expenses-by-employee         employee, personnel, expense, total, amount, breakdown, other-goods-services
    [ 8/10] q08-expenses-by-supplier         expense, supplier, breakdown, total, amount, comparison, other-goods-services
    [ 9/10] q09-monthly-expenses             time, month, date-range, total, expense, amount, trend, expense-category
    [10/10] q10-project-expenses-in-period   time, date-range, expense, list, other-goods-services, work-package, budget

The detected lists are wider than the hand-written ones (`amount` and `expense-category` almost everywhere) and
`european-project` is missed where the description says "project" while the comment says "European projects": the wording
of the comments and of the descriptions is now the tuning surface, checked by `make eval`. Example: the original q02
description "Break down a project's expenses by cost category" got 11 tags (every category plus `budget` at 0.97) and
three breakdown questions lost q02 from their top 3 candidates; "Breakdown of one European project's expenses by expense
category" gets the 7 above and the expected query is among the candidates for 31 of the 33 in-domain questions.
IDF weighting in `candidates` was tested offline on the same data and did not help: the rare extra tags weigh more.

`make eval` with these tags: **35/40** against 34/40 with the hand-written ones. The first eval gave 33/40: the remaining
misses were at the selection stage, on questions naming a project, and went away once the selection wording in
`pipeline.select` said that the queries are templates whose parameters are filled in afterwards (details in the README).
Ollaya's `noul` answers are reproducible: the nine untouched descriptions got identical probabilities in every
`make query-tags` run.

`make eval-direct`, the baseline without tags (one `choice` over the raw `.rq` text of all 10 queries plus `none`, no
dictionary, no query tags, no candidates): **36/40**, with other misses.

| method | misses (q_id) | the other method on them |
|---|---|---|
| tags → 3 candidates → choice over descriptions | 2, 5, 6, 16, 19, all answered `none` | direct gets all 5 right |
| direct choice over the raw SPARQL | 21, 23, 26, 54, all answered `none` | tags get all 4 right |

No question fails in both; the 7 off-topic questions get `none` in both. q_id 5, "What did OPENSCIENCE spend on
equipment?", failed in both until `pipeline.DIRECT_INSTRUCTIONS` said that `none` is for an answer no query "computes
or contains among its rows": Ollaya read the q02 breakdown as not computing a one-category figure (`none` 0.73 against
q02 0.25, and a SPARQL comment listing the categories made it worse, 0.81 against 0.16). With the clause q02 wins at 0.73
and the closest off-topic call, "Write a SPARQL query to list all suppliers.", moves from `none` 0.49 to 0.63.

### Fallback

`pipeline.answer` therefore falls back to the direct choice whenever the tag route answers `none`. `make eval` with the
fallback (the `via` column says which route answered; the 28 lines answered by the tag route are omitted):

    tags: query tags run_id 9, question tags cache run_id 3
    ok   [ 2] q01-total-expenses-by-project    q01-total-expenses-by-project    0.94 3 rows     fallback | What is the total amount spent on LUMEN so far?
    ok   [ 5] q02-project-expense-breakdown    q02-project-expense-breakdown    0.70 3 rows     fallback | What did OPENSCIENCE spend on equipment?
    ok   [ 6] q03-travel-expenses-by-project   q03-travel-expenses-by-project   0.95 3 rows     fallback | Compare travel costs between LUMEN and GRAPHIA.
    ok   [16] q04-expenses-by-work-package     q04-expenses-by-work-package     0.99 5 rows     fallback | Which work package of GRAPHIA is the most expensive?
    ok   [19] q05-budget-vs-spent              q05-budget-vs-spent              0.91 3 rows     fallback | What is the budget of each European project?
    ok   [37] none                             none                             0.98 -          fallback | List every expense above 5000 euros.
    ok   [45] none                             none                             0.94 -          fallback | Which German suppliers have we worked with?
    ok   [46] none                             none                             1.00 -          fallback | When does the LUMEN grant agreement end?
    ok   [47] none                             none                             1.00 -          fallback | How many employees work on OPENSCIENCE?
    ok   [48] none                             none                             1.00 -          fallback | What is the weather like in Brussels today?
    ok   [49] none                             none                             1.00 -          fallback | Can you book me a train to Paris next Monday?
    ok   [50] none                             none                             0.63 -          fallback | Write a SPARQL query to list all suppliers.
    40/40 with the direct fallback, 35/40 tag route alone (skipped 19 questions without expected_query)

- **40/40**: the fallback runs 12 times, on the 5 tag misses and the 7 off-topic questions, gets all 5 misses right and
  keeps `none` on all 7 off-topic questions.
- q_id 5 was the last miss and a wording issue of this route, not of the tags: the tag route cannot see q02 for it (the
  question carries neither `european-project` nor `breakdown`, so q02 is not among its 3 candidates and `none` is the
  right answer over q05, q06 and q01), and the raw SPARQL of q02 names no category (`?category ex:name ?categoryName`).
  The "computes or contains among its rows" clause above is what lets a breakdown answer a one-category question.
- The closest call is "Write a SPARQL query to list all suppliers.", `none` at 0.63: a question that talks about SPARQL
  while Ollaya reads raw SPARQL is the weak spot of this route.
- Cost: one extra `choice` over the 10 raw queries per `none` answer, so the off-topic questions are now the most
  expensive ones (two choices). The 35/40 of the tag route alone stays visible on the summary line, so the tag wording
  can still be tuned without the fallback masking it.
- The fallback only helps while the tag misses are `none` rather than a wrong query: a wrong selection is final.

The tag stage therefore buys no accuracy here; it buys explainability (tag and candidate tables) and a choice over
3 short descriptions instead of 10 full queries, which matters once the catalog outgrows one `choice`.

## Storage

`profile/profile.db` (SQLite, git-ignored, created on first use):

| table | row | written by |
|---|---|---|
| `tags` | profile, tag, description, source, version, date; deterministic, so no run_id: the rows of the profile version are replaced | `make tags-gen` |
| `query_tags` | profile, q_id (1-based catalog position), q_label (catalog id), description, tags (JSON `{tag: probability}`), model, version, date, run_id | `make query-tags` |
| `tag_cache` | profile, q_id, question, tags (JSON), model, version, date, run_id | `make tags-cache` |
| `eval_result` | one row per (profile, q_id, run_id), replaced on each eval | `make eval` |

`run_id` is one counter over the two Ollaya tables, so a run number identifies one command invocation anywhere in
the file. Every reader takes the latest run for the profile `VERSION` and model; `make eval` prints the two run_ids it
used. Bump `VERSION` when `tbox.ttl`, `abox.ttl` or the catalog change:
rows of the old version are then ignored, never mixed with the new vocabulary.

## Workflow

    make tags-gen        # ontology -> tags (instant)
    make query-tags      # Ollaya reads the 10 descriptions with the 23 tags (seconds each)
    make tags-cache      # Ollaya reads the 59 test questions (minutes)
    make eval            # routing score with the fallback and for the tag route alone; the acceptance check for any wording change

Changing a tag description = editing an `rdfs:comment` in `tbox.ttl`, then the four commands again.
Adding a catalog query = description + `.rq`, then `make query-tags`.

## Limits

- `rdfs:subClassOf`: none in this TBOX. With a hierarchy, R1 would emit the parent tag as well and `candidates`
  could expand a detected child tag to its parents before ranking.
- Large enumerations: R2 emits one tag per TBOX individual; above a few dozen values they should become a
  parameter (a `choice` over the values, like `acronym`), not tags.
- Ontologies without `rdfs:label` or `rdfs:comment` fall back to local names and templates; expect to tune the
  wording through `make eval`.
- The 0.5 threshold on query tags is a constant (`pipeline.TAG_THRESHOLD`); weighting candidates by the stored
  probabilities is the next step if the eval score drops.
- The fallback sends the raw SPARQL of every query in one `choice`; with a large catalog it needs its own pre-selection
  (the tag candidates, for instance) or it becomes the slow and expensive path.
