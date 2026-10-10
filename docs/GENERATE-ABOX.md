# Generating `abox.ttl` from `csv/*.csv` and `tbox.ttl`

`make abox` (`uv run python -m wsparql abox`) calls `wsparql/etl.py`, which reads the profile directory
(`profile/eu-expense-poc/`) and writes `abox.ttl` next to `tbox.ttl`:

```
tbox.ttl  ─┐  (schema: classes, properties, ranges, category individuals; opaque IRIs, rdfs:label = the name)
           ├─► etl.build() ─► rdflib Graph ─► etl.write() ─► abox.ttl
csv/*.csv ─┘  (data: one file per class, one row per individual)
```

There is **no mapping file**. The TBOX IRIs are opaque (`ex:C06`, `ex:P14`, `ex:I02`: numbered classes, properties
and individuals, no meaning in the local name) and the name of a term is its `rdfs:label`. CSV names are those
labels, compared as slugs (`tags.slug`: lower case, camelCase split, non-alphanumerics to `-`), so the column
`expenseDate` matches the label `expense date` and `EuropeanProject.csv` matches `European project`. The namespace and
its prefix are those of the classes of `tbox.ttl` (`ex:` = `https://example.org/eu-expense#` here, `c3po:` in
`profile/c3po`); the ABOX ids are minted in it and `abox.ttl` is serialised with it. The TBOX is the schema and
decides how each cell becomes RDF.

## The mapping rules

| CSV element | becomes in `abox.ttl` | rule / TBOX lookup |
|---|---|---|
| file name `Expense.csv` | class `ex:C06` of every row | an `owl:Class` of `tbox.ttl` labeled `Expense` |
| column `id`, value `E003` | subject IRI `ex:E003` + `ex:E003 a ex:C06` | mandatory column, non-empty; ABOX ids are the CSV ids |
| other column, e.g. `amount` | predicate `ex:P14` | an `owl:ObjectProperty` or `owl:DatatypeProperty` labeled `amount` |
| cell of an `owl:DatatypeProperty` column | literal typed by its `rdfs:range` | `xsd:decimal` → `680.00`, `xsd:date` → `"2026-02-12"^^xsd:date`, `xsd:boolean` → `true`, `xsd:string` → plain `"…"` (no `^^xsd:string`) |
| cell of an `owl:ObjectProperty` column | IRI reference | a TBOX individual whose label matches (`Travel` → `ex:I02`), else the CSV row `ex:<cell>` (`chargedToWorkPackage=LUMEN-WP4` → `ex:LUMEN-WP4`) |
| cell `LUMEN\|GRAPHIA\|OPENSCIENCE` | one triple per value | `\|` separates several values |
| empty cell | no triple | e.g. `E001` has no `supplier` |

Column order does not matter; the header row names the properties.

## Worked example

`csv/Expense.csv`:

```csv
id,description,amount,expenseDate,eligible,incurredBy,chargedToWorkPackage,category,employee,supplier
E003,Trip to Brussels consortium meeting,680.00,2026-02-12,true,ESDF,LUMEN-WP4,Travel,AliceMartin,Eurostar
```

The TBOX tells the ETL what each column is:

```turtle
ex:C06 a owl:Class ; rdfs:label "Expense" .                                        # file stem -> class
ex:P14 a owl:DatatypeProperty ; rdfs:range xsd:decimal ; rdfs:label "amount" .      # literal, decimal
ex:P15 a owl:DatatypeProperty ; rdfs:range xsd:date ; rdfs:label "expense date" .   # column expenseDate
ex:P17 a owl:DatatypeProperty ; rdfs:range xsd:boolean ; rdfs:label "eligible" .
ex:P16 a owl:DatatypeProperty ; rdfs:range xsd:string ; rdfs:label "description" .
ex:P07 a owl:ObjectProperty ; rdfs:range ex:C05 ; rdfs:label "supplier" .          # reference
ex:P05 a owl:ObjectProperty ; rdfs:range ex:C07 ; rdfs:label "category" .
ex:I02 a ex:C07 ; rdfs:label "Travel" .                                            # cell Travel -> this individual
```

Result in `abox.ttl`:

```turtle
ex:E003 a ex:C06 ;
    ex:P03 ex:ESDF ;
    ex:P04 ex:LUMEN-WP4 ;
    ex:P05 ex:I02 ;
    ex:P06 ex:AliceMartin ;
    ex:P07 ex:Eurostar ;
    ex:P14 680.00 ;
    ex:P15 "2026-02-12"^^xsd:date ;
    ex:P16 "Trip to Brussels consortium meeting" ;
    ex:P17 true .
```

The `rdfs:range` of an object property (`ex:C05`) is **not** checked against the referenced row's class. The ETL
only requires the reference to exist (see "Validation" below).

### Multi-valued cell

`csv/Company.csv`: `ESDF,e-Science Data Factory,France,LUMEN|GRAPHIA|OPENSCIENCE` →

