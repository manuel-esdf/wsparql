# Deriving the tags from the ontology

Tags route a question to its candidate queries. Nothing about them is hand-written: the dictionary is derived from
`tbox.ttl` + `abox.ttl`, and each query's tags are what Ollaya detects on its competency question.

## Why

A tag has two uses:

- its **description** is one `noul` instruction sent to Ollaya (`ollaya.detect_tags`);
- its **name** is a key attached to each catalog query, used to rank queries (`pipeline.candidates`: mean detected
  probability over the query's tags).

The ontology already names the concepts and each query already has a competency question, so both can be derived
instead of kept aligned by hand. Tag names never reach Ollaya, only descriptions and questions do.

## Steps

| Step | Command | Input | Output (`profile/profile.db`) |
|---|---|---|---|
| 1. Data | `make abox` | `tbox.ttl` + `csv/*.csv` (see [GENERATE-ABOX.md](GENERATE-ABOX.md)) | `abox.ttl` |
| 2. Tag dictionary | `make ontology-tags-gen` | `tbox.ttl` + `abox.ttl`, rules below, no Ollaya | `ontology_tags` |
| 3. Query tags | `make cq-tag-assessment` | Ollaya `noul` per tag on each catalog `competency-question` | `cq_tag_assessment` |
| 4. Question tags | `make question-tag-assessment` | Ollaya `noul` per tag on each test question | `question_tag_assessment` |

A query's tags are those with probability ≥ 0.5 (`pipeline.TAG_THRESHOLD`). All probabilities are stored, so the
threshold can change without calling Ollaya again.

## Rules (`wsparql/tags.py`)

Applied in order; the first rule to produce a name wins.

| | Rule | Example (eu-expense-poc) |
|---|---|---|
| R1 | one tag per `owl:Class` with ≥ 2 individuals, counting those of its subclasses | `expense`, `supplier`; `Company` (1 individual) skipped |
| R2 | one tag per individual declared in the TBOX (controlled vocabulary) | the expense categories `travel`, `personnel`… |
| R3 | one tag per boolean or numeric datatype property; all date properties → one `time` tag; strings skipped | `budget`, `amount`, `eligible`, `time` |
| R4 | fixed intent tags, the same for every profile (`tags.INTENT`) | `total`, `breakdown`, `comparison`, `ranking`, `list`, `trend`, `month`, `date-range` |

ABOX individuals (projects, employees, suppliers) never become tags: they are query parameter values.

- **name**: slug of the `rdfs:label` (`European project` → `european-project`). IRIs are opaque, so labels are required.
- **description**: the term's `rdfs:comment`, else a template (`The question concerns: expense category`). The wording
  Ollaya reads belongs in `tbox.ttl`.

Example output of `make ontology-tags-gen` (23 tags on eu-expense-poc, 41 on c3po):

    tag                source             description
    european-project   class ex:C02       The question concerns one or more European projects
    travel             individual ex:I02  The question concerns travel expenses
    budget             property ex:P13    The question concerns allocated project budget
    time               property xsd:date  The question includes a temporal dimension
    total              intent             The user wants a total amount
    ...

## Storage

| table | content | written by |
|---|---|---|
| `ontology_tags` | tag, description, source; deterministic, rows of the profile version replaced | `make ontology-tags-gen` |
| `cq_tag_assessment` | per catalog query: competency question, `{tag: probability}`, model, run_id | `make cq-tag-assessment` |
| `question_tag_assessment` | per test question: `{tag: probability}`, model, run_id | `make question-tag-assessment` |

`run_id` is one counter over the two Ollaya tables. Readers take the latest run for the profile `VERSION` and model.
Bump `VERSION` when the ontology, the CSV data or the catalog change, so old rows are never mixed with new ones.

## Workflow

    make build   # abox → ontology-tags-gen → cq-tag-assessment → question-tag-assessment
    make eval    # routing score; the acceptance check for any wording change

- Change a tag description: edit its `rdfs:comment` in `tbox.ttl`, then `make build`.
- Add a catalog query: competency question + `.rq`, then `make cq-tag-assessment`.

## Limits

- A detected child tag (`internal-employee`) does not raise a query tagged with its parent (`employee`).
- Large enumerations of TBOX individuals should become a parameter, not one tag each.
- Without `rdfs:label` / `rdfs:comment`, names and descriptions are poor; expect to tune the wording via `make eval`.
- The 0.5 threshold is a constant; weighting candidates by the stored probabilities is the next step if scores drop.
