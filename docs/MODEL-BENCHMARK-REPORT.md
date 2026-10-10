> Historical benchmark: recorded before routing was simplified to direct selection only. Combined-route scores below describe the former implementation. Direct-baseline scores correspond to the current selection path.

# Ollaya model benchmark — C3PO 1.2.0

Measured 2026-10-10 against the local Ollaya server: Laya and Winnow first, then Decider and Kev. Same 29 labeled questions, 13 catalog queries, 41 ontology-derived tags, prompts, top-5 ranking, tag threshold 0.5 and selection confidence threshold 0.4. Each model has freshly generated catalog and question tags. Model calls ran sequentially. No prompts, thresholds or source code were changed for the Decider/Kev extension; `.env` remains unchanged.

| Model | Installed ID | Listed size |
|---|---|---:|
| laya:latest | 89aa53ce17e1 | 11 KB (alias) |
| winnow:latest | 8d72fee0e5f9 | 13 GB |
| decider:latest | 5507d6f80e9a | 3.8 GB |
| kev:latest | c0e732655dc9 | 9.5 GB |

Installed Laya variants were `laya:en` and `laya:multilingual`; this comparison uses the default `laya` alias, not explicit variant comparisons.

## Scores and timings

| Measure | Laya | Winnow | Decider | Kev |
|---|---:|---:|---:|---:|
| Full pipeline with direct fallback | 22/29 (75.9%) | 27/29 (93.1%) | 25/29 (86.2%) | 20/29 (69.0%) |
| Tag route alone | 10/29 (34.5%) | 17/29 (58.6%) | 25/29 (86.2%) | 17/29 (58.6%) |
| Direct baseline without tags | 21/29 (72.4%) | 27/29 (93.1%) | 26/29 (89.7%) | 11/29 (37.9%) |
| Catalog tag assessment | 9.35 s | 160.02 s | 130.15 s | 343.44 s |
| Question tag assessment | 19.79 s | 333.89 s | 169.89 s | 541.86 s |
| Total tag preparation | 29.14 s | 493.91 s | 300.04 s | 885.30 s |
| Full evaluation, cached tags | 5.19 s | 177.47 s | 36.55 s | 421.25 s |
| Direct baseline evaluation | 3.42 s | 347.77 s | 255.50 s | 810.96 s |

For the current direct-only path, Winnow scored 27/29, Decider 26/29, Laya 21/29 and Kev 11/29. Decider's listed size is 3.8 GB versus Winnow's 13 GB, with one fewer correct routing answer on this small C3PO sample. These are historical direct-baseline measurements, not a fresh evaluation of the simplified CLI.

These are single-run wall-clock measurements, including server/model loading effects. Some runs used CPU instead of GPU, so timing ratios do not establish relative model performance. Use accuracy and installed model size when interpreting this comparison. All questions are in-domain; rejection of unrelated questions was not tested. No thresholds were tuned to these results.

## Failed question IDs

| Model | Full pipeline | Direct baseline |
|---|---|---|
| laya | 1, 14, 15, 24, 25, 27, 28 | 1, 4, 5, 14, 15, 24, 25, 28 |
| winnow | 4, 15 | 4, 15 |
| decider | 1, 4, 14, 15 | 4, 14, 15 |
| kev | 1, 2, 4, 15, 19, 20, 24, 25, 28 | 1, 2, 4, 5, 6, 7, 8, 10, 12, 15, 19, 20, 24, 25, 26, 27, 28, 29 |

Every model misses question 15, "List all ERP of project FAIR-IMPACT." Laya answers travel-total question 4 correctly, while the other three full pipelines miss it. Decider's four full-pipeline failures (1, 4, 14, 15) are accepted wrong selections, so the fallback is not invoked for them.

## Full-pipeline failures and selected queries

