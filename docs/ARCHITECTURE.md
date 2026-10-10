# Architecture

## Profile inputs

`Profile` loads the ontology and ABOX into one rdflib graph, the YAML query catalog, trusted `.rq` files, test questions, optional expected results and the profile version. Catalog entries declare required `params` and `optional` parameters with example values. The top-level `parameters` dictionary specifies how each value is found: a property label, a list of words, or a date.

The ontology supplies CSV schema and literal types during ETL, labels for readable SPARQL, and the domains and values of properties used during parameter extraction. See [ABOX generation](GENERATE-ABOX.md).

## Direct selection

`Profile.readable` replaces ontology IRIs with labels and compacts the query text while retaining PREFIX declarations. `pipeline.select` sends the question as state and one `choice` to `/v1/systemone`. Its criteria contain every catalog query's readable SPARQL plus `none`; instructions explain that parameters will be supplied afterwards. Query competency questions remain useful display text but are not selection criteria.

The model never writes SPARQL. Its selected catalog ID is accepted only if confidence is at least the profile’s `min-confidence` (default 0.4) and the choice is not `none`. This was formerly the direct fallback; there is now one routing path.

The entire catalog must fit the model's context. A larger catalog may require a different selection strategy.

## Parameters and execution

`extract_params` first searches ABOX property values as whole words, case-insensitively, with the longest matching value first. Otherwise, property-backed parameters use a constrained `choice` over their values plus `none`. Word-list parameters use explicit matches. Named reporting periods supply start/end dates; otherwise quarter, month and year patterns derive date boundaries.

`answer` checks that every required parameter is present, then calls `Profile.run`. Optional values remain unbound when not found. Execution uses the original query with rdflib `initBindings`; no string templating is applied. The output contains selection confidence and probabilities, parameters, extraction explanations, missing values and the result table.

## Evaluation storage

Only `eval` opens the shared `profile/profile.db`. `ProfileDb` creates `direct_eval` with columns:

`profile, q_id, question, expected, selected, confidence, params, missing, row_count, ok, model, version, run_id, date, min_confidence, parameter_min_confidence`.

`params` is JSON. `row_count` is NULL when no query ran. A completed invocation has a new independent run ID, allocated from existing direct evaluation rows. All results are inserted in one transaction after every scored question completes; interrupted runs store nothing. The CLI compares the run with the latest evaluation of the same profile/model/version and both cutoffs. Runs are intended to execute sequentially.

Legacy benchmark tables in an existing database are preserved but never read or written by the current code. New direct scores are isolated from historical combined-route scores.

## Confidence configuration and experiments

The catalog's top-level `min-confidence` is validated as a numeric value in [0, 1], rejecting booleans, strings and non-finite numbers. If absent, it defaults to 0.4. `Profile.min_confidence` controls query acceptance. `Profile.parameter_min_confidence` controls model-based parameter acceptance, configured with `parameter-min-confidence`; when omitted, it inherits the query cutoff at load time. Both are validated independently. Exact equality passes. A model choice of `none` never becomes a query or parameter, even at threshold zero.

Existing `direct_eval` tables gain a `min_confidence` column on first open, with existing rows assigned the previous fixed cutoff 0.4. A second column, `parameter_min_confidence`, records the parameter cutoff; migration copies each existing row’s formerly shared `min_confidence` value into it. New runs record both cutoffs and previous-run comparisons match both alongside model/profile/version.

`scripts/confidence-sweep.py` evaluates configured cutoffs with one response per distinct question/request pair. It caches raw selection and parameter choices within the experiment; each cutoff replays those responses through the normal `answer` path, including parameter acceptance and actual query execution. This avoids sampling changes between cutoffs. It records per-question outcomes, in-domain scores, off-topic rejection scores, missing parameters and failed IDs outside the normal evaluation database. `--parameter-thresholds` tests a Cartesian grid with independent parameter cutoffs; omitted values use matching query and parameter cutoffs. `--replay` loads saved responses by exact request and makes no model calls, failing on a missing request. Profile YAML files are not modified. Results are exploratory on the existing test set, not held-out estimates.

## Validation

Offline tests cover full-catalog selection criteria, rejection thresholds, parameter extraction, bound execution, evaluation history, transactional writes, ETL round trips and the expected-SPARQL cases for both profiles. `eval` uses the same `answer` function as the demo. A scored question must select the expected catalog ID and return rows, or produce no result when the expected answer is `none`. Exact natural-language parameter correctness is not scored.
