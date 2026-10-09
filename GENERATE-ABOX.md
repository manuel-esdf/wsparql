# Generating `abox.ttl` from `csv/*.csv` and `tbox.ttl`

`make abox` (`uv run python -m wsparql abox`) calls `wsparql/etl.py`, which reads the profile directory
(`profile/eu-expense-poc/`) and writes `abox.ttl` next to `tbox.ttl`:

```
tbox.ttl  ─┐  (schema: classes, properties, ranges, category individuals)
           ├─► etl.build() ─► rdflib Graph ─► etl.write() ─► abox.ttl
csv/*.csv ─┘  (data: one file per class, one row per individual)
```

There is **no mapping file**. The mapping is a naming convention: CSV names are ontology local names in the `ex:`
namespace (`https://example.org/eu-expense#`, read from the `ex` prefix of `tbox.ttl`). The TBOX is the schema and
decides how each cell becomes RDF.

## The mapping rules

| CSV element | becomes in `abox.ttl` | rule / TBOX lookup |
|---|---|---|
| file name `Expense.csv` | class `ex:Expense` of every row | the file stem must be an `owl:Class` in `tbox.ttl` |
| column `id`, value `E003` | subject IRI `ex:E003` + `ex:E003 a ex:Expense` | mandatory column, non-empty |
| other column, e.g. `amount` | predicate `ex:amount` | must be an `owl:ObjectProperty` or `owl:DatatypeProperty` in `tbox.ttl` |
| cell of an `owl:DatatypeProperty` column | literal typed by its `rdfs:range` | `xsd:decimal` → `680.00`, `xsd:date` → `"2026-02-12"^^xsd:date`, `xsd:boolean` → `true`, `xsd:string` → plain `"…"` (no `^^xsd:string`) |
| cell of an `owl:ObjectProperty` column | IRI reference `ex:<cell>` | `chargedToWorkPackage=LUMEN-WP4` → `ex:LUMEN-WP4` |
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
ex:Expense a owl:Class .                                    # file stem -> class
ex:amount a owl:DatatypeProperty ; rdfs:range xsd:decimal .  # literal, decimal
ex:expenseDate a owl:DatatypeProperty ; rdfs:range xsd:date .
ex:eligible a owl:DatatypeProperty ; rdfs:range xsd:boolean .
ex:description a owl:DatatypeProperty ; rdfs:range xsd:string .
ex:supplier a owl:ObjectProperty ; rdfs:range ex:Supplier .  # reference
ex:category a owl:ObjectProperty ; rdfs:range ex:ExpenseCategory .
```

Result in `abox.ttl`:

```turtle
ex:E003 a ex:Expense ;
    ex:amount 680.00 ;
    ex:category ex:Travel ;
    ex:chargedToWorkPackage ex:LUMEN-WP4 ;
    ex:description "Trip to Brussels consortium meeting" ;
    ex:eligible true ;
    ex:employee ex:AliceMartin ;
    ex:expenseDate "2026-02-12"^^xsd:date ;
    ex:incurredBy ex:ESDF ;
    ex:supplier ex:Eurostar .
```

The `rdfs:range` of an object property (`ex:Supplier`) is **not** checked against the referenced row's class. The ETL
only requires the reference to exist (see "Validation" below).

### Multi-valued cell

`csv/Company.csv`: `ESDF,e-Science Data Factory,France,LUMEN|GRAPHIA|OPENSCIENCE` →

```turtle
ex:ESDF a ex:Company ; ex:country "France" ; ex:name "e-Science Data Factory" ;
    ex:participatesIn ex:GRAPHIA, ex:LUMEN, ex:OPENSCIENCE .
```

### No inference, no redundant relations

A relation is stored once, in one direction, and the ETL adds nothing the CSVs do not say. There is no
`hasWorkPackage` (the inverse of `belongsToProject`) and no `chargedToProject` (the project is the one the
expense's work package belongs to): storing them would duplicate what is already in the graph and let the copies
drift. The queries walk the stored direction with an explicit join, plain graph matching, no reasoner:

```sparql
?project a ex:EuropeanProject ; ex:acronym ?acronym .
?workPackage ex:belongsToProject ?project .
?expense a ex:Expense ; ex:chargedToWorkPackage ?workPackage ; ex:amount ?amount .
```

Written project-first and spelled out rather than as the path `ex:chargedToWorkPackage/ex:belongsToProject`: the
raw query text is what the routing fallback reads, and the path form cost it two questions (README, "Fallback").

### References to TBOX individuals

Expense categories (`ex:Personnel`, `ex:Travel`, `ex:Equipment`, `ex:Subcontracting`, `ex:OtherGoodsServices`) are
individuals declared in `tbox.ttl`, not CSV rows. A `category` cell holds the local name (`Travel`) and resolves to
the TBOX individual. Their triples stay in `tbox.ttl` and are not copied into `abox.ttl`.

## Algorithm (`etl.build`)

1. Parse `tbox.ttl`. Collect the `owl:ObjectProperty` set and an `owl:DatatypeProperty → rdfs:range` map.
2. For each `csv/*.csv`, in sorted order:
   1. check that the stem is an `owl:Class`, that an `id` column exists and that every other column is a known property;
   2. for each row, add `ex:<id> a ex:<Stem>`, then for each non-empty value of each cell (split on `|`), add a
      reference (object property) or a typed literal (datatype property).
3. Check that every object of an object property is a subject in the ABOX or in the TBOX.
4. `etl.write` serialises the graph as Turtle (prefixes `ex:`, `xsd:`) to `abox.ttl`.

## Validation: what makes the build fail

`etl.build` raises `ValueError` and writes nothing when:

| error | example message |
|---|---|
| file stem is not a TBOX class | `Invoice.csv: Invoice is not a class of tbox.ttl` |
| no `id` column | `Expense.csv: no id column` |
| column is not a TBOX property | `Supplier.csv: colour is not a property of tbox.ttl` |
| empty `id` | `Expense.csv line 7: empty id` |
| value does not parse as its range (rdflib `Literal.ill_typed`) | `Expense.csv E003.expenseDate: '2026-13-01' is not a valid date` |
| reference to an unknown IRI (dangling) | `unknown references: Nobody` |

## Adding or changing data

- **New row**: add a line to the class CSV, then run `make abox`.
- **New column**: first declare the property in `tbox.ttl` (`owl:DatatypeProperty` with an `rdfs:range`, or
  `owl:ObjectProperty`), then add the column.
- **Inverse or derived relation**: do not store it; join in the query (`?workPackage ex:belongsToProject ?project`).
- **New class**: declare `ex:Foo a owl:Class` in `tbox.ttl`, then create `csv/Foo.csv` with an `id` column.

`abox.ttl` is derived but committed. `make test` (`test_csv_round_trip_equals_the_committed_abox`) rebuilds the graph
from the CSVs and compares it with the committed file, so a CSV edit without `make abox` fails the tests. The
current data is 29 rows in 6 files, which produce 179 triples.
