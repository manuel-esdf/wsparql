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

A query's tag list is the set of tags with probability ≥ 0.5 in `query_tags`; the probabilities are kept, so the
threshold can change without calling Ollaya again. `select`, `params` and `sparql` are untouched.

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

`make query-tags` output (tags ≥ 0.5 per query, as detected by Ollaya on the descriptions) is in the README.

## Storage

`profile/profile.db` (SQLite, git-ignored, created on first use):

| table | row | written by |
|---|---|---|
| `tags` | profile, tag, description, source, version, date, run_id | `make tags-gen` |
| `query_tags` | profile, q_id (1-based catalog position), q_label (catalog id), description, tags (JSON `{tag: probability}`), model, version, date, run_id | `make query-tags` |
| `tag_cache` | profile, q_id, question, tags (JSON), model, version, date, run_id | `make tags-cache` |
| `eval_result` | one row per (profile, q_id, run_id), replaced on each eval | `make eval` |

`run_id` is one counter over the three tag tables, so a run number identifies one command invocation anywhere in
the file. Every reader takes the latest run for the profile `VERSION` (and model, when Ollaya was involved);
`make eval` prints the three run_ids it used. Bump `VERSION` when `tbox.ttl`, `abox.ttl` or the catalog change:
rows of the old version are then ignored, never mixed with the new vocabulary.

## Workflow

    make tags-gen        # ontology -> tags (instant)
    make query-tags      # Ollaya reads the 10 descriptions with the 23 tags (seconds each)
    make tags-cache      # Ollaya reads the 59 test questions (minutes)
    make eval            # routing score; the acceptance check for any wording change

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
