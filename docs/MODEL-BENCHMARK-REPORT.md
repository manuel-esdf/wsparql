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

Winnow has the highest full-pipeline routing score (27/29). Decider scores 25/29 with a 36.55-second cached-tag evaluation, about 4.9 times faster than Winnow's 177.47 seconds. Decider's direct baseline gains one correct answer but takes 255.50 seconds, about seven times its full evaluation time. Laya remains the fastest model, with a lower routing score (22/29).

Kev scores 20/29 with tags and fallback, versus 11/29 directly. Its 885.30-second tag preparation and 421.25-second full evaluation are the slowest in this comparison. Its direct baseline takes 810.96 seconds; low-confidence rejections account for many failures at the existing 0.4 threshold. These results do not support choosing Kev for this profile and configuration.

These are single-run wall-clock measurements, including server/model loading effects, rather than controlled latency benchmarks. All questions are in-domain; rejection of unrelated questions was not tested. No thresholds were tuned to these results.

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

Laya originally assigned no tags above threshold to catalog queries q03 (travel events) and q12 (all projects), exposing a division by zero in `pipeline.candidates`. Queries with an empty tag list now receive score zero and remain eligible as candidates or through direct fallback. All four models were evaluated with this fix. The regression test and existing offline suite pass (18 tests). All 29 independent expected-SPARQL cases passed before the original benchmark; execution code and profile data were unchanged for the extension.

The evaluation metric checks that the expected query is selected and returns at least one row. It does not validate extracted parameters or exact returned answers per natural-language question. For example, Laya question 13 passes the routing metric while returning four rows versus Winnow's one row. The separate expected-SPARQL cases validate execution with supplied parameters, not model extraction. Evaluation exit code 1 means at least one scored question failed; all evaluations completed and produced 29 question results.

SQLite runs:

| Model | Catalog tags run | Question tags / evaluation run |
|---|---:|---:|
| Laya | 4 | 5 |
| Winnow | 6 | 7 |
| Decider | 8 | 9 |
| Kev | 10 | 11 |

Full logs and `timings.json` are in this directory. The directory retains its original `laya-vs-winnow` name to preserve existing links.

## Reproduce

From the repository root, run these stages sequentially for each model (`laya`, `winnow`, `decider`, `kev`):

```sh
make PROFILE=profile/c3po OLLAYA_MODEL=decider cq-tag-assessment
make PROFILE=profile/c3po OLLAYA_MODEL=decider question-tag-assessment
make PROFILE=profile/c3po OLLAYA_MODEL=decider eval
make PROFILE=profile/c3po OLLAYA_MODEL=decider eval-direct
```

Replace `decider` with the desired model. Each evaluation intentionally exits nonzero if any answer fails.