```turtle
ex:ESDF a ex:C01 ; ex:P18 "France" ; ex:P08 "e-Science Data Factory" ;
    ex:P01 ex:GRAPHIA, ex:LUMEN, ex:OPENSCIENCE .
```

### No inference, no redundant relations

A relation is stored once, in one direction, and the ETL adds nothing the CSVs do not say. There is no
`hasWorkPackage` (the inverse of `belongsToProject`, `ex:P02`) and no `chargedToProject` (the project is the one the
expense's work package belongs to): storing them would duplicate what is already in the graph and let the copies
drift. The queries walk the stored direction with an explicit join, plain graph matching, no reasoner:

```sparql
?project a ex:C02 ; ex:P09 ?acronym .          # European project, acronym
?workPackage ex:P02 ?project .                 # belongs to project
?expense a ex:C06 ; ex:P04 ?workPackage ; ex:P14 ?amount .   # Expense, charged to work package, amount
```

Written project-first and spelled out rather than as the path `ex:P04/ex:P02`: the query text is what the routing
fallback reads, and the path form cost it two questions. The committed `.rq` files carry no such
comments: the fallback gets the text with each opaque term replaced by its label in camelCase (`Profile.readable`:
`?expense a ex:Expense ; ex:chargedToWorkPackage ?workPackage ; ex:amount ?amount`), without its indentation and
blank lines (one choice over every query has to fit the model's context; the PREFIX lines stay, the model leans on
them), the wording that was measured before the IRIs became opaque (README, "Current score").

### References to TBOX individuals

Expense categories (`ex:I01` Personnel, `ex:I02` Travel, `ex:I03` Equipment, `ex:I04` Subcontracting, `ex:I05`
Other goods and services) are individuals declared in `tbox.ttl`, not CSV rows. A `category` cell holds the label
as a slug-equal name (`Travel`, `OtherGoodsAndServices`) and resolves to the TBOX individual; a cell that matches no
individual label is read as a CSV row id. Their triples stay in `tbox.ttl` and are not copied into `abox.ttl`; q02
reads their name through `rdfs:label`.

## Algorithm (`etl.build`)

1. Parse `tbox.ttl`. Index the classes, the properties (`owl:ObjectProperty` set plus an
   `owl:DatatypeProperty → rdfs:range` map) and the TBOX individuals by the slug of their `rdfs:label`
   (`tags.words`, which falls back to the local name when a term has no label).
2. For each `csv/*.csv`, in sorted order:
   1. look the stem up among the class labels, check that an `id` column exists and that every other column is a
      known property label;
   2. for each row, add `ex:<id> a <class>`, then for each non-empty value of each cell (split on `|`), add a
      reference (object property: TBOX individual by label, else `ex:<cell>`) or a typed literal (datatype property).
3. Check that every object of an object property is a subject in the ABOX or in the TBOX.
4. `etl.write` serialises the graph as Turtle (prefixes `ex:`, `xsd:`) to `abox.ttl`.

## Validation: what makes the build fail

`etl.build` raises `ValueError` and writes nothing when:

| error | example message |
|---|---|
| file stem matches no TBOX class label | `Invoice.csv: no class of tbox.ttl is labeled Invoice` |
| no `id` column | `Expense.csv: no id column` |
| column matches no TBOX property label | `Supplier.csv: colour is not a property of tbox.ttl` |
| empty `id` | `Expense.csv line 7: empty id` |
| value does not parse as its range (rdflib `Literal.ill_typed`) | `Expense.csv E003.expenseDate: '2026-13-01' is not a valid date` |
| reference to an unknown IRI (dangling) | `unknown references: Nobody` |

## Adding or changing data

- **New row**: add a line to the class CSV, then run `make abox`.
- **New column**: first declare the property in `tbox.ttl` (next free `ex:Pnn`, `owl:DatatypeProperty` with an
  `rdfs:range`, or `owl:ObjectProperty`, and an `rdfs:label`), then add the column named after the label.
- **Inverse or derived relation**: do not store it; join in the query (`?workPackage ex:P02 ?project`).
- **New class**: declare `ex:Cnn a owl:Class ; rdfs:label "Foo"` in `tbox.ttl`, then create `csv/Foo.csv` with an
  `id` column.
- **New category**: declare `ex:Inn a ex:C07 ; rdfs:label "..."` and use the slug-equal name in the `category` cells.

`abox.ttl` is derived but committed. `make test` (`test_csv_round_trip_equals_the_committed_abox`) rebuilds the graph
from the CSVs and compares it with the committed file, so a CSV edit without `make abox` fails the tests. The
current data is 29 rows in 6 files, which produce 179 triples (the same count as with the named IRIs of profile 1.3.0:
only the terms were renamed). The second profile, `profile/c3po`, was converted the other way round: its 11 CSV files
(347 rows) were written once from a curated Turtle A-Box and `make abox` rebuilds 2016 of its 2030 triples (see its
README for the two typing differences with the source and the two derived relations left out).
