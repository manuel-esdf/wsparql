# Architecture overview

A natural-language question is sent to Ollaya with a choice over all predefined SPARQL queries plus `none`. The model sees ontology labels in place of opaque IRIs, but execution always uses the original trusted query.

After selection, the pipeline finds named parameter values or asks constrained choices over ABOX values. Named reporting periods and date parsing supply date boundaries. Missing required parameters stop execution; absent optional parameters leave variables free.

rdflib executes the selected query using bound parameters and displays the rows. A `none` choice or confidence below 0.4 produces “no suitable query.”

The ontology and CSV source data produce the committed ABOX through a deterministic ETL. There is no model preprocessing before answering questions.

`make eval` runs this same path on every labeled test question and stores a new completed evaluation in SQLite. See [architecture details](ARCHITECTURE.md) and [ABOX generation](GENERATE-ABOX.md).
