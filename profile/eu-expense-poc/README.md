# EU Project Expense POC Dataset

Synthetic RDF dataset designed to demonstrate natural-language routing to predefined SPARQL queries.

## Files

- `VERSION`: profile version (semver), bump when tags, catalog, queries or data change
- `tbox.ttl`: domain ontology
- `abox.ttl`: synthetic company, projects, work packages, employees, suppliers and expenses
- `queries/`: 10 predefined SPARQL queries
- `query-catalog.yaml`: query descriptions and routing tags
- `tags.yaml`: controlled tag dictionary
- `demo-questions.yaml`: example natural-language questions with expected query IDs

## Scenario

A French SME participates in three synthetic European projects: LUMEN, GRAPHIA and OPENSCIENCE. Expenses include personnel, travel, equipment, subcontracting and other goods/services.

All grant agreement IDs, budgets and expense records are fictional and intended only for demonstration.