| ID | Question | Expected | Laya | Winnow | Decider | Kev |
|---|---|---|---|---|---|---|
| 1 | What is the total personnel cost for the project FAIR-IMPACT in ERP3? | q01-expenditure-by-reporting-period | q07-personnel-cost-of-employee-by-year | q01-expenditure-by-reporting-period | q05-employees-on-project | none |
| 2 | How many person-months were spent in WP4 during ERP1 for the project FAIR-IMPACT? | q02-person-months-by-work-package | q02-person-months-by-work-package | q02-person-months-by-work-package | q02-person-months-by-work-package | none |
| 4 | What is the total travel cost for ERP1 for the project FAIR-IMPACT? | q01-expenditure-by-reporting-period | q01-expenditure-by-reporting-period | q03-travel-events | q03-travel-events | none |
| 14 | What is the duration of ERP1 on project FAIR-IMPACT? | q09-reporting-periods-of-project | none | q09-reporting-periods-of-project | q13-person-months-of-task | q09-reporting-periods-of-project |
| 15 | List all ERP of project FAIR-IMPACT. | q09-reporting-periods-of-project | q10-work-packages-of-project | none | q10-work-packages-of-project | none |
| 19 | What is the travel cost of travel event "Dagstuhl Workshop 2023" for FAIR-IMPACT? | q03-travel-events | q03-travel-events | q03-travel-events | q03-travel-events | none |
| 20 | What is the travel destination of travel event "Dagstuhl Workshop 2023" for FAIR-IMPACT? | q03-travel-events | q03-travel-events | q03-travel-events | q03-travel-events | none |
| 24 | What is the salary gross of employee 1 in 2023? | q07-personnel-cost-of-employee-by-year | q06-hours-by-employee | q07-personnel-cost-of-employee-by-year | q07-personnel-cost-of-employee-by-year | none |
| 25 | What is the patronal contribution to the salary of employee 1 in 2023? | q07-personnel-cost-of-employee-by-year | q04-hourly-rate-by-employee-and-year | q07-personnel-cost-of-employee-by-year | q07-personnel-cost-of-employee-by-year | none |
| 27 | What is the list of projects? | q12-all-projects | q10-work-packages-of-project | q12-all-projects | q12-all-projects | q12-all-projects |
| 28 | How many working hours has each employee logged in May 2025? | q06-hours-by-employee | q04-hourly-rate-by-employee-and-year | q06-hours-by-employee | q06-hours-by-employee | none |

## Validation and interpretation

Laya originally assigned no tags above threshold to catalog queries q03 (travel events) and q12 (all projects), exposing a division by zero in `pipeline.candidates`. At benchmark time, queries with an empty tag list were given score zero and remained eligible as candidates or through direct fallback. All four models were evaluated with that fix; the then-current 18 offline tests passed. Tag ranking and its tests have since been removed. All 29 independent expected-SPARQL cases passed before the original benchmark; execution code and profile data were unchanged for the extension.

The evaluation metric checks that the expected query is selected and returns at least one row. It does not validate extracted parameters or exact returned answers per natural-language question. For example, Laya question 13 passes the routing metric while returning four rows versus Winnow's one row. The separate expected-SPARQL cases validate execution with supplied parameters, not model extraction. Evaluation exit code 1 means at least one scored question failed; all evaluations completed and produced 29 question results.

SQLite runs:

| Model | Catalog tags run | Question tags / evaluation run |
|---|---:|---:|
| Laya | 4 | 5 |
| Winnow | 6 | 7 |
| Decider | 8 | 9 |
| Kev | 10 | 11 |

This report was copied from the original experiment output. Its raw logs and timing files are not included alongside this document; the run IDs above refer to the historical local database, whose contents depend on whether it has been retained.

## Forced-fallback experiments

These experiments retried only questions whose expected answers showed that the combined route had failed. They do not measure direct selection on the complete question set.

| Profile | Model | Original combined score | Failed questions retried | Recovered | Hypothetical score after replacing known failures |
|---|---|---:|---:|---:|---:|
| c3po 1.2.0 | Winnow | 27/29 | 2 | 0 | 27/29 |
| c3po 1.2.0 | Decider | 25/29 | 4 | 1 | 26/29 |
| eu-expense-poc 1.5.0 | Winnow | 86/87 | 1 | 0 | 86/87 |
| eu-expense-poc 1.5.0 | Decider | 70/87 | 17 | 6 | 76/87 |

On eu-expense-poc, 87 questions were scored (73 in-domain and 14 off-topic), with 22 unscored questions skipped. Winnow's only failure was question 67, "Show the personnel expenditure for OPENSCIENCE." Forced fallback repeated the original `none` decision. Decider recovered IDs 1, 26, 61, 69, 70 and 98; five off-topic questions remained incorrectly accepted (45, 50, 101, 103, 106). The original tag route alone scored 74/87 for Winnow and 71/87 for Decider.

The hypothetical scores use expected labels to identify failures. They are not production routing-policy scores and do not prove that direct selection alone is more accurate. The eu-expense forced-retry experiment did not evaluate the direct route on every scored question, so its direct-only score is not available from that experiment.

## Evaluate the current direct-only implementation

From the repository root, with `.env` configured:

```sh
make PROFILE=profile/c3po OLLAYA_MODEL=winnow eval
make PROFILE=profile/c3po OLLAYA_MODEL=decider eval
make PROFILE=profile/eu-expense-poc OLLAYA_MODEL=winnow eval
make PROFILE=profile/eu-expense-poc OLLAYA_MODEL=decider eval
```

Each command now performs direct selection on all labeled questions, extracts parameters, executes the chosen query and stores a new run in `direct_eval`. No preprocessing is required. Exit code 1 means at least one scored answer failed. Historical combined-route experiments require the earlier implementation; its commands are not supported by the current code. See [migration notes](MIGRATION-DIRECT-SELECTION.md).
