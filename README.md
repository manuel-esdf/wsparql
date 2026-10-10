# wsparql

POC evaluating Ollaya for routing natural-language questions to predefined SPARQL queries on an ontology-backed knowledge graph.

The model chooses a trusted catalog query, extracts its parameters through constrained choices, and executes it with rdflib. It never generates SPARQL or free-form answers. Routing uses one direct choice over all catalog SPARQL queries plus `none`.

## Setup

```sh
cp .env.example .env
# Set OLLAYA_HOST, OLLAYA_MODEL and PROFILE.
make install
make ollaya-check
make test
make expected
make ollaya-smoke-test
make PROFILE=profile/eu-expense-poc answer Q="List LUMEN expenses for Q1 2026"
make eval
```

All three environment variables are required. `make PROFILE=profile/c3po OLLAYA_MODEL=winnow eval` overrides the configured profile and model for one invocation. The committed ABOX is ready to use; `make build` rebuilds it after CSV changes. No model preprocessing or cached assessments are needed.

## Profiles

- [eu-expense-poc](profile/eu-expense-poc/README.md), version 1.5.0: synthetic company expenses, 10 queries, 109 test questions (87 scored, including 14 off-topic).
- [c3po](profile/c3po/README.md), version 1.2.0: FAIR-IMPACT cost reporting, 13 queries and 29 scored competency questions.

Each profile contains `tbox.ttl`, source `csv/*.csv`, derived `abox.ttl`, `query-catalog.yaml`, trusted `queries/*.rq`, `tests/test-questions.yaml`, optional `tests/expected.json`, and `VERSION`.

## Decision process

1. Render catalog SPARQL for the model: replace opaque ontology IRIs with their `rdfs:label`, remove indentation and blank lines, retain PREFIX declarations. The executable query files remain unchanged.
2. Ask Ollaya one `choice` over every rendered query plus `none`. The instructions explain that parameters are filled in afterwards. `none` or confidence below 0.4 means no suitable query.
3. Extract declared parameters: use a value named in the question, otherwise a constrained choice over ABOX values plus `none`. Dates come from a named reporting period or quarter/month/year parsing. Missing required values stop execution; absent optional values leave variables unbound.
4. Execute the original catalog query with rdflib `initBindings` and show the result table.

This is the former direct-fallback path, now the only routing mode. The ontology provides the ETL schema, readable query labels and property values for parameter extraction.

## Commands

| Command | Purpose |
|---|---|
| `make` | List commands |
| `make install` | Install dependencies with uv |
| `make test` | Offline tests for selection, parameters, storage, ETL and expected results |
| `make ollaya-check` | Check tools, server and installed model |
| `make ollaya-smoke-test` | Select a query for the first test question |
| `make profile-check` | Check required files and catalog query files |
| `make build` / `make abox` | Rebuild ABOX from ontology and CSVs |
| `make sparql Q=<id> ARGS="param=value ..."` | Execute a query directly; no arguments uses catalog examples |
| `make expected` | Check expected row counts and values with supplied parameters |
| `make query-selection Q="..."` | Show direct query choice and probabilities |
| `make param-extraction Q="..."` | Show extracted values; no Q runs parameterized test examples |
| `make answer Q="..."` | Select, extract and execute; no Q uses the first test question |
| `make demo` | Answer every scored test question |
| `make eval` | Evaluate every scored test question and store a new run |
| `make clean` | Remove the configured ABOX, shared database and Python caches |

For changes from the previous routing workflow, see [migration to direct selection](docs/MIGRATION-DIRECT-SELECTION.md).

## Examples

Run these from the repository root; explicit profile overrides make the examples independent of `PROFILE` in `.env`.

```sh
make PROFILE=profile/eu-expense-poc answer Q="List LUMEN expenses for Q1 2026"
make PROFILE=profile/c3po answer Q="What is the hourly rate for each employee?"
make PROFILE=profile/c3po query-selection Q="List all reporting periods of project FAIR-IMPACT."
make PROFILE=profile/c3po OLLAYA_MODEL=winnow eval
make PROFILE=profile/c3po OLLAYA_MODEL=decider eval
```

`answer` prints every catalog query's probability, the selected query and confidence, extracted parameters with explanations, and the result rows. The competency questions in this table are display labels; selection uses the readable SPARQL text. The selected query's probability and the model's reported confidence are separate values.

A rejected choice prints `no suitable query`. If a query is selected but required parameters are missing, it prints their names and skips execution. C3PO's parameters are optional; the expense profile has required parameters on q02 and q10.

## Evaluation history

`make eval` needs only the profile files and a running Ollaya model. It evaluates every question with `expected_query`, stores the completed run atomically in `profile/profile.db` table `direct_eval`, and compares selections, rounded confidences, row counts and correctness with the previous run for the same profile/model/version. Interrupted runs store no evaluation rows. Each completed invocation gets an independent run ID. Existing legacy benchmark tables are left untouched and are not used by the application.

A question passes when its expected query is selected and returns rows, or an expected `none` produces no result. This is a routing score; it does not validate exact extracted parameters or answer values. `make expected` separately checks query execution with supplied parameters. `make eval` exits 1 when any scored question fails.

The [historical model benchmark](docs/MODEL-BENCHMARK-REPORT.md) compares the former routing approaches. Its direct-baseline results correspond to the current selection path; combined-route results do not describe the simplified implementation.

## Code and documentation

- `wsparql/ollaya.py`: minimal stdlib HTTP client for `/v1/systemone`.
- `wsparql/pipeline.py`: direct selection, parameter extraction and execution.
- `wsparql/profile.py`: profile loading, readable SPARQL and bound query execution.
- `wsparql/etl.py`: ontology and CSV conversion to ABOX.
- `wsparql/db.py`: direct evaluation history in SQLite.
- `wsparql/__main__.py`: CLI behind the Makefile.
- [Migration from tag routing](docs/MIGRATION-DIRECT-SELECTION.md).
- [Architecture overview](docs/ARCHITECTURE-OVERVIEW.md), [architecture details](docs/ARCHITECTURE.md), [ABOX generation](docs/GENERATE-ABOX.md).

Python ≥ 3.12, uv, rdflib and pyyaml; stdlib urllib and sqlite3. No external triple store or HTTP application server.
