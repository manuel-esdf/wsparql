# EU Project Expense POC Dataset

Synthetic RDF dataset designed to demonstrate natural-language routing to predefined SPARQL queries.

## Run this profile

From the repository root, with `.env` configured and the model available:

```sh
make PROFILE=profile/eu-expense-poc expected
make PROFILE=profile/eu-expense-poc answer Q="List LUMEN expenses for Q1 2026"
make PROFILE=profile/eu-expense-poc OLLAYA_MODEL=winnow eval
```

Selection makes one choice over every catalog query's readable SPARQL plus `none`. No model preprocessing is needed. `make eval` stores a new direct evaluation run and exits 1 if any scored answer fails. See the [root usage guide](../../README.md) and [migration notes](../../docs/MIGRATION-DIRECT-SELECTION.md).

## Files

- `VERSION`: profile version (semver); bump when ontology, data, queries or test questions change, so evaluation history distinguishes revisions.
- `tbox.ttl`: domain ontology with opaque IRIs (`ex:C01`.. classes, `ex:P01`.. properties, `ex:I01`.. category individuals, numbered in declaration order); the name of a term is its `rdfs:label`, and its `rdfs:comment` documents the term. Labels render opaque IRIs as readable names for direct query selection.
- `csv/`: the source data, one file per class (`Company`, `EuropeanProject`, `WorkPackage`, `Employee`, `Supplier`, `Expense`): synthetic company, 3 projects, 5 work packages, 3 employees, 5 suppliers, 12 expenses. Convention, the TBOX is the schema and CSV names are its labels compared as slugs (`expenseDate` = `expense date`): file stem = class label, column = property label, `id` = IRI local name (ABOX ids stay readable), `|` separates several values in a cell, empty cell = no triple; the property's `rdfs:range` types the value (reference for an object property, `xsd:date` / `xsd:decimal` / `xsd:boolean` literal otherwise); a reference cell that matches a TBOX individual label (`category`: `Personnel`, `Travel`, `Equipment`, `Subcontracting`, `OtherGoodsAndServices`) resolves to that individual, else to the CSV row; no inference, a relation is stored once in one direction and the queries join on it: `WorkPackage.csv` carries `belongsToProject` (no `hasWorkPackage`), an expense carries only `chargedToWorkPackage` (no `chargedToProject`; the queries go `?workPackage ex:P02 ?project . ?expense ex:P04 ?workPackage`). Unknown file or column, bad value or dangling reference fail the build, see [GENERATE-ABOX.md](../../docs/GENERATE-ABOX.md)
- `abox.ttl`: derived, `make abox` builds it from `tbox.ttl` + `csv/*.csv` (rdflib serialisation, sorted by subject, opaque predicates); committed so the tools and tests need no build step, rerun `make abox` after editing a csv (`make test` fails when it is stale)
- `queries/`: 10 predefined SPARQL queries on the opaque IRIs (readable variable names, no comments; direct selection reads them with the labels rendered in place of the IRIs, `ex:P14` → `ex:amount`); q02 and q10 take `?acronym`, q10 also `?from`/`?to` (bound at execution, never templated)
- `query-catalog.yaml`: `parameters` (what fills each query parameter: the ABOX values of the property labeled `acronym`, dates for `from`/`to`), one `competency-question` per query (the question it answers, "Which expenses are marked as ineligible?") and, for parameterised queries, `params` with example values (required: not found = "missing parameter"; used by `make sparql` when no `ARGS` is given)
- `tests/test-questions.yaml`: 109 natural-language questions (`q_id`, `question`, optional `expected_query`: catalog id or `none`; absent = ambiguous, skipped by `make eval`)
- `tests/expected.json`: a snapshot, not independent answers: one case per catalog query run with its catalog example parameters, written once from the results of profile 1.4.0 (a scratchpad script, not kept). Each case has `q_id` (the case number, not a test-question id), `query`, `params`, the row count and every returned cell. `make PROFILE=profile/eu-expense-poc expected` and `make test` fail when a query, `abox.ttl` or a catalog example changes what a query returns; rewrite the snapshot after an intended change
- `../profile.db`: shared SQLite evaluation history, git-ignored. `make eval` appends a completed run to `direct_eval`, keyed by profile, question and independent run ID, with model/version, selection, confidence, parameters, row count and correctness. See the [root README](../../README.md).

## Scenario

A French SME participates in three synthetic European projects: LUMEN, GRAPHIA and OPENSCIENCE. Expenses include personnel, travel, equipment, subcontracting and other goods/services.

All grant agreement IDs, budgets and expense records are fictional and intended only for demonstration.
