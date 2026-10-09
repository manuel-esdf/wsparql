"""Minimal ETL: csv/*.csv + tbox.ttl -> abox.ttl. Convention, the TBOX is the schema: file stem = class, column = property
local name, `id` = IRI local name, `|` separates several values in a cell, empty cell = no triple. The TBOX decides whether
a column is a reference (owl:ObjectProperty) or a literal and its datatype (rdfs:range); owl:inverseOf pairs are
materialised so a relation is stored once."""
import csv
from pathlib import Path

from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, Namespace

SEP = "|"


def build(path):
    """Graph of path/csv/*.csv typed by path/tbox.ttl; ValueError on an unknown file or column, an empty id,
    an ill-typed value or a dangling reference."""
    path = Path(path)
    tbox = Graph().parse(path / "tbox.ttl")
    ns = Namespace(dict(tbox.namespaces())["ex"])  # ponytail: the profile prefix is ex in queries and ontology alike
    rng = {p: tbox.value(p, RDFS.range) for p in tbox.subjects(RDF.type, OWL.DatatypeProperty)}
    objs = set(tbox.subjects(RDF.type, OWL.ObjectProperty))
    g = Graph(bind_namespaces="core")
    g.bind("ex", ns)
    for f in sorted((path / "csv").glob("*.csv")):
        cls = ns[f.stem]
        if (cls, RDF.type, OWL.Class) not in tbox:
            raise ValueError(f"{f.name}: {f.stem} is not a class of tbox.ttl")
        with f.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            cols = reader.fieldnames or []
            if "id" not in cols:
                raise ValueError(f"{f.name}: no id column")
            if unknown := [c for c in cols if c != "id" and ns[c] not in objs and ns[c] not in rng]:
                raise ValueError(f"{f.name}: {', '.join(unknown)} is not a property of tbox.ttl")
            for row in reader:
                if not (rid := row.pop("id")):
                    raise ValueError(f"{f.name} line {reader.line_num}: empty id")
                s = ns[rid]
                g.add((s, RDF.type, cls))
                for col, cell in row.items():
                    p = ns[col]
                    for v in filter(None, (cell or "").split(SEP)):
                        if p in objs:
                            g.add((s, p, ns[v]))
                        else:  # ponytail: xsd:string -> plain literal, what hand-written Turtle produces
                            lit = Literal(v, datatype=None if rng[p] == XSD.string else rng[p])
                            if lit.ill_typed:
                                raise ValueError(f"{f.name} {rid}.{col}: {v!r} is not a valid {rng[p].fragment}")
                            g.add((s, p, lit))
    for p, q in list(tbox.subject_objects(OWL.inverseOf)):
        for a, b in (p, q), (q, p):
            for s, o in list(g.subject_objects(a)):
                g.add((o, b, s))
    known = set(g.subjects()) | set(tbox.subjects())  # TBOX individuals (expense categories) are valid references
    if dangling := {o for p in objs for o in g.objects(None, p)} - known:
        raise ValueError("unknown references: " + ", ".join(sorted(o.fragment for o in dangling)))
    return g


def write(path):
    """Build and write path/abox.ttl; returns (file path, triple count)."""
    g = build(path)
    out = Path(path) / "abox.ttl"
    out.write_text(g.serialize(format="turtle"), encoding="utf-8")
    return out, len(g)
