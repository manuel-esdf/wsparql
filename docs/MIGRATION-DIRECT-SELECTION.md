# Migrating to direct selection

The former direct fallback is now the only routing path: one Ollaya choice over every catalog SPARQL query plus `none`, followed by parameter extraction and execution. The choice prompt and readable query rendering are retained. The confidence threshold is now configured by `min-confidence` in the profile catalog, with the previous value 0.4 as its default. `parameter-min-confidence` sets an independent parameter cutoff; when omitted, it inherits `min-confidence`.

## Command changes

| Previous workflow | Current workflow |
|---|---|
| `make build` generated ABOX and model assessments | `make build` rebuilds only the ABOX |
| `make ontology-tags-gen`, `make cq-tag-assessment`, `make question-tag-assessment` | Removed; no replacement or preprocessing needed |
| `make tags`, `make query-ranking` | Removed |
| `make query-selection Q="..."` ranked candidates before selecting | Same command now selects over all catalog SPARQL queries |
| `make eval-direct` ran a printed-only direct baseline | Use `make eval`; direct scores are now stored |
| `make eval` used cached model assessments | Same command now runs direct selection on every labeled question |
| `make answer` and `make demo` used two routing paths | Same commands now use direct selection only |

No configuration change is required. Keep `OLLAYA_HOST`, `OLLAYA_MODEL` and `PROFILE` in `.env`. An existing committed ABOX can be used immediately:

```sh
make PROFILE=profile/eu-expense-poc answer Q="List LUMEN expenses for Q1 2026"
make PROFILE=profile/eu-expense-poc OLLAYA_MODEL=winnow eval
```

## Output changes

The selection table shows each catalog query's probability and competency question as display text. The model selects using readable SPARQL, not the competency question. There are no ranking scores or route labels. An accepted selection shows its confidence, parameters and result rows; rejection shows `no suitable query`.

Evaluation starts with the model, profile version and a new run ID. Each question prints `ok` or `FAIL`, expected and selected query IDs, confidence, row count or missing parameters, and question text. The final score covers direct selection and execution. Exit code 1 indicates at least one failed answer.

## Evaluation history

New evaluations are stored in `profile/profile.db` table `direct_eval`. Their run IDs are independent of old assessment IDs. The CLI compares each completed evaluation with the latest direct evaluation for the same profile, model, version and both confidence thresholds.

Existing database tables and historical results remain on disk but are not used by current commands. No database cleanup or migration command is required. `make clean` removes the shared database and its history as well as the configured ABOX; rebuilding is unnecessary for this migration.

Historical combined-route scores and hypothetical improvements from retrying known failures should not be treated as current direct-only scores. Use `make eval` to measure the simplified implementation. See the [historical benchmark report](MODEL-BENCHMARK-REPORT.md).

## Ontology and catalog

The ontology still supplies the ETL schema, readable names for opaque SPARQL IRIs, and property information for parameter extraction. Catalog competency questions remain display labels. Required and optional parameters, bound query execution and test-question formats are unchanged.
