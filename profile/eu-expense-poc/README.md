# EU Project Expense POC Dataset

Synthetic RDF dataset designed to demonstrate natural-language routing to predefined SPARQL queries.

## Files

- `VERSION`: profile version (semver), bump when tags, catalog, queries or data change
- `tbox.ttl`: domain ontology
- `abox.ttl`: synthetic company, projects, work packages, employees, suppliers and expenses
- `queries/`: 10 predefined SPARQL queries; q02 and q10 take `?acronym`, q10 also `?from`/`?to` (bound at execution, never templated)
- `query-catalog.yaml`: query descriptions, routing tags and, for parameterised queries, `params` with example values (used by `make sparql` when no `ARGS` is given)
- `tags.yaml`: controlled tag dictionary
- `tests/test-questions.yaml`: 59 natural-language questions (`q_id`, `question`, optional `expected_query`: catalog id or `none`; absent = ambiguous, skipped by `make eval`)
- `../profile.db`: SQLite, shared by all profiles, git-ignored, created on first use. Table `tag_cache(profile, q_id, question, tags JSON, model, version, date, run_id)`: filled by `make tags-cache` (`run_id` incremented on each run), read by `make candidates` / `select` / `ask` / `demo` (last run). Table `eval_result(profile, q_id, question, expected, selected, confidence, params JSON, missing, row_count, ok, model, version, run_id, date)`: one row per `make eval` question with the `tag_cache` `run_id` it used; `make eval` reads one run_id only, so it is reproducible for a given run_id and reports whether it matches the previous eval of that run_id

## Scenario

A French SME participates in three synthetic European projects: LUMEN, GRAPHIA and OPENSCIENCE. Expenses include personnel, travel, equipment, subcontracting and other goods/services.

All grant agreement IDs, budgets and expense records are fictional and intended only for demonstration.
